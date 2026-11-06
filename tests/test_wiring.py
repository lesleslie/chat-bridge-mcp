"""Verify chat_bridge_mcp.server wires apply_chat_bridge_tool_profile() at module load.

Mirrors the proven AST-walk pattern from
``mahavishnu/tests/unit/test_wiring.py:12::test_server_core_calls_apply_tool_profile``
(verified 2026-10-13) — the test parses the server module as AST and
checks that the production startup path calls either the sync
``apply_tool_profile`` or the per-repo
``apply_<repo>_tool_profile`` helper. The crackerjack-mirror test does
NOT exist (``crackerjack/tests/unit/test_wiring.py::test_apply_tool_profile_called``
is a phantom), so we mirror mahavishnu's pattern, not crackerjack's.
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_server_calls_apply_chat_bridge_tool_profile() -> None:
    server_path = Path("chat_bridge_mcp/server.py")
    tree = ast.parse(server_path.read_text())
    found = any(
        isinstance(node, ast.Call)
        and getattr(node.func, "id", "") in (
            "apply_tool_profile",
            "_apply_tool_profile",
            "apply_chat_bridge_tool_profile",
        )
        for node in ast.walk(tree)
    )
    assert found, (
        "chat_bridge_mcp/server.py must call apply_chat_bridge_tool_profile() "
        "or _apply_tool_profile() to wire the CHAT_BRIDGE_TOOL_PROFILE env var"
    )


def test_server_does_not_register_tools_eagerly() -> None:
    """The profile dispatch must be the SOLE owner of tool registration.

    ``server.py`` used to call ``_tools.register_tools()`` unconditionally at
    module import, before the profile dispatch ran. mcp-common's dispatch is
    additive-only — it can register a group but never unregister one — so
    binding the tools first made CHAT_BRIDGE_TOOL_PROFILE fail open: the
    ``minimal`` profile still exposed all 6 chat-bridge tools.

    The behavioral counterpart is
    ``tests/integration/test_tool_profile_gating.py``; this static guard
    catches the regression at the source instead of only at the surface.
    """
    server_path = Path("chat_bridge_mcp/server.py")
    tree = ast.parse(server_path.read_text())
    eager_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_tools"
    ]
    assert not eager_calls, (
        "chat_bridge_mcp/server.py must not call register_tools() directly — "
        "the profile dispatch owns registration. An eager call makes "
        "CHAT_BRIDGE_TOOL_PROFILE fail open because mcp-common's dispatch "
        "cannot unregister already-bound tools."
    )

