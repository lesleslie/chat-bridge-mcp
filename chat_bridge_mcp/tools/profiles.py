"""Tool profile registration groups for chat-bridge-mcp MCP server.

Maps ``ToolProfile`` levels to specific ``register_<group>_tools()``
call lists, controlling which tools are honored at module-load based on
the ``CHAT_BRIDGE_TOOL_PROFILE`` environment variable.

Profile tiers (single-tier; chat-bridge-mcp's tool surface is bound at
module import via ``@mcp.tool()`` decorators against the module-level
FastMCP singleton — chat-bridge-mcp does not lazily register groups,
so the profile dispatcher exists for env-var compliance + the standard
``discover_tools`` meta-tool; future dispatch work would refactor
``_tools.register_tools`` into per-group lambdas):

    MINIMAL:  No tool groups registered (only ``discover_tools`` meta-tool
              + /health HTTP route via ``mcp_common.health.register_http_health_route``).
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

    The ``register_chat_bridge_tools`` lambda re-invokes
    ``_tools.register_tools``, which is idempotent (guarded by the
    ``_tools_registered`` module-level flag set on first call from
    ``server.py``). It is a no-op on subsequent invocations, so the
    FULL profile effectively acknowledges the already-bound tool
    surface and ensures ``discover_tools`` is registered with the
    W0-canonical shape.

    chat-bridge-mcp exposes no MCP-registered health tools (only the
    /health HTTP route via ``register_http_health_route``), so the
    ``MANDATORY_GROUPS`` / ``essential_tool_names`` invariants are
    vacuously satisfied. We pass empty sets explicitly to opt out of
    the subset check.
    """
    from mcp_common.tools.dispatch import apply_tool_profile

    from chat_bridge_mcp._tools import register_tools

    def register_chat_bridge_tools(_server: FastMCP) -> None:
        """Idempotently bind ``@mcp.tool()`` decorators.

        ``_tools.register_tools`` is a no-op on subsequent calls (the
        first call from ``server.py`` set ``_tools_registered = True``).
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
