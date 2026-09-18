from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from chat_bridge_mcp.cdp import CDPConnection, CDPSession
from chat_bridge_mcp.exceptions import CDPProtocolError, PeerNotAttachedError


@pytest.mark.asyncio
async def test_discover_targets_returns_fake_page(fake_cdp):
    """GET /json returns at least one page-typed target."""
    targets = await CDPConnection.discover_targets(
        fake_cdp.host, fake_cdp.port_http
    )
    assert isinstance(targets, list)
    assert any(t.get("type") == "page" for t in targets)


@pytest.mark.asyncio
async def test_evaluate_returns_handler_value(fake_cdp):
    """Runtime.evaluate round-trips a simple expression through the fake handler."""
    targets = await CDPConnection.discover_targets(
        fake_cdp.host, fake_cdp.port_http
    )
    target = next(t for t in targets if t.get("type") == "page")
    session = await CDPConnection.attach(target)
    try:
        result = await session.evaluate("1 + 1")
        assert result == 2
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_websocket_drop_raises_cdp_protocol_error(fake_cdp):
    """A `close()` then `evaluate()` raises CDPProtocolError rather than hanging."""
    targets = await CDPConnection.discover_targets(
        fake_cdp.host, fake_cdp.port_http
    )
    target = targets[0]
    session = await CDPConnection.attach(target)
    await session.close()
    with pytest.raises(CDPProtocolError):
        await session.evaluate("x")


@pytest.mark.asyncio
async def test_out_of_order_response_is_skipped_not_consumed(fake_cdp):
    """An unsolicited response with a non-matching id is skipped, not consumed.

    The fake fixture injects a response with id=99999 before the real
    response for the in-flight request id. The session must skip the
    poison frame and still resolve the real id's response.

    Pins spec §9.3 "message-ordering edge case" — production code must
    not silently consume an out-of-order reply and must not raise for an
    unsolicited event arriving between request and reply.
    """
    injected_ids: list[int] = []

    async def inject_unsolicited(ws, msg):
        injected_ids.append(int(msg["id"]))
        await ws.send(
            json.dumps({"id": 99999, "result": {"poison": True}})
        )

    fake_cdp.before_response_hook = inject_unsolicited

    targets = await CDPConnection.discover_targets(
        fake_cdp.host, fake_cdp.port_http
    )
    target = next(t for t in targets if t.get("type") == "page")
    session = await CDPConnection.attach(target)
    try:
        result = await session.evaluate("1 + 1")
        assert result == 2
        assert len(injected_ids) == 1
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# find_top_level_target filtering (cdp.py:30-36)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_top_level_target_skips_iframes_and_returns_first_page(monkeypatch):
    """discover_targets returns [iframe, nested-page, top-level-page]; the
    function must skip both non-page types AND pages with parentId
    (nested pages inside iframes) and return the top-level page.
    Covers cdp.py:30-35.
    """
    monkeypatch.setattr(
        CDPConnection,
        "discover_targets",
        AsyncMock(
            return_value=[
                {"id": "IFRAME-1", "type": "iframe", "parentId": "OUTER"},
                {"id": "NESTED-PAGE", "type": "page", "parentId": "OUTER"},
                {"id": "PAGE-1", "type": "page"},
            ]
        ),
    )
    target = await CDPConnection.find_top_level_target("x", 9999)
    assert target["id"] == "PAGE-1"


@pytest.mark.asyncio
async def test_find_top_level_target_raises_when_no_top_level_page(monkeypatch):
    """No top-level page -> PeerNotAttachedError with the host:port context.
    Covers cdp.py:36-39 (the raise branch after the for-loop).
    """
    monkeypatch.setattr(
        CDPConnection,
        "discover_targets",
        AsyncMock(
            return_value=[
                {"id": "IFRAME-1", "type": "iframe"},
                {"id": "IFRAME-2", "type": "iframe", "parentId": "X"},
            ]
        ),
    )
    with pytest.raises(PeerNotAttachedError) as excinfo:
        await CDPConnection.find_top_level_target("127.0.0.1", 9229)
    assert excinfo.value.context == {"host": "127.0.0.1", "port": 9229}


# ---------------------------------------------------------------------------
# send() event skip + websocket error translation (cdp.py:96, 109-114)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_skips_event_messages_with_method_field():
    """A message with a `method` field is a CDP event notification (not a
    reply); CDPSession.send must skip it and keep waiting for the matching
    reply. Covers cdp.py:95-96 (the event-skip continue).
    """
    ws = AsyncMock()
    # First message: a CDP event with method=Target.targetCreated (no id).
    # Second message: the matching reply.
    ws.recv = AsyncMock(
        side_effect=[
            json.dumps({"method": "Target.targetCreated", "params": {}}),
            json.dumps({"id": 1, "result": {"ok": True}}),
        ]
    )
    session = CDPSession(ws)
    result = await session.send("Runtime.evaluate")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_send_translates_websocket_failure_to_peer_not_attached():
    """A WebSocket-level exception (e.g. ConnectionClosed) is translated to
    PeerNotAttachedError so the chat surface renders the operator-facing
    'not attached' copy. Covers cdp.py:109-114 (the generic-exception
    re-raise handler).
    """
    ws = AsyncMock()
    ws.send = AsyncMock(side_effect=ConnectionResetError("connection reset"))
    session = CDPSession(ws)
    with pytest.raises(PeerNotAttachedError, match="CDP target disconnected") as excinfo:
        await session.send("Runtime.evaluate")
    assert excinfo.value.context["method"] == "Runtime.evaluate"
    assert excinfo.value.context["ws_error"] == "ConnectionResetError"


