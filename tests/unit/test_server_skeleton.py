from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_bridge_mcp.config import ChatBridgeConfig
from chat_bridge_mcp.peers.base import PeerHealth, PeerStatus
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


# ---------------------------------------------------------------------------
# Server lifecycle tests (in-process). Cover server.py:101-145, 153-156,
# 164-171. The bridge_proc subprocess fixture in tests/integration/
# test_server_lifecycle.py exercises the same code paths but only inside
# a subprocess, so coverage.py in the parent pytest doesn't see them.
# ---------------------------------------------------------------------------


def _make_peer_mock(name: str) -> MagicMock:
    """Build an AsyncMock peer satisfying the DesktopPeerAdapter contract.

    .attach() and .health() and .detach() are async; .status() is sync.
    .name is a class attribute on the real adapters, so the mock needs it too.
    """
    peer = MagicMock()
    peer.name = name
    peer.attach = AsyncMock(return_value=None)
    peer.detach = AsyncMock(return_value=None)
    peer.health = AsyncMock(
        return_value=PeerHealth(
            name=name,
            attached=True,
            cdp_port=9230 if name == "chatgpt" else 9229,
            page_id=None,
            last_call_succeeded=None,
            last_call_error=None,
            total_calls=0,
            errors_total=0,
            cycles_total=0,
            entities_count=1,
            last_updated_timestamp="2026-09-18T00:00:00+00:00",
        )
    )
    peer.status = MagicMock(
        return_value=PeerStatus(
            name=name,
            attached=True,
            last_call_at=None,
            last_reply_char_count=None,
        )
    )
    return peer


def _build_server_with_mocks(
    claude_peer: MagicMock | None = None,
    chatgpt_peer: MagicMock | None = None,
) -> ChatBridgeServer:
    """Construct a ChatBridgeServer with mocked peer adapters.

    Replaces self.claude and self.chatgpt post-construction so the test
    doesn't have to spawn real CDP-attached peers.
    """
    server = ChatBridgeServer(ChatBridgeConfig())
    server.claude = claude_peer or _make_peer_mock("claude")  # type: ignore[assignment]
    server.chatgpt = chatgpt_peer or _make_peer_mock("chatgpt")  # type: ignore[assignment]
    runtime_mock = MagicMock()
    runtime_mock.initialize = AsyncMock(return_value=None)
    runtime_mock.cleanup = AsyncMock(return_value=None)
    server.runtime = runtime_mock  # type: ignore[assignment]
    # _create_startup_snapshot / _create_shutdown_snapshot are inherited from
    # BaseOneiricServerMixin; they may write to .oneiric_cache. Stub them so
    # the test doesn't need a writable runtime cache.
    server._create_startup_snapshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
    server._create_shutdown_snapshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
    return server


@pytest.mark.asyncio
async def test_server_startup_attaches_both_peers_and_registers_health_route() -> None:
    """startup() drives attach + health snapshot + register_http_health_route.

    Covers server.py:101-145 (startup body).
    """
    from chat_bridge_mcp import _tools

    server = _build_server_with_mocks()
    _tools._reset()
    try:
        await server.startup()
        # Both peers were attached; their .attach() awaits must have been hit.
        server.claude.attach.assert_awaited_once()  # type: ignore[attr-defined]
        server.chatgpt.attach.assert_awaited_once()  # type: ignore[attr-defined]
        # The runtime's initialize() ran.
        server.runtime.initialize.assert_awaited_once()  # type: ignore[attr-defined]
        # The _tools registry was populated so @mcp.tool() bodies can dispatch.
        clients = _tools.get_clients()
        assert "claude" in clients
        assert "chatgpt" in clients
        # The startup snapshot was created.
        server._create_startup_snapshot.assert_awaited_once()  # type: ignore[attr-defined]
    finally:
        await server.shutdown()
        _tools._reset()


@pytest.mark.asyncio
async def test_server_shutdown_detaches_both_peers_and_cleans_up_runtime() -> None:
    """shutdown() drives detach + runtime.cleanup() + shutdown snapshot.

    Covers server.py:153-156 (shutdown body).
    """
    server = _build_server_with_mocks()
    await server.startup()
    await server.shutdown()
    server.claude.detach.assert_awaited_once()  # type: ignore[attr-defined]
    server.chatgpt.detach.assert_awaited_once()  # type: ignore[attr-defined]
    server.runtime.cleanup.assert_awaited_once()  # type: ignore[attr-defined]
    server._create_shutdown_snapshot.assert_awaited_once()  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_server_health_check_aggregates_per_peer_health() -> None:
    """health_check() returns [(adapter.name, adapter.health().__dict__), ...]
    on the success path. Covers server.py:164-168.
    """
    server = _build_server_with_mocks()
    components = await server.health_check()
    assert isinstance(components, list)
    assert [name for name, _ in components] == ["claude", "chatgpt"]
    for name, payload in components:
        assert payload["name"] == name
        assert payload["attached"] is True
        # The four-signal wiring discipline keyset is present in the
        # snapshot that the production health envelope ships.
        for required_key in (
            "entities_count",
            "errors_total",
            "cycles_total",
            "last_updated_timestamp",
        ):
            assert required_key in payload


@pytest.mark.asyncio
async def test_server_health_check_surfaces_peer_failure_as_error_dict() -> None:
    """When a peer's .health() raises, health_check() must record the
    failure as a `{"error": <str>}` payload rather than letting the
    exception escape. Covers server.py:170 (the except branch).
    """
    server = _build_server_with_mocks()
    # Make chatgpt's health() raise; claude's still returns a healthy payload.
    server.chatgpt.health = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("boom")
    )
    components = await server.health_check()
    by_name = {name: payload for name, payload in components}
    assert by_name["claude"].get("attached") is True
    assert by_name["chatgpt"] == {"error": "boom"}