from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False


# Hard skip before any subprocess is spawned. pyproject.toml registers
# the `e2e` marker and asyncio_mode=auto, so the test can be async.
if os.environ.get("CHAT_BRIDGE_MCP_E2E") != "1":
    pytest.skip(
        "set CHAT_BRIDGE_MCP_E2E=1 to run e2e tests (also requires `npm install` "
        "inside tests/e2e/fixtures/electron)",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def electron_fixture() -> subprocess.Popen[bytes]:
    fixture_dir = Path(__file__).parent / "fixtures" / "electron"
    env = {**os.environ, "ELECTRON_ENABLE_LOGGING": "1"}
    proc = subprocess.Popen(
        ["npm", "start"],
        cwd=fixture_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not _wait_for_port("127.0.0.1", 9230, timeout_s=60.0):
        proc.kill()
        pytest.fail("electron fixture failed to expose CDP port 9230")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def bridge_proc(
    electron_fixture: subprocess.Popen[bytes],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    log_dir = tmp_path_factory.mktemp("logs")
    port = _free_port()
    env = {
        **os.environ,
        "CHAT_BRIDGE_MCP_HTTP_PORT": str(port),
        "CHAT_BRIDGE_MCP_SELECTORS_FILE": str(
            Path(__file__).parent / "fixtures" / "selectors.yaml"
        ),
        "CHAT_BRIDGE_MCP_STREAMING_TIMEOUT_SECONDS": "30",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "chat_bridge_mcp", "start"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not _wait_for_port("127.0.0.1", port, timeout_s=20.0):
        proc.kill()
        pytest.fail("bridge did not start within 20s")
    yield {"port": port, "proc": proc, "log_dir": str(log_dir)}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


async def _ask_chatgpt_via_http(http_port: int, prompt: str, *, timeout_s: float = 30.0) -> str:
    """Inline JSON-RPC client for /mcp tools/call.

    Mirrors tests/integration/test_server_lifecycle.py::_ask_chatgpt_via_http
    so this e2e test does not depend on the integration suite being collected.
    """
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{http_port}") as client:
        resp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "ask_chatgpt",
                    "arguments": {"prompt": prompt},
                },
            },
            timeout=timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        return body["result"]["content"][0]["text"]


async def test_real_chatgpt_input_set_with_react_setter_trick(
    electron_fixture: subprocess.Popen[bytes],
    bridge_proc: dict[str, object],
) -> None:
    """End-to-end smoke: drive the Electron fixture's textarea with the
    React-friendly setter via CDP, confirm reply text is reachable.

    Pinned by name in spec §9.1.
    """
    port = int(bridge_proc["port"])  # type: ignore[arg-type]
    text = await _ask_chatgpt_via_http(
        port, "Reply with the word 'pong'.", timeout_s=30
    )
    assert "pong" in text.lower()