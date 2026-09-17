"""Integration tests for the bridge server lifecycle (Task 11b).

Named tests referenced by spec §9.1:
  - test_attach_succeeds_for_both_peers
  - test_health_envelope_carries_four_signal_per_component
  - test_attach_fails_when_cdp_port_busy
  - test_send_after_websocket_drop_raises_PeerNotAttachedError
  - test_detach_is_idempotent
  - test_concurrent_calls_pin_drop

Plus the tool-body tests pinned in spec §9.1:
  - test_ask_chatgpt_returns_plaintext_reply
  - test_peers_health_round_trip
  - test_out_of_order_response_raises_CDPProtocolError

Plus the chat-surface string pinning tests pinned in spec §9.1 + §10a.3.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import requests

from chat_bridge_mcp.exceptions import (
    CDPProtocolError,
    GuardrailFailure,
    PeerNotAttachedError,
    SelectorMissingError,
    SelectorUnmatchedError,
    StreamingTimeoutError,
)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def capture_file(tmp_path: Path) -> Path:
    """Temp file path for the fake CDP capture; pre-touched so the subprocess
    can append to it. Always pre-touched; the fake_cdp fixture wires the
    CHAT_BRIDGE_MCP_FAKE_CDP_CAPTURE_FILE env var to it. Tests that don't
    care about capture just ignore the file.
    """
    path = tmp_path / "cdp_capture.jsonl"
    path.write_text("")
    return path


@pytest.fixture
def fake_cdp(
    tmp_path_factory: pytest.TempPathFactory,
    capture_file: Path,
) -> dict[str, object]:
    """Boot tests/integration/_fake_cdp_server.py as a subprocess.

    It writes its bound ports to <tmp>/fake_cdp_ports.json which
    bridge_proc reads. Yields ``{"ports_file": Path, "proc": Popen,
    "capture_file": Path}`` so individual tests can interact with the
    fake CDP subprocess (e.g. terminate it to simulate WS drop) and
    read captured Runtime.evaluate expressions.

    The capture_file fixture is REQUESTED (always) so every test that
    uses fake_cdp gets a fresh capture file. Tests that don't care
    about capture simply ignore the ``capture_file`` field.

    Function-scoped (NOT module-scoped) so that destructive tests
    like test_send_after_websocket_drop_raises_PeerNotAttachedError
    that kill the fake CDP don't poison later tests in the same
    pytest process. Module scope would let one test's WS-drop kill
    every subsequent test's bridge startup.
    """
    ports_file = tmp_path_factory.mktemp("fake") / "ports.json"
    capture_path = Path(capture_file)
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.integration._fake_cdp_server"],
        env={
            **os.environ,
            "CHAT_BRIDGE_MCP_FAKE_CDP_PORTS_FILE": str(ports_file),
            "CHAT_BRIDGE_MCP_FAKE_CDP_CAPTURE_FILE": str(capture_path),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if ports_file.exists() and ports_file.read_text().strip():
            break
        time.sleep(0.1)
    else:
        proc.kill()
        stderr = proc.stderr.read() if proc.stderr else b""
        pytest.fail(
            f"fake CDP fixture did not write ports file in 30s; stderr={stderr[:500]!r}"
        )
    try:
        yield {"ports_file": ports_file, "proc": proc, "capture_file": capture_path}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def bridge_proc(
    fake_cdp: dict[str, object], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, object]:
    """Boot the bridge as a subprocess pointed at the fake CDP fixture."""
    ports = json.loads(Path(str(fake_cdp["ports_file"])).read_text())
    http_port = _free_port()
    settings_file = tmp_path_factory.mktemp("cfg") / "chat-bridge-mcp.yaml"
    env = {
        **os.environ,
        "CHAT_BRIDGE_MCP_HTTP_PORT": str(http_port),
        "CHAT_BRIDGE_MCP_CDP_CLAUDE_PORT": str(ports["claude_port"]),
        "CHAT_BRIDGE_MCP_CDP_CHATGPT_PORT": str(ports["chatgpt_port"]),
        "CHAT_BRIDGE_MCP_STREAMING_TIMEOUT_SECONDS": "10",
        "CHAT_BRIDGE_MCP_POLLING_INTERVAL_SECONDS": "0.3",
        "CHAT_BRIDGE_MCP_SETTINGS_FILE": str(settings_file),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "chat_bridge_mcp", "start"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{http_port}/health", timeout=0.5)
            if r.status_code == 200:
                break
        except Exception:  # noqa: BLE001 (intentional: poll until /health is ready)
            time.sleep(0.3)
    else:
        proc.kill()
        stderr = proc.stderr.read() if proc.stderr else b""
        pytest.fail(
            f"bridge did not start within 30s; stderr={stderr[:500]!r}"
        )
    try:
        yield {"proc": proc, "port": http_port}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _ask_chatgpt_via_http(http_port: int, prompt: str, *, timeout_s: float = 30.0) -> str:
    """HTTP client to call /mcp tools/call against the running bridge.

    Uses the raw JSON-RPC over HTTP transport the bridge exposes.
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