# ---------------------------------------------------------------------------
# evaluate() branches (cdp.py:133, 135)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_returns_none_when_result_payload_not_dict():
    """When send() returns a dict whose nested 'result' key is not a dict
    (e.g. None, scalar), evaluate must return None rather than crash on
    the .get("value") call. Covers cdp.py:132-133.
    """
    ws = AsyncMock()
    session = CDPSession(ws)
    # Patch send() so evaluate's `result.get("result")` returns a non-dict.
    session.send = AsyncMock(return_value={"result": None})
    assert await session.evaluate("x") is None


@pytest.mark.asyncio
async def test_evaluate_raises_on_exception_details():
    """When the CDP reply's inner result carries `exceptionDetails`,
    evaluate must raise CDPProtocolError. Covers cdp.py:134-137.
    """
    ws = AsyncMock()
    ws.recv = AsyncMock(
        return_value=json.dumps(
            {
                "id": 1,
                "result": {
                    "result": {  # evaluate reads result.get("result")
                        "exceptionDetails": {
                            "text": "ReferenceError: x is not defined",
                            "lineNumber": 1,
                            "columnNumber": 0,
                        }
                    }
                },
            }
        )
    )
    session = CDPSession(ws)
    with pytest.raises(CDPProtocolError, match="Runtime.evaluate raised"):
        await session.evaluate("x;")


# ---------------------------------------------------------------------------
# dispatch_key_event (cdp.py:147-148)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_key_event_sends_keydown_char_keyup_phases():
    """dispatch_key_event must send Input.dispatchKeyEvent three times
    (keyDown, char, keyUp) so CJK input reaches the page correctly.
    Covers cdp.py:147-148 (the for-loop over event types).
    """
    ws = AsyncMock()
    ws.recv = AsyncMock(
        side_effect=[
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"id": 2, "result": {}}),
            json.dumps({"id": 3, "result": {}}),
        ]
    )
    session = CDPSession(ws)
    await session.dispatch_key_event("Enter", "Enter")
    sent = [json.loads(call.args[0]) for call in ws.send.await_args_list]
    assert [m["params"]["type"] for m in sent] == ["keyDown", "char", "keyUp"]
    assert all(m["method"] == "Input.dispatchKeyEvent" for m in sent)
    assert all(m["params"]["key"] == "Enter" for m in sent)


# ---------------------------------------------------------------------------
# query_selector_all branches (cdp.py:162-170)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_selector_all_returns_zero_when_evaluate_returns_none():
    """If Runtime.evaluate returns None (no payload at all), qsa returns 0.
    Covers cdp.py:165-166.
    """
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value=json.dumps({"id": 1, "result": {}}))
    session = CDPSession(ws)
    assert await session.query_selector_all("anything") == 0


@pytest.mark.asyncio
async def test_query_selector_all_returns_zero_on_non_int_value():
    """If the JS expression returns a non-int (e.g. a string), qsa returns 0
    rather than raising. Covers cdp.py:167-170 (the int-coercion except).
    """
    ws = AsyncMock()
    ws.recv = AsyncMock(
        return_value=json.dumps(
            {"id": 1, "result": {"result": {"value": "not-an-int"}}}
        )
    )
    session = CDPSession(ws)
    assert await session.query_selector_all("anything") == 0


# ---------------------------------------------------------------------------
# close() idempotency (cdp.py:175)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_idempotent():
    """close() sets _closed=True; calling close() twice is a no-op the
    second time. Covers cdp.py:175 (the `if self._closed: return` guard).
    """
    ws = AsyncMock()
    session = CDPSession(ws)
    await session.close()
    assert ws.close.await_count == 1
    # Second close is a no-op.
    await session.close()
    assert ws.close.await_count == 1


@pytest.mark.asyncio
async def test_send_raises_cdp_protocol_error_on_non_json_response():
    """When ws.recv returns a non-JSON frame, CDPSession.send wraps the
    JSONDecodeError as CDPProtocolError with the raw payload quoted.
    Covers cdp.py:88-94 (the except json.JSONDecodeError branch).
    """
    ws = AsyncMock()
    ws.recv = AsyncMock(return_value="not-valid-json-at-all{{{")
    session = CDPSession(ws)
    with pytest.raises(CDPProtocolError, match="CDP returned non-JSON"):
        await session.send("Runtime.evaluate")