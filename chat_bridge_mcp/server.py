"""Chat-bridge-mcp server: lifecycle, /health, CLI factory wiring.

Spec §4 module-level mcp singleton: the FastMCP instance lives at import
time so the @mcp.tool() decorators in _tools.py bind against it. The
:class:`ChatBridgeServer` wraps the singleton and adds the
startup/shutdown/health_check methods the mcp-common CLI factory expects.
"""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp_common.bootstrap import bootstrap_baseline_tools
from mcp_common.cli import MCPServerCLIFactory
from mcp_common.health import register_http_health_route
from mcp_common.server import BaseOneiricServerMixin, RuntimeComponents, create_runtime_components

from chat_bridge_mcp import (
    __version__,
    _tools,
)
from chat_bridge_mcp.config import ChatBridgeConfig
from chat_bridge_mcp.exceptions import (
    BridgeError,
    CDPProtocolError,
    GuardrailFailure,
    PeerNotAttachedError,
    SelectorMissingError,
    SelectorUnmatchedError,
    StreamingTimeoutError,
)
from chat_bridge_mcp.peers.chatgpt import ChatGPTDesktopAdapter
from chat_bridge_mcp.peers.claude import ClaudeDesktopAdapter

# Module-level FastMCP singleton. _tools.register_tools() binds @mcp.tool()
# decorators against this instance at import time (Task 10). MUST stay
# module-level so that any code importing `from chat_bridge_mcp.server
# import mcp` gets the same instance regardless of how many
# ChatBridgeServer objects exist.
mcp = FastMCP("chat-bridge-mcp")
_tools.register_tools()

# Bodai baseline tools (discover_tools, get_liveness, get_readiness,
# health_check_all) — every Bodai MCP server exposes these so Claude Code's
# picker can find them. Registered after the chat-bridge tools so list_tools()
# returns the full 6 + 4 = 10 surface.
bootstrap_baseline_tools(mcp)


def _tool_error_string(exc: BridgeError) -> str:
    """Map a BridgeError to the user-facing chat-surface string per spec §10a.3.

    Pinned via tests/integration/test_server_lifecycle.py::
    test_chat_surface_string_for_exception.
    """
    # Per spec §10a.3: the chat surface is the operator-visible copy.
    # Templates use PEP 3101 str.format(**kwargs) with these keys per type:
    #   - PeerNotAttachedError: peer
    #   - SelectorMissingError: peer
    #   - SelectorUnmatchedError: peer, selector_name
    #   - StreamingTimeoutError: peer, timeout
    #   - GuardrailFailure: (none)
    #   - CDPProtocolError: peer
    if isinstance(exc, PeerNotAttachedError):
        return f"{exc.peer} peer is not attached. Run `chat-bridge-mcp restart`."
    if isinstance(exc, SelectorMissingError):
        return f"{exc.peer} selectors missing. See settings/selectors.yaml."
    if isinstance(exc, SelectorUnmatchedError):
        return (
            f"{exc.peer} selector did not match. "
            f"Update settings/selectors.yaml and `chat-bridge-mcp restart`."
        )
    if isinstance(exc, StreamingTimeoutError):
        timeout = (exc.context or {}).get("timeout", "?")
        return f"{exc.peer} response did not complete within {timeout}s."
    if isinstance(exc, GuardrailFailure):
        return "Internal: prompt rejected by guardrail. Report as a bug."
    if isinstance(exc, CDPProtocolError):
        return f"{exc.peer} CDP target returned an error. Run `chat-bridge-mcp restart`."
    return "internal error; see logs"