async def _ask_claude_via_http(http_port: int, prompt: str, *, timeout_s: float = 30.0) -> str:
    """HTTP client for the ask_claude tool (T16 mirror of _ask_chatgpt_via_http)."""
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{http_port}") as client:
        resp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "ask_claude",
                    "arguments": {"prompt": prompt},
                },
            },
            timeout=timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        return body["result"]["content"][0]["text"]


# ---------------------------------------------------------------------------
# Named tests referenced by spec §9.1
# ---------------------------------------------------------------------------


def test_attach_succeeds_for_both_peers(bridge_proc: dict[str, object]) -> None:
    """Pinned by name in spec §9.1: both peers attached at startup."""
    port = int(bridge_proc["port"])  # type: ignore[arg-type]
    body = requests.get(f"http://127.0.0.1:{port}/health", timeout=2).json()
    assert body["status"] == "ok"
    assert body["service"] == "chat-bridge-mcp"
    component_names = {c["name"] for c in body.get("components", [])}
    assert "claude" in component_names
    assert "chatgpt" in component_names


def test_health_envelope_carries_four_signal_per_component(bridge_proc: dict[str, object]) -> None:
    port = int(bridge_proc["port"])  # type: ignore[arg-type]
    body = requests.get(f"http://127.0.0.1:{port}/health", timeout=2).json()
    for c in body["components"]:
        if c["name"] not in ("claude", "chatgpt"):
            continue
        for required_key in (
            "entities_count",
            "errors_total",
            "cycles_total",
            "last_updated_timestamp",
        ):
            assert required_key in c, (
                f"{required_key} missing from peer component {c['name']}"
            )


def test_attach_fails_when_cdp_port_busy() -> None:
    """Pinned by name in spec §9.1: bridge exits non-zero when CDP port is busy.

    Implementation note: we point the bridge at a port that has nothing
    listening on it (`_free_port()` reserved but never bound). The bridge's
    GET to ``/json`` then fails with ConnectionRefusedError, which
    propagates as PeerNotAttachedError through the startup lifecycle.
    """
    busy_port = _free_port()
    env = {
        **os.environ,
        "CHAT_BRIDGE_MCP_HTTP_PORT": str(_free_port()),
        "CHAT_BRIDGE_MCP_CDP_CLAUDE_PORT": str(_free_port()),
        "CHAT_BRIDGE_MCP_CDP_CHATGPT_PORT": str(busy_port),
        "CHAT_BRIDGE_MCP_STRICT_MODE_ON_START": "true",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "chat_bridge_mcp", "start"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode != 0, (
        f"bridge started successfully despite chatgpt port {busy_port} being unreachable; "
        f"stdout={proc.stdout[:500]!r} stderr={proc.stderr[:500]!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert (
        "peernotattachederror" in combined
        or "not attached" in combined
        or "peer not attached" in combined
    ), (
        f"Expected PeerNotAttachedError in output, got stdout={proc.stdout[:500]!r} "
        f"stderr={proc.stderr[:500]!r}"
    )


def test_send_after_websocket_drop_raises_PeerNotAttachedError(
    bridge_proc: dict[str, object],
    fake_cdp: dict[str, object],
) -> None:
    """Killing the fake CDP server drops the bridge's WebSocket; the next
    ask_chatgpt call surfaces PeerNotAttachedError to the MCP client.
    """
    port = int(bridge_proc["port"])  # type: ignore[arg-type]
    cdp_proc = fake_cdp["proc"]  # type: ignore[assignment]
    assert isinstance(cdp_proc, subprocess.Popen)
    cdp_proc.terminate()
    cdp_proc.wait(timeout=5)
    # Allow the bridge to observe the WS drop on its own poll cycle.
    time.sleep(1.0)

    async def _post() -> dict[str, object]:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            r = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "ask_chatgpt", "arguments": {"prompt": "hi"}},
                },
                timeout=10,
            )
            return dict(r.json())

    body = asyncio.run(_post())
    # The bridge may surface this as an MCP error result OR as the chat-surface
    # string (depending on whether ask_chatgpt is implemented in _tools yet).
    # Accept either shape; the contract is "not attached" surfaces somewhere.
    if "error" in body:
        assert "not attached" in str(body["error"]).lower()
    else:
        text = body["result"]["content"][0]["text"]  # type: ignore[index]
        assert "not attached" in text.lower()


