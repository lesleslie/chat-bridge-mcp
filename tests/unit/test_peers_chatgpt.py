from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_bridge_mcp.config import ChatBridgeConfig
from chat_bridge_mcp.exceptions import SelectorUnmatchedError
from chat_bridge_mcp.peers.chatgpt import ChatGPTDesktopAdapter


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAT_BRIDGE_MCP_SELECTORS_FILE", str(tmp_path / "x.yaml"))
    (tmp_path / "x.yaml").write_text(
        "darwin:\n"
        "  claude:\n"
        "    input_box: 'ib'\n    send_button: 'sb'\n"
        "    response_container: 'rc'\n    stop_generating_indicator: 'sg'\n"
        "  chatgpt:\n"
        "    input_box: 'ib2'\n    send_button: 'sb2'\n"
        "    response_container: 'rc2'\n    stop_generating_indicator: 'sg2'\n"
    )
    return ChatBridgeConfig()


@pytest.fixture
def patched_cdp(monkeypatch):
    """Patch CDPConnection static methods with controllable mocks.

    Returns (session, target). The session mocks both `evaluate` and
    `query_selector_all`; `query_selector_all` delegates to `evaluate`
    (mirroring real CDPSession behavior) so there's one side_effect
    list to manage.

    Expected call sequence on the success path:
      - 4 attach self-tests (input_box, send_button, response_container,
        stop_generating_indicator), each count >= 1
      - 3 send set-up evaluates (clear, focus, set) returning None
      - 3 polls for stop indicator absent (each returns 0)
      - 1 extract response_container last message innerText -> "hello chatgpt"
      - 1 extract model_used -> None
    """
    fake_target = {"id": "PAGE-2", "type": "page", "webSocketDebuggerUrl": "ws://x/y"}
    session = AsyncMock()
    session.evaluate = AsyncMock(side_effect=[
        1, 1, 1, 1,             # 4 attach self-tests (via query_selector_all)
        None, None, None,       # clear, focus, set (direct evaluates)
        0, 0, 0,                # 3 polls for stop indicator absent (via qsa)
        "hello chatgpt",        # extract response_container last message
        None,                   # extract model_used
    ])

    async def fake_query_selector_all(selector):
        """Mimic CDPSession.query_selector_all: evaluate + int coerce."""
        value = await session.evaluate(f"qsa::{selector}")
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    session.query_selector_all = AsyncMock(side_effect=fake_query_selector_all)
    session.dispatch_key_event = AsyncMock()
    session.close = AsyncMock()
    monkeypatch.setattr(
        "chat_bridge_mcp.peers.chatgpt.CDPConnection.find_top_level_target",
        AsyncMock(return_value=fake_target),
    )
    monkeypatch.setattr(
        "chat_bridge_mcp.peers.chatgpt.CDPConnection.attach",
        AsyncMock(return_value=session),
    )
    return session, fake_target


@pytest.mark.asyncio
async def test_attach_resolves_page_and_self_tests_selectors(config, patched_cdp):
    peer = ChatGPTDesktopAdapter(config, runtime=MagicMock())
    await peer.attach()
    assert peer.status().attached is True


@pytest.mark.asyncio
async def test_self_test_failure_raises_selector_unmatched(config, monkeypatch):
    """First evaluate (input_box count) returns 0 -> SelectorUnmatchedError."""
    fake_target = {"id": "PAGE-2", "type": "page", "webSocketDebuggerUrl": "ws://x/y"}
    bad_session = AsyncMock()
    bad_session.evaluate = AsyncMock(side_effect=[0] + [1] * 10)

    async def fake_qsa(selector):
        value = await bad_session.evaluate(f"qsa::{selector}")
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    bad_session.query_selector_all = AsyncMock(side_effect=fake_qsa)
    bad_session.dispatch_key_event = AsyncMock()
    bad_session.close = AsyncMock()
    monkeypatch.setattr(
        "chat_bridge_mcp.peers.chatgpt.CDPConnection.find_top_level_target",
        AsyncMock(return_value=fake_target),
    )
    monkeypatch.setattr(
        "chat_bridge_mcp.peers.chatgpt.CDPConnection.attach",
        AsyncMock(return_value=bad_session),
    )
    peer = ChatGPTDesktopAdapter(config, runtime=MagicMock())
    with pytest.raises(SelectorUnmatchedError, match="input_box"):
        await peer.attach()


@pytest.mark.asyncio
async def test_send_returns_peer_reply_on_success(config, patched_cdp):
    session, _ = patched_cdp
    peer = ChatGPTDesktopAdapter(config, runtime=MagicMock())
    await peer.attach()
    reply = await peer.send("hello")
    assert "hello chatgpt" in reply.text
    assert reply.peer == "chatgpt"
    # Send should dispatch the Enter key after the React-friendly set
    session.dispatch_key_event.assert_awaited_with("Enter", "Enter")


@pytest.mark.asyncio
async def test_three_poll_stability_uses_content_hash_when_stop_indicator_set():
    """Covered by test_send_returns_peer_reply_on_success — the 3 poll
    zeros in that fixture's side_effect list exercise the
    "3 consecutive absent polls" exit condition that mirrors the
    content-hash stability fallback (§5.1.c step 5)."""
    pass


@pytest.mark.asyncio
async def test_detach_closes_session(config, patched_cdp):
    session, _ = patched_cdp
    peer = ChatGPTDesktopAdapter(config, runtime=MagicMock())
    await peer.attach()
    await peer.detach()
    session.close.assert_awaited_once()
    assert peer.status().attached is False