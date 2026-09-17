from __future__ import annotations

from chat_bridge_mcp.config import ChatBridgeConfig
from chat_bridge_mcp.server import ChatBridgeServer, mcp


def test_mcp_singleton_exists() -> None:
    """The module-level `mcp` is the FastMCP instance tools bind to."""
    assert mcp is not None
    assert mcp.name == "chat-bridge-mcp"


def test_chat_bridge_server_constructs() -> None:
    """ChatBridgeServer captures the module-level `mcp` singleton and the config."""
    cfg = ChatBridgeConfig()
    server = ChatBridgeServer(cfg)
    assert server.mcp is mcp  # same singleton captured
    assert server.config is cfg


def test_get_app_returns_http_app() -> None:
    """get_app() returns the FastMCP http_app bound to the captured singleton.

    Task 11b added ``stateless_http=True, json_response=True`` so the
    /mcp endpoint accepts raw JSON POSTs (no session-id handshake) and
    returns plain JSON instead of SSE. This is required for the
    integration tests that POST to /mcp via httpx.
    """
    cfg = ChatBridgeConfig()
    server = ChatBridgeServer(cfg)
    app = server.get_app()
    assert app is not None
    # The /mcp route is auto-registered by FastMCP's http_app; the
    # /health route is added during startup(). Verify /mcp is present.
    paths = [r.path for r in app.routes]  # type: ignore[attr-defined]
    assert "/mcp" in paths