def test_detach_is_idempotent(bridge_proc: dict[str, object]) -> None:
    """Stop the bridge twice; second stop is a no-op."""
    proc = bridge_proc["proc"]  # type: ignore[assignment]
    assert isinstance(proc, subprocess.Popen)
    proc.terminate()
    proc.wait(timeout=5)
    r = subprocess.run(
        [sys.executable, "-m", "chat_bridge_mcp", "stop"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    # Exit codes: 0 = graceful, 1 = force-required, 2 = "Server not running"
    # (the mcp-common factory's status message). All three mean the
    # idempotency contract holds.
    assert r.returncode in (0, 1, 2)


@pytest.mark.asyncio
async def test_concurrent_calls_pin_drop(bridge_proc: dict[str, object]) -> None:
    """Two concurrent ask_chatgpt calls produce prompt-drop data corruption
    per §5.6 (NOT serialized in v1). Both calls return the second call's reply."""
    port = int(bridge_proc["port"])  # type: ignore[arg-type]

    async def call(prompt: str) -> str:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            r = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "ask_chatgpt", "arguments": {"prompt": prompt}},
                },
                timeout=10,
            )
            body = r.json()
            return body["result"]["content"][0]["text"]

    a, b = await asyncio.gather(call("prompt A"), call("prompt B"))
    assert a == b


# ---------------------------------------------------------------------------
# Tool-body tests (referenced by spec §9.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_chatgpt_returns_plaintext_reply(bridge_proc: dict[str, object]) -> None:
    port = int(bridge_proc["port"])  # type: ignore[arg-type]
    text = await _ask_chatgpt_via_http(port, "Reply with the word 'pong'.")
    # Fake CDP returns a fixed marker for innerText extraction; we assert
    # the tool body returns *something* plaintext-shaped, not a JSON error.
    assert text
    assert "not attached" not in text.lower()


@pytest.mark.asyncio
async def test_ask_claude_returns_plaintext_reply(bridge_proc: dict[str, object]) -> None:
    """T16 mirror of test_ask_chatgpt_returns_plaintext_reply — verifies
    the ask_claude tool round-trips through the bridge's /mcp transport,
    returning a plaintext reply (not a chat-surface error string).
    """
    port = int(bridge_proc["port"])  # type: ignore[arg-type]
    text = await _ask_claude_via_http(port, "Reply with the word 'pong'.")
    assert text
    assert "not attached" not in text.lower()


@pytest.mark.asyncio
async def test_peers_health_round_trip(bridge_proc: dict[str, object]) -> None:
    port = int(bridge_proc["port"])  # type: ignore[arg-type]
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        r = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_peer_health", "arguments": {"peer": "chatgpt"}},
            },
            timeout=5,
        )
    body = r.json()
    text = body["result"]["content"][0]["text"]
    health = json.loads(text)
    assert health["name"] == "chatgpt"
    assert health["attached"] is True
    assert health["errors_total"] == 0


@pytest.mark.asyncio
async def test_out_of_order_response_raises_CDPProtocolError() -> None:
    """Pure unit test (no bridge needed) — verifies CDPSession.send
    skips out-of-order responses (id mismatch) and only completes on
    the matching id; a stale `error` response (whose id matches) is
    surfaced as CDPProtocolError.
    """
    from chat_bridge_mcp.cdp import CDPSession

    sent: list[str] = []

    class FakeWS:
        async def send(self, msg: str) -> None:
            sent.append(msg)

        async def recv(self) -> str:
            # First respond with the wrong id (skipped), then the correct
            # id carrying a CDP error — CDPSession should raise.
            if not hasattr(FakeWS, "_step"):
                FakeWS._step = 0  # type: ignore[attr-defined]
            FakeWS._step += 1  # type: ignore[attr-defined]
            if FakeWS._step == 1:  # type: ignore[attr-defined]
                return json.dumps({"id": 999, "result": {}})  # stale → skipped
            return json.dumps(
                {
                    "id": 1,
                    "error": {"code": -32000, "message": "boom"},
                }
            )

    sess = CDPSession(FakeWS())
    with pytest.raises(CDPProtocolError, match="boom"):
        await asyncio.wait_for(sess.send("Runtime.evaluate"), timeout=2)
    assert sent, "FakeWS.send was never called"


