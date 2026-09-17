from __future__ import annotations

import pytest

from chat_bridge_mcp.exceptions import (
    BridgeError,
    PeerNotAttachedError,
    SelectorMissingError,
    SelectorUnmatchedError,
    StreamingTimeoutError,
    GuardrailFailure,
    CDPProtocolError,
)


@pytest.mark.parametrize(
    "exc_cls",
    [
        PeerNotAttachedError,
        SelectorMissingError,
        SelectorUnmatchedError,
        StreamingTimeoutError,
        GuardrailFailure,
        CDPProtocolError,
    ],
)
def test_subclass_inherits_bridge_error(exc_cls):
    assert issubclass(exc_cls, BridgeError)


def test_peer_and_context_propagate():
    exc = PeerNotAttachedError("cdp port unreachable", peer="chatgpt", context={"port": 9230})
    assert exc.peer == "chatgpt"
    assert exc.context == {"port": 9230}
    assert exc.message == "cdp port unreachable"
    assert "chatgpt" in str(exc)


def test_peer_optional():
    exc = GuardrailFailure("operator template missing begin marker")
    assert exc.peer is None
    assert exc.context == {}


def test_default_message_is_strable():
    exc = StreamingTimeoutError("did not finish in 180s")
    assert str(exc) == "did not finish in 180s"