class ChatBridgeServer(BaseOneiricServerMixin):
    """Bridge server. Bound to the module-level `mcp` singleton."""

    # Narrow the mixin's `config: MCPBaseSettings | MCPServerSettings` to the
    # concrete ChatBridgeConfig so `validate_for_start` resolves. ChatBridgeConfig
    # extends BaseSettings (not OneiricMCPConfig, which is BaseModel-based and
    # silently drops SettingsConfigDict overrides — see config.py docstring).
    config: ChatBridgeConfig  # type: ignore[assignment]
    runtime: RuntimeComponents

    def __init__(self, config: ChatBridgeConfig) -> None:
        self.config = config
        self.mcp = mcp  # capture the module-level singleton
        self.runtime = create_runtime_components("chat-bridge-mcp", ".oneiric_cache")
        self.claude = ClaudeDesktopAdapter(self.config, self.runtime)
        self.chatgpt = ChatGPTDesktopAdapter(self.config, self.runtime)

    async def startup(self) -> None:
        await self.runtime.initialize()
        self.config.validate_for_start()
        # Per spec §5.3: attach BOTH peers at startup. If a port is busy,
        # CDPConnection.find_top_level_target raises PeerNotAttachedError;
        # that propagates up and the factory's start handler exits non-zero
        # (see test_attach_fails_when_cdp_port_busy).
        await self.claude.attach()
        await self.chatgpt.attach()
        # Hand the live adapters to the @mcp.tool() bodies (Task 10's
        # decorators register tool callables that look up via _tools).
        _tools.set_clients(claude=self.claude, chatgpt=self.chatgpt)
        # Build the four-signal-shape peer component dicts once at startup.
        # register_http_health_route captures extra_components verbatim, so
        # we snapshot the per-peer health envelope here. Live values would
        # require a custom route handler; v1 ships the startup snapshot
        # and relies on get_peer_health() (the dedicated tool) for live data.
        claude_health = await self.claude.health()
        chatgpt_health = await self.chatgpt.health()
        extra_components = [
            {
                "name": claude_health.name,
                "entities_count": claude_health.entities_count,
                "errors_total": claude_health.errors_total,
                "cycles_total": claude_health.cycles_total,
                "last_updated_timestamp": claude_health.last_updated_timestamp,
                "attached": claude_health.attached,
                "cdp_port": claude_health.cdp_port,
            },
            {
                "name": chatgpt_health.name,
                "entities_count": chatgpt_health.entities_count,
                "errors_total": chatgpt_health.errors_total,
                "cycles_total": chatgpt_health.cycles_total,
                "last_updated_timestamp": chatgpt_health.last_updated_timestamp,
                "attached": chatgpt_health.attached,
                "cdp_port": chatgpt_health.cdp_port,
            },
        ]
        register_http_health_route(
            self.mcp,
            service_name="chat-bridge-mcp",
            version=__version__,
            extra_components=extra_components,
        )
        await self._create_startup_snapshot(
            custom_components={
                "claude": self.claude.status().__dict__,
                "chatgpt": self.chatgpt.status().__dict__,
            }
        )

    async def shutdown(self) -> None:
        await self._create_shutdown_snapshot()
        await self.claude.detach()
        await self.chatgpt.detach()
        await self.runtime.cleanup()

    async def health_check(self) -> Any:
        """Run the per-component health snapshot.

        Returned to ``health_probe_handler`` in the CLI factory; the
        factory wraps it into a ``RuntimeHealthSnapshot``.
        """
        components: list[tuple[str, dict[str, object]]] = []
        for adapter in (self.claude, self.chatgpt):
            try:
                h = await adapter.health()
                components.append((adapter.name, h.__dict__))
            except Exception as e:  # noqa: BLE001 (probe never raises)
                components.append((adapter.name, {"error": str(e)}))
        return components

    def get_app(self) -> Any:
        # `stateless_http=True` makes /mcp accept per-request POST without a
        # session-ID handshake. `json_response=True` returns plain JSON
        # instead of SSE; integration tests (and curl smoke tests in spec
        # §10) need JSON bodies, not `event: message\ndata: {...}\n\n`.
        return self.mcp.http_app(stateless_http=True, json_response=True)


def _build_factory() -> MCPServerCLIFactory:
    """Build the CLI factory for `chat-bridge-mcp start/stop/...`.

    Per the mcp-common CLI factory signature (verified at
    /Users/les/Projects/mcp-common/mcp_common/cli/factory.py:91):
        def create_server_cli(
            cls, server_class, config_class, name,
            _description="MCP Server",
            _use_subcommands=True,
            use_mcp_subcommand=False,
        ) -> MCPServerCLIFactory
    The `_description` kwarg uses the underscore-prefixed sentinel name to
    match the canonical factory pattern; we accept the default.
    """
    return MCPServerCLIFactory.create_server_cli(
        server_class=ChatBridgeServer,
        config_class=ChatBridgeConfig,
        name="chat-bridge-mcp",
    )


# CLI Factory singleton used by __main__.py. Module-import side effects:
# registers tools via _tools, binds the FastMCP app on import.
_factory = _build_factory()
app = _factory.create_app()
