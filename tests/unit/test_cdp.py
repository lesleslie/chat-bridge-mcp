from __future__ import annotations

import json

import pytest

from chat_bridge_mcp.cdp import CDPConnection
from chat_bridge_mcp.exceptions import CDPProtocolError


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