# ---------------------------------------------------------------------------
# Chat-surface string pinning (referenced by spec §9.1 + §10a.3)
# ---------------------------------------------------------------------------


EXPECTED_CHAT_STRINGS: dict[type[Exception], str] = {
    PeerNotAttachedError: "{peer} peer is not attached. Run `chat-bridge-mcp restart`.",
    SelectorMissingError: "{peer} selectors missing. See settings/selectors.yaml.",
    SelectorUnmatchedError: (
        "{peer} selector did not match. "
        "Update settings/selectors.yaml and `chat-bridge-mcp restart`."
    ),
    StreamingTimeoutError: "{peer} response did not complete within {timeout}s.",
    GuardrailFailure: "Internal: prompt rejected by guardrail. Report as a bug.",
    CDPProtocolError: "{peer} CDP target returned an error. Run `chat-bridge-mcp restart`.",
}


# Per-exception context kwargs that must be passed into the constructor so
# _tool_error_string can read them via exc.context. Pinned per spec §10a.3.
_CONTEXT_FOR_EXC: dict[type[Exception], dict[str, object]] = {
    StreamingTimeoutError: {"timeout": 180},
}


@pytest.mark.parametrize(
    ("exc_cls", "template"),
    list(EXPECTED_CHAT_STRINGS.items()),
)
def test_chat_surface_string_for_exception(
    exc_cls: type[Exception], template: str
) -> None:
    """Pin the exact chat-surface strings for each BridgeError subclass."""
    from chat_bridge_mcp.server import _tool_error_string

    kwargs: dict[str, object] = {"peer": "chatgpt"}
    if exc_cls is StreamingTimeoutError:
        kwargs["timeout"] = 180
    if exc_cls is SelectorMissingError:
        kwargs["os"] = "macos"
    context = _CONTEXT_FOR_EXC.get(exc_cls, {})
    actual = _tool_error_string(exc_cls("test", peer="chatgpt", context=context))
    expected = template.format(**kwargs)
    assert actual == expected


def test_status_command_via_cli() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "chat_bridge_mcp", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    # Without a running bridge, status exits non-zero; that's the contract.
    assert r.returncode != 0


def test_version_command_prints() -> None:
    """The factory's `_cmd_version` prints via importlib.metadata. The
    output format is `<name>: <version>` (with colon, per mcp-common).
    """
    r = subprocess.run(
        [sys.executable, "-m", "chat_bridge_mcp", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "chat-bridge-mcp" in r.stdout
    assert ":" in r.stdout or r.stdout.strip() == "0.1.0"



# ---------------------------------------------------------------------------
# forward_chatgpt end-to-end (T17)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_chatgpt_wrapped_text_reaches_chatgpt_adapter(
    bridge_proc: dict[str, object],
    fake_cdp: dict[str, object],
) -> None:
    """T17 end-to-end: forward_chatgpt wraps source_reply in the nonce
    frame, and the WRAPPED text is what reaches the chatgpt adapter.

    Strategy: the fake CDP subprocess JSON-appends every Runtime.evaluate
    expression (CHAT_BRIDGE_MCP_FAKE_CDP_CAPTURE_FILE). The chatgpt adapter
    inlines the prompt as a JSON-escaped string in the JS source. The
    assertion scans the capture for at least one expression containing
    BOTH the relay-frame markers (``<<nonce=...>>``) AND the original
    ``source_reply`` substring.
    """
    import re

    capture_file_path = fake_cdp["capture_file"]  # type: ignore[assignment]
    assert capture_file_path is not None

    port = int(bridge_proc["port"])  # type: ignore[arg-type]
    source_reply = "test reply"
    source_peer = "claude"
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        resp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "forward_chatgpt",
                    "arguments": {
                        "source_peer": source_peer,
                        "source_reply": source_reply,
                        "ask_for_opinion": True,
                    },
                },
            },
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()

    assert "result" in body or "error" in body

    entries = [
        json.loads(line)
        for line in Path(str(capture_file_path)).read_text().splitlines()
        if line.strip()
    ]
    assert entries, "fake_cdp captured no Runtime.evaluate expressions"

    matched = [
        e for e in entries
        if "<<nonce=" in e["expression"] and source_reply in e["expression"]
    ]
    assert matched, (
        "forward_chatgpt did not inject the guardrail-wrapped text; "
        f"captured={[e['expression'][:200] for e in entries[-5:]]}"
    )

    for entry in matched:
        nonces = re.findall(r"<<nonce=([^>]+)>>", entry["expression"])
        assert len(nonces) >= 2
        assert nonces[0] == nonces[1]

    assert any(source_peer in e["expression"] for e in matched)
