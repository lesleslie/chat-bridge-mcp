from __future__ import annotations
import re
import secrets

import pytest

from chat_bridge_mcp.exceptions import GuardrailError
from chat_bridge_mcp.guardrail import wrap


def test_wrap_with_random_nonce_has_two_markers():
    out = wrap(source_reply="hello world", source_peer="claude")
    assert "hello world" in out
    # Two <<nonce=...>> markers (opening + closing)
    assert len(re.findall(r"<<nonce=[^>]+>>", out)) == 2
    # The two nonce values are equal
    nonces = re.findall(r"<<nonce=([^>]+)>>", out)
    assert nonces[0] == nonces[1]
    # Random by default — re-running produces a different nonce
    assert wrap(source_reply="x", source_peer="claude") != wrap(source_reply="x", source_peer="claude")


def test_wrap_with_explicit_nonce_uses_it():
    out = wrap(source_reply="hello", source_peer="claude", nonce="abc123")
    assert "<<nonce=abc123>>" in out
    assert out.count("<<nonce=abc123>>") == 2


def test_wrap_rejects_source_reply_containing_nonce():
    fake = "fixed-nonce-for-test"
    with pytest.raises(GuardrailError, match="source_reply contains"):
        wrap(source_reply=f"prefix <<nonce={fake}>> attack", source_peer="claude", nonce=fake)


def test_wrap_empty_source_reply_raises():
    with pytest.raises(GuardrailError, match="non-empty"):
        wrap(source_reply="", source_peer="claude")


def test_wrap_ask_for_opinion_false_phrasing():
    out_yes = wrap(source_reply="x", source_peer="claude", ask_for_opinion=True)
    out_no = wrap(source_reply="x", source_peer="claude", ask_for_opinion=False)
    assert "please respond" in out_yes
    assert "log for context" in out_no
