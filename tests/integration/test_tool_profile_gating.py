"""Behavioral contract: CHAT_BRIDGE_TOOL_PROFILE must actually gate the
registered MCP tool surface.

Why this test exists
--------------------
``chat_bridge_mcp/server.py`` used to call ``_tools.register_tools()``
unconditionally at module import, *before* the profile dispatch ran. The
6 chat-bridge ``@mcp.tool()`` decorators were therefore bound no matter
which profile was selected. mcp-common's dispatch is additive-only — it
can register a group but never unregister one — so the gate failed open:
``minimal`` and ``full`` both exposed the full 10-tool surface.

These tests pin the fixed behavior end-to-end by importing the real module
in a subprocess with a controlled environment, because the profile is
resolved at import time against the module-level FastMCP singleton (the
same reason ``apply_tool_profile`` refuses to run inside a live event
loop). A subprocess is the only way to exercise a fresh import per profile.

Pinned contract
---------------
- ``full`` (and unset)      -> all 6 chat-bridge tools + all 4 baseline tools
- ``minimal``               -> 0 chat-bridge tools, all 4 baseline tools
- set-but-invalid value    -> startup fails with ``InvalidProfileError``
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

CHAT_BRIDGE_TOOLS = frozenset(
    {
        "ask_chatgpt",
        "ask_claude",
        "forward_chatgpt",
        "forward_claude",
        "list_peers",
        "get_peer_health",
    }
)

BASELINE_TOOLS = frozenset(
    {
        "discover_tools",
        "get_liveness",
        "get_readiness",
        "health_check_all",
    }
)

# Imports the real module, then writes the registered tool names to the
# path given as argv[1]. Writing to a file (rather than stdout) keeps the
# result immune to the logger's own stdout traffic.
_CHILD_PROGRAM = """
import asyncio
import json
import sys

from chat_bridge_mcp.server import mcp


async def main() -> None:
    names = sorted(tool.name for tool in await mcp.list_tools())
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        json.dump(names, handle)


asyncio.run(main())
"""


def _registered_tools(profile: str | None, out_file: Path) -> list[str]:
    """Import the server module with ``profile`` applied and return the
    registered tool names.

    ``profile=None`` leaves ``CHAT_BRIDGE_TOOL_PROFILE`` unset, which is
    the default deployment shape.
    """
    env = dict(os.environ)
    env.pop("CHAT_BRIDGE_TOOL_PROFILE", None)
    if profile is not None:
        env["CHAT_BRIDGE_TOOL_PROFILE"] = profile
    subprocess.run(
        [sys.executable, "-c", _CHILD_PROGRAM, str(out_file)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    return json.loads(out_file.read_text(encoding="utf-8"))


def test_full_profile_registers_chat_bridge_and_baseline_tools(tmp_path: Path) -> None:
    """The FULL profile exposes the complete 6 + 4 surface."""
    names = set(_registered_tools("full", tmp_path / "tools.json"))
    assert names >= CHAT_BRIDGE_TOOLS, f"chat-bridge tools missing: {sorted(names)}"
    assert names >= BASELINE_TOOLS, f"baseline tools missing: {sorted(names)}"


def test_unset_profile_defaults_to_full(tmp_path: Path) -> None:
    """An unset CHAT_BRIDGE_TOOL_PROFILE selects FULL, not an empty surface."""
    names = set(_registered_tools(None, tmp_path / "tools.json"))
    assert names >= CHAT_BRIDGE_TOOLS
    assert names >= BASELINE_TOOLS


def test_minimal_profile_withholds_chat_bridge_tools(tmp_path: Path) -> None:
    """The MINIMAL profile must NOT expose the tools that drive the desktop
    apps. This is the fail-open regression guard: before the fix, all 6
    chat-bridge tools were registered regardless of the selected profile.
    """
    names = set(_registered_tools("minimal", tmp_path / "tools.json"))
    leaked = CHAT_BRIDGE_TOOLS & names
    assert not leaked, (
        f"MINIMAL profile leaked chat-bridge tools: {sorted(leaked)}; "
        f"registered: {sorted(names)}"
    )


def test_minimal_profile_keeps_baseline_tools(tmp_path: Path) -> None:
    """The 4 Bodai baseline tools stay registered under MINIMAL — they carry
    no chat-surface access, and every Bodai server exposes them so the
    Claude Code picker can find the server.
    """
    names = set(_registered_tools("minimal", tmp_path / "tools.json"))
    assert names >= BASELINE_TOOLS, f"baseline tools missing: {sorted(names)}"


def test_invalid_profile_value_fails_startup(tmp_path: Path) -> None:
    """A set-but-invalid profile must raise rather than fall back to FULL.

    Falling back would silently re-expose the full tool surface to an
    operator who asked for a narrower one.
    """
    env = dict(os.environ)
    env["CHAT_BRIDGE_TOOL_PROFILE"] = "bogus"
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_PROGRAM, str(tmp_path / "tools.json")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert proc.returncode != 0, "invalid profile must not start the server"
    assert "InvalidProfileError" in proc.stderr, (
        f"expected InvalidProfileError, got stderr:\n{proc.stderr}"
    )


@pytest.mark.parametrize("profile", ["full", "minimal"])
def test_profile_gate_is_not_a_no_op(profile: str, tmp_path: Path) -> None:
    """The two profiles must produce *different* surfaces.

    A no-op gate (both profiles yielding the same tool set) is the exact
    failure this file guards against, so assert the difference directly
    rather than only the per-profile membership above.
    """
    names = set(_registered_tools(profile, tmp_path / f"{profile}.json"))
    chat_bridge_present = bool(CHAT_BRIDGE_TOOLS & names)
    assert chat_bridge_present is (profile == "full"), (
        f"profile={profile!r} exposed chat-bridge tools={sorted(names)}"
    )
