from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_bridge_mcp.config import ChatBridgeConfig
from chat_bridge_mcp.exceptions import (
    PeerNotAttachedError,
    SelectorUnmatchedError,
    StreamingTimeoutError,
)
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
      - 3 attach self-tests (input_box, send_button, response_container),
        each count >= 1. The stop_generating_indicator is OPTIONAL per
        spec §5.1.c step 5 — Task 11b removed it from the attach self-test
        so the fallback path is exercised when no indicator matches.
      - 3 send set-up evaluates (clear, focus, set) returning None
      - 3 polls for stop indicator absent (each returns 0)
      - 1 extract response_container last message innerText -> "hello chatgpt"
      - 1 extract model_used -> None
    """
    fake_target = {"id": "PAGE-2", "type": "page", "webSocketDebuggerUrl": "ws://x/y"}
    session = AsyncMock()
    session.evaluate = AsyncMock(side_effect=[
        1, 1, 1,                # 3 attach self-tests (via query_selector_all)
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
    """detach() is safe when no session was opened (attach's probe_session
    is the only `close()` call in this path).
    """
    session, _ = patched_cdp
    peer = ChatGPTDesktopAdapter(config, runtime=MagicMock())
    await peer.attach()
    await peer.detach()
    session.close.assert_awaited_once()
    assert peer.status().attached is False


@pytest.mark.asyncio
async def test_detach_closes_lazy_session_chatgpt(config, patched_cdp):
    """detach() closes a session that was lazy-opened by send() (lines 141-142).

    The previous test only covered the case where no session was opened
    (attach() leaves self._session = None). This test exercises the lazy
    path: send() opens the session, then detach() closes it.
    """
    session, _ = patched_cdp
    peer = ChatGPTDesktopAdapter(config, runtime=MagicMock())
    await peer.attach()
    await peer.send("hello")  # lazy-opens session via _ensure_session
    assert peer._session is not None
    await peer.detach()
    # Two `close()` calls expected: one from attach()'s probe_session in the
    # finally block, one from detach() closing the lazy-opened session.
    assert session.close.await_count == 2
    assert peer._session is None
    assert peer.status().attached is False


@pytest.mark.asyncio
async def test_content_hash_success_path_chatgpt(tmp_path, monkeypatch):
    """Content-hash polling with stable text for 3 polls -> break out -> extract.
    Covers chatgpt.py:228-230 (the `if stable_count >= 3: break` success branch
    of the content-hash streaming-done detector).
    """
    monkeypatch.setenv("CHAT_BRIDGE_MCP_SELECTORS_FILE", str(tmp_path / "x.yaml"))
    monkeypatch.setenv("CHAT_BRIDGE_MCP_STREAMING_TIMEOUT_SECONDS", "2.0")
    monkeypatch.setenv("CHAT_BRIDGE_MCP_POLLING_INTERVAL_SECONDS", "0.01")
    # chatgpt block intentionally omits stop_generating_indicator so the
    # content-hash path runs.
    (tmp_path / "x.yaml").write_text(
        "darwin:\n"
        "  claude:\n"
        "    input_box: 'ib'\n    send_button: 'sb'\n"
        "    response_container: 'rc'\n    stop_generating_indicator: 'sg'\n"
        "  chatgpt:\n"
        "    input_box: 'ib2'\n    send_button: 'sb2'\n"
        "    response_container: 'rc2'\n"
    )
    config = ChatBridgeConfig()

    fake_target = {"id": "PAGE-2", "type": "page", "webSocketDebuggerUrl": "ws://x/y"}
    session = AsyncMock()

    async def eval_dispatch(expr: str) -> object:
        if expr.startswith("qsa::"):
            return 1  # attach self-tests pass
        # response_container innerText polling: return the SAME text 3 times
        # so the content-hash stability check trips and the loop breaks.
        if "innerText" in expr:
            return "stable-response-text"
        if "model-selector" in expr:
            return "fake-model"
        return None

    session.evaluate = AsyncMock(side_effect=eval_dispatch)

    async def qsa(selector: str) -> int:
        v = await session.evaluate(f"qsa::{selector}")
        return int(v) if v is not None else 0

    session.query_selector_all = AsyncMock(side_effect=qsa)
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

    peer = ChatGPTDesktopAdapter(config, runtime=MagicMock())
    await peer.attach()
    assert peer._selectors is not None
    assert peer._selectors.stop_generating_indicator is None
    reply = await peer.send("hello")
    # The polling loop should have broken out (not raised) and the response
    # should carry the stable text we polled for.
    assert reply.text == "stable-response-text"
    assert reply.peer == "chatgpt"


# ---------------------------------------------------------------------------
# Streaming-timeout tests (T27a-d). Cover chatgpt.py:213-217 and 235-240.
# ---------------------------------------------------------------------------


@pytest.fixture
def short_timeout_config(tmp_path, monkeypatch):
    """Config with 0.5s streaming timeout + 0.05s polling interval for fast timeout tests."""
    monkeypatch.setenv("CHAT_BRIDGE_MCP_SELECTORS_FILE", str(tmp_path / "x.yaml"))
    monkeypatch.setenv("CHAT_BRIDGE_MCP_STREAMING_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("CHAT_BRIDGE_MCP_POLLING_INTERVAL_SECONDS", "0.05")
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


@pytest.mark.asyncio
async def test_streaming_timeout_stop_indicator_chatgpt(
    short_timeout_config, monkeypatch
):
    """Stop indicator never goes absent 3 times across the deadline ->
    StreamingTimeoutError. Covers chatgpt.py:213-217 (raise
    StreamingTimeoutError in stop_generating_indicator polling loop's else
    branch).
    """
    fake_target = {"id": "PAGE-2", "type": "page", "webSocketDebuggerUrl": "ws://x/y"}
    session = AsyncMock()

    async def eval_dispatch(expr: str) -> object:
        # 3 attach self-tests (qsa::ib2/sb2/rc2) -> 1; setup evaluates -> None;
        # stop indicator polls (qsa::sg2) -> 5 (never 0, so the
        # consecutive_absent counter never reaches 3 -> loop exits via
        # deadline -> raise StreamingTimeoutError).
        if expr.startswith("qsa::"):
            return 5 if "sg" in expr[5:] else 1
        return None

    session.evaluate = AsyncMock(side_effect=eval_dispatch)

    async def qsa(selector: str) -> int:
        v = await session.evaluate(f"qsa::{selector}")
        return int(v) if v is not None else 0

    session.query_selector_all = AsyncMock(side_effect=qsa)
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

    peer = ChatGPTDesktopAdapter(short_timeout_config, runtime=MagicMock())
    await peer.attach()
    with pytest.raises(StreamingTimeoutError, match="did not complete within"):
        await peer.send("hello")
    # StreamingTimeoutError context must carry the timeout per spec §10a.3.
    with pytest.raises(StreamingTimeoutError) as excinfo:
        await peer.send("hello")
    assert excinfo.value.context.get("timeout") == 0.5


@pytest.mark.asyncio
async def test_streaming_timeout_content_hash_chatgpt(tmp_path, monkeypatch):
    """stop_generating_indicator=None (content-hash fallback path); response
    text keeps changing each poll so the 3-stable hash check never trips
    -> StreamingTimeoutError. Covers chatgpt.py:235-240.
    """
    monkeypatch.setenv("CHAT_BRIDGE_MCP_SELECTORS_FILE", str(tmp_path / "x.yaml"))
    monkeypatch.setenv("CHAT_BRIDGE_MCP_STREAMING_TIMEOUT_SECONDS", "0.5")
    monkeypatch.setenv("CHAT_BRIDGE_MCP_POLLING_INTERVAL_SECONDS", "0.05")
    # chatgpt block intentionally omits stop_generating_indicator so the
    # SelectorSet field is None -> polling loop takes the content-hash branch.
    (tmp_path / "x.yaml").write_text(
        "darwin:\n"
        "  claude:\n"
        "    input_box: 'ib'\n    send_button: 'sb'\n"
        "    response_container: 'rc'\n    stop_generating_indicator: 'sg'\n"
        "  chatgpt:\n"
        "    input_box: 'ib2'\n    send_button: 'sb2'\n"
        "    response_container: 'rc2'\n"
    )
    config = ChatBridgeConfig()

    fake_target = {"id": "PAGE-2", "type": "page", "webSocketDebuggerUrl": "ws://x/y"}
    session = AsyncMock()
    poll = {"n": 0}

    async def eval_dispatch(expr: str) -> object:
        if expr.startswith("qsa::"):
            return 1  # all 3 attach self-tests pass
        # Direct evaluates: clear/focus/set return None; the innerText
        # polling call returns a different string each time so hash() never
        # matches and stable_count never reaches 3.
        if "innerText" in expr:
            poll["n"] += 1
            return f"changing-text-{poll['n']}"
        return None

    session.evaluate = AsyncMock(side_effect=eval_dispatch)

    async def qsa(selector: str) -> int:
        v = await session.evaluate(f"qsa::{selector}")
        return int(v) if v is not None else 0

    session.query_selector_all = AsyncMock(side_effect=qsa)
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

    peer = ChatGPTDesktopAdapter(config, runtime=MagicMock())
    await peer.attach()
    # Sanity: confirms we exercised the content-hash path.
    assert peer._selectors is not None
    assert peer._selectors.stop_generating_indicator is None
    with pytest.raises(StreamingTimeoutError, match="did not stabilize within"):
        await peer.send("hello")
    assert poll["n"] >= 2, (
        f"expected at least 2 polling calls before deadline, got {poll['n']}"
    )


@pytest.mark.asyncio
async def test_send_raises_peer_not_attached_when_selectors_unset(
    short_timeout_config,
):
    """send() before attach() -> _selectors is None -> PeerNotAttachedError.
    Covers chatgpt.py:173.
    """
    peer = ChatGPTDesktopAdapter(short_timeout_config, runtime=MagicMock())
    # Never call attach().
    with pytest.raises(PeerNotAttachedError, match="peer not attached"):
        await peer.send("hello")


@pytest.mark.asyncio
async def test_ensure_session_raises_when_attach_fails_chatgpt(
    short_timeout_config, monkeypatch
):
    """When CDPConnection.attach() raises inside _ensure_session(), the peer
    must surface PeerNotAttachedError ("chatgpt CDP target unreachable"),
    not the underlying websocket error. Covers chatgpt.py:162-163.
    """
    fake_target = {"id": "PAGE-2", "type": "page", "webSocketDebuggerUrl": "ws://x/y"}

    # Self-test session returned for the attach() call; the streaming loop's
    # lazy attach() call must fail to exercise the catch block.
    self_test_session = AsyncMock()
    self_test_session.evaluate = AsyncMock(side_effect=[1, 1, 1])

    async def qsa(selector: str) -> int:
        v = await self_test_session.evaluate(f"qsa::{selector}")
        return int(v) if v is not None else 0

    self_test_session.query_selector_all = AsyncMock(side_effect=qsa)
    self_test_session.close = AsyncMock()

    attach_calls = {"n": 0}

    async def fake_attach(target: object) -> object:
        attach_calls["n"] += 1
        if attach_calls["n"] == 1:
            # First call: attach() self-test session succeeds.
            return self_test_session
        # Streaming-loop's lazy attach fails — exercise the
        # "CDP target unreachable" branch.
        raise ConnectionRefusedError("ws unreachable")

    monkeypatch.setattr(
        "chat_bridge_mcp.peers.chatgpt.CDPConnection.find_top_level_target",
        AsyncMock(return_value=fake_target),
    )
    monkeypatch.setattr(
        "chat_bridge_mcp.peers.chatgpt.CDPConnection.attach",
        AsyncMock(side_effect=fake_attach),
    )

    peer = ChatGPTDesktopAdapter(short_timeout_config, runtime=MagicMock())
    await peer.attach()
    with pytest.raises(PeerNotAttachedError, match="CDP target unreachable"):
        await peer.send("hello")


@pytest.mark.asyncio
async def test_ensure_session_raises_when_target_missing_chatgpt(
    short_timeout_config,
):
    """When _target is None (e.g. detach was called), _ensure_session must
    raise PeerNotAttachedError "peer not attached" without trying to
    re-attach. Covers chatgpt.py:168.
    """
    peer = ChatGPTDesktopAdapter(short_timeout_config, runtime=MagicMock())
    peer._target = None
    peer._session = None
    peer.feed_state.entities_count = 1  # don't lie about attached state
    with pytest.raises(PeerNotAttachedError, match="peer not attached"):
        await peer._ensure_session()