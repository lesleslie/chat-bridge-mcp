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
