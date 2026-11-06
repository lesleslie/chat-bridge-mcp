"""Tool profile registration groups for chat-bridge-mcp MCP server.

Maps ``ToolProfile`` levels to specific ``register_<group>_tools()``
call lists, controlling which tools are honored at module-load based on
the ``CHAT_BRIDGE_TOOL_PROFILE`` environment variable.

Profile tiers (the dispatch in ``chat_bridge_mcp.server`` is the SOLE owner
of chat-bridge tool registration — the 6 ``@mcp.tool()`` decorators in
``_tools.py`` are bound by the selected profile's registration group, never
eagerly at import):

    MINIMAL:  No chat-bridge tool groups registered. The 4 Bodai baseline
              tools (``discover_tools``, ``get_liveness``, ``get_readiness``,
              ``health_check_all``) remain — ``bootstrap_baseline_tools``
              runs for every profile — and the /health HTTP route is
              registered via ``mcp_common.health.register_http_health_route``.
    FULL:     All 6 chat-bridge tools (``ask_chatgpt``, ``ask_claude``,
              ``forward_chatgpt``, ``forward_claude``, ``get_peer_health``,
              ``list_peers``) plus the 4 Bodai baseline tools
              (``discover_tools``, ``get_liveness``, ``get_readiness``,
              ``health_check_all``).
              Default behavior — matches pre-refactor module-load flow.

The dispatch surface (``PROFILE_REGISTRATIONS`` + ``registration_map``
+ ``apply_chat_bridge_tool_profile``) is consumed at module load in
``chat_bridge_mcp.server``, immediately after
``bootstrap_baseline_tools(mcp)`` registers the 4 canonical Bodai
baseline tools. The W0 dispatcher removes any pre-existing
``discover_tools`` (idempotent — first occurrence came from
``bootstrap_baseline_tools``) and re-registers a fresh one.

The sync ``apply_tool_profile`` wrapper at
``mcp_common/tools/dispatch.py:269`` is the correct entry point here:
the calling context is module import (synchronous, no event loop),
which the wrapper detects via ``asyncio.get_running_loop()`` and runs
the async implementation via ``asyncio.run()``. The async
``_apply_tool_profile`` helper at line 353 is reserved for callers
already inside an existing event loop (e.g. cmux-mcp's
``CmuxMCPServer.startup``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_common.tools import ToolProfile
from mcp_common.tools.dispatch import ALL_TOOLS

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

MINIMAL_REGISTRATIONS: list[str | Callable[[FastMCP], object] | object] = []

FULL_REGISTRATIONS: list[str | Callable[[FastMCP], object] | object] = [
    "chat_bridge_tools",
]

PROFILE_REGISTRATIONS: dict[
    ToolProfile,
    list[str | Callable[[FastMCP], object] | object] | type[ALL_TOOLS],
] = {
    ToolProfile.MINIMAL: MINIMAL_REGISTRATIONS,
    ToolProfile.FULL: FULL_REGISTRATIONS,
}


def apply_chat_bridge_tool_profile(server: FastMCP) -> None:
    """Apply the CHAT_BRIDGE_TOOL_PROFILE dispatch to ``server`` at module load.

    Sync because the calling context is module import — no event loop is
    running. The W0 helper's sync wrapper
    (``mcp_common.tools.dispatch.apply_tool_profile``) detects this and
    internally spins an event loop via ``asyncio.run()``.

    The ``register_chat_bridge_tools`` lambda calls ``_tools.register_tools``,
    which binds the 6 ``@mcp.tool()`` decorators against the module-level
    FastMCP singleton. It is idempotent (guarded by the ``_tools_registered``
    module-level flag), so the FULL profile binds the chat-bridge surface
    exactly once. Under MINIMAL this lambda is never invoked, so the
    chat-bridge tools are never bound at all.

    The dispatch must be the sole owner of registration: mcp-common's
    dispatcher can register a group but never unregister one, so binding the
    tools eagerly in ``server.py`` before the dispatch ran made the gate fail
    open (MINIMAL still exposed all 6 tools). Pinned by
    ``tests/integration/test_tool_profile_gating.py`` and
    ``tests/test_wiring.py::test_server_does_not_register_tools_eagerly``.

    chat-bridge-mcp exposes no MCP-registered health tools (only the
    /health HTTP route via ``register_http_health_route``), so the
    ``MANDATORY_GROUPS`` / ``essential_tool_names`` invariants are
    vacuously satisfied. We pass empty sets explicitly to opt out of
    the subset check.
    """
    from mcp_common.tools.dispatch import apply_tool_profile

    from chat_bridge_mcp._tools import register_tools

    def register_chat_bridge_tools(_server: FastMCP) -> None:
        """Bind the ``@mcp.tool()`` decorators for the chat-bridge group.

        ``_tools.register_tools`` is idempotent (guarded by the
        ``_tools_registered`` module-level flag), so the FULL profile binds
        the chat-bridge surface exactly once. Under MINIMAL this lambda is
        never invoked, so the chat-bridge tools are never bound at all.
        The W0 helper requires a ``register_all_fn`` callable when
        ``registrations[FULL]`` is a list of group names; we pass this
        idempotent wrapper so the helper's per-group call is safe.
        """
        register_tools()

    apply_tool_profile(
        server,
        profile_env_var="CHAT_BRIDGE_TOOL_PROFILE",
        registrations=PROFILE_REGISTRATIONS,
        registration_map={
            "chat_bridge_tools": register_chat_bridge_tools,
        },
        register_all_fn=register_chat_bridge_tools,
        mandatory_groups=set(),
        essential_tool_names=set(),
    )


__all__ = [
    "FULL_REGISTRATIONS",
    "MINIMAL_REGISTRATIONS",
    "PROFILE_REGISTRATIONS",
    "apply_chat_bridge_tool_profile",
]
