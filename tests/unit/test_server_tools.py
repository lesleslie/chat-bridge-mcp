"""Unit tests pinning the chat-surface strings returned to operators.

Per spec §10a.3: the chat surface is the operator-visible copy that
Claude Desktop / ChatGPT Desktop receives when a tool call fails. These
strings are v1.0.0 contract — drift between the spec and the impl must
fail this test loudly.

Two views are pinned:
  1. ``server._tool_error_string(exc)`` — the canonical mapper. Fast, no
     subprocess, exercises the full exception → string conversion.
  2. ``_tools._render_error(exc, default_peer=...)`` — the public path
     used by the @mcp.tool() bodies in ``_tools.py``. Confirms the
     PeerNotAttachedError-without-peer fallback is wired.

The placeholder text in the plan (e.g. ``{os_and_peer_missing="macos:claude"}``)
is replaced with the actual implementation's substitution: the current
strings do not include an OS key — the platform-key fix is a no-op here
because the SelectorMissingError message references ``settings/selectors.yaml``
without naming the OS. If the implementation is later updated to include
``{os}``, the parametrized cases will catch the drift.
"""
from __future__ import annotations

import json

import pytest

from chat_bridge_mcp import _tools
from chat_bridge_mcp.exceptions import (
    BridgeError,
    CDPProtocolError,
    GuardrailFailure,
    PeerNotAttachedError,
    SelectorMissingError,
    SelectorUnmatchedError,
    StreamingTimeoutError,
)


# Pinned chat-surface strings per spec §10a.3 (v1.0.0 contract).
# Mirrors tests/integration/test_server_lifecycle.py::EXPECTED_CHAT_STRINGS;
# re-pinned here so a unit-test run catches drift without booting a subprocess.
EXPECTED_MESSAGES: dict[type[BridgeError], str] = {
    PeerNotAttachedError: "{peer} peer is not attached. Run `chat-bridge-mcp restart`.",
    SelectorMissingError: "{peer} selectors missing. See settings/selectors.yaml.",
    SelectorUnmatchedError: (
        "{peer} selector did not match. "
        "Update settings/selectors.yaml and `chat-bridge-mcp restart`."
    ),
    StreamingTimeoutError: "{peer} response did not complete within {timeout}s.",
    GuardrailFailure: "Internal: prompt rejected by guardrail. Report as a bug.",
    CDPProtocolError: "{peer} CDP target returned an error. Run `chat-bridge-mcp restart`.",
}


# Per-exception kwargs to inject into the exception constructor. StreamingTimeoutError
# reads `timeout` from exc.context (set by the adapter on raise). SelectorMissingError
# carries the peer name in the same constructor kwarg as every other error.
def _kwargs_for(exc_cls: type[BridgeError]) -> dict[str, object]:
    """Build constructor kwargs for the BridgeError subclass.

    StreamingTimeoutError carries ``timeout`` inside ``exc.context`` (set by
    the adapter at raise time). The pinned template references timeout at the
    top level for .format(); callers pass the timeout value via the second
    return value of ``_context_kwargs`` when constructing format kwargs.
    """
    kwargs: dict[str, object] = {"peer": "chatgpt"}
    if exc_cls is StreamingTimeoutError:
        kwargs["context"] = {"timeout": 180}
    return kwargs


def _format_kwargs(exc_cls: type[BridgeError]) -> dict[str, object]:
    """Build kwargs for ``template.format(**kwargs)``.

    StreamingTimeoutError's template has ``{timeout}`` at the top level; the
    constructor stores it inside ``context``. Lift it out so format() finds it.
    """
    kwargs: dict[str, object] = {"peer": "chatgpt"}
    if exc_cls is StreamingTimeoutError:
        kwargs["timeout"] = 180
    return kwargs


@pytest.mark.parametrize(
    ("exc_cls", "template"),
    list(EXPECTED_MESSAGES.items()),
    ids=lambda v: v.__name__ if isinstance(v, type) else str(v),
)
def test_chat_surface_string_for_exception(
    exc_cls: type[BridgeError], template: str
) -> None:
    """The pinned chat-surface string for each BridgeError subclass equals
    what the operator sees in Claude/ChatGPT Desktop's chat."""
    from chat_bridge_mcp.server import _tool_error_string

    exc = exc_cls("test", **_kwargs_for(exc_cls))
    expected = template.format(**_format_kwargs(exc_cls))
    actual = _tool_error_string(exc)
    assert actual == expected


@pytest.mark.parametrize(
    ("exc_cls", "template"),
    list(EXPECTED_MESSAGES.items()),
    ids=lambda v: v.__name__ if isinstance(v, type) else str(v),
)
def test_render_error_public_path_matches_pinned_strings(
    exc_cls: type[BridgeError], template: str
) -> None:
    """The @mcp.tool() bodies in _tools.py route errors through
    ``_render_error``, which delegates to ``_tool_error_string``. Confirm
    the public path returns the same pinned string."""
    exc = exc_cls("test", **_kwargs_for(exc_cls))
    expected = template.format(**_format_kwargs(exc_cls))
    assert _tools._render_error(exc) == expected


def test_render_error_injects_default_peer_when_missing() -> None:
    """A PeerNotAttachedError raised without `peer=` (e.g. by a lower-level
    wrapper that does not know the peer name) must fall back to the
    ``default_peer`` arg so the operator sees an actionable message."""
    exc = PeerNotAttachedError("ws disconnect")
    rendered = _tools._render_error(exc, default_peer="claude")
    assert rendered == "claude peer is not attached. Run `chat-bridge-mcp restart`."


def test_render_error_falls_back_to_internal_for_non_bridge_error() -> None:
    """Non-BridgeError exceptions must NOT leak through with a peer-specific
    message; they fall back to the generic internal-error string."""
    rendered = _tools._render_error(ValueError("boom"))
    assert rendered == "internal error; see logs"


# ---------------------------------------------------------------------------
# list_peers tool pinning (T19)
# ---------------------------------------------------------------------------


class _FakePeerForListPeers:
    """Minimal peer stub that satisfies DesktopPeerAdapter's `.health()` contract.

    `list_peers` reads only the `name` attribute and awaits `.health()`,
    which must return something with the same attribute shape as the real
    ``PeerHealth`` dataclass (so the implementation's ``health.name`` /
    ``health.cycles_total`` / ... accesses work).
    """

    def __init__(self, name: str, attached: bool = True) -> None:
        self.name = name
        self._attached = attached

    async def health(self) -> "PeerHealth":  # noqa: F821
        from chat_bridge_mcp.peers.base import PeerHealth

        return PeerHealth(
            name=self.name,
            attached=self._attached,
            cdp_port=19229,
            page_id=None,
            last_call_succeeded=True,
            last_call_error=None,
            total_calls=0,
            errors_total=0,
            cycles_total=0,
            entities_count=1 if self._attached else 0,
            last_updated_timestamp="2026-09-17T00:00:00+00:00",
        )


@pytest.mark.asyncio
async def test_list_peers_returns_array_of_records_with_six_fields() -> None:
    """`list_peers` is the operator-facing roster: it returns a JSON array,
    one record per bound peer, with the seven operator-visible fields pinned
    in T19's spec.
    """
    _tools._reset()
    _tools.set_clients(
        chatgpt=_FakePeerForListPeers("chatgpt"),  # type: ignore[arg-type]
        claude=_FakePeerForListPeers("claude", attached=False),  # type: ignore[arg-type]
    )
    try:
        # Invoke the registered FastMCP tool by name. This exercises the same
        # decorator body the MCP transport would call.
        from chat_bridge_mcp.server import mcp

        tool = await mcp.get_tool("list_peers")
        text = await tool.fn()  # type: ignore[misc]
        records = json.loads(text)
        assert isinstance(records, list)
        assert {r["name"] for r in records} == {"chatgpt", "claude"}
        for record in records:
            assert set(record.keys()) == {
                "name",
                "attached",
                "cycles_total",
                "errors_total",
                "last_updated_timestamp",
                "last_call_succeeded",
                "entities_count",
            }
        chatgpt = next(r for r in records if r["name"] == "chatgpt")
        claude = next(r for r in records if r["name"] == "claude")
        assert chatgpt["attached"] is True
        assert chatgpt["entities_count"] == 1
        assert claude["attached"] is False
        assert claude["entities_count"] == 0
    finally:
        _tools._reset()


@pytest.mark.asyncio
async def test_list_peers_handles_empty_registry() -> None:
    """An empty registry returns an empty JSON array (not an error)."""
    _tools._reset()
    try:
        from chat_bridge_mcp.server import mcp

        tool = await mcp.get_tool("list_peers")
        text = await tool.fn()  # type: ignore[misc]
        assert json.loads(text) == []
    finally:
        _tools._reset()


# ---------------------------------------------------------------------------
# ask_claude tool pinning (T16)
# ---------------------------------------------------------------------------


def test_ask_claude_tool_is_registered() -> None:
    """The ask_claude tool must be registered alongside ask_chatgpt and
    get_peer_health (T16: add ask_claude MCP tool). Pinned so future
    regressions that drop the tool from `register_tools()` surface as a
    unit-test failure rather than a downstream integration gap.
    """
    import asyncio

    from chat_bridge_mcp.server import mcp

    tool_names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "ask_claude" in tool_names, (
        f"ask_claude not registered; tools present: {sorted(tool_names)}"
    )
    assert "ask_chatgpt" in tool_names
    assert "get_peer_health" in tool_names


def test_ask_claude_returns_claude_chat_surface_when_not_attached() -> None:
    """When the claude peer has not been bound, ask_claude must return
    the same chat-surface string the canonical PeerNotAttachedError
    mapper emits for the claude peer — pinning the v1.0.0 operator-visible
    copy per spec §10a.3.
    """
    import asyncio

    from chat_bridge_mcp.server import mcp

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert "ask_claude" in tools, (
        "ask_claude not registered; chat-surface string cannot be pinned"
    )
    ask_claude_fn = tools["ask_claude"].fn
    # Clear the clients registry so get_client("claude") raises KeyError,
    # which routes through the same chat-surface path that ask_chatgpt
    # exercises in test_render_error_injects_default_peer_when_missing.
    _tools._reset()
    try:
        result = asyncio.run(ask_claude_fn("hello"))
    finally:
        _tools._reset()
    assert result == "claude peer is not attached. Run `chat-bridge-mcp restart`."


# ---------------------------------------------------------------------------
# forward_chatgpt tool pinning (T17)
# ---------------------------------------------------------------------------


class _FakeChatGPTForForward:
    """Minimal chatgpt stub satisfying DesktopPeerAdapter.send() contract.

    Records the prompt passed to ``send`` so callers can assert on what
    reached the chatgpt adapter.
    """

    def __init__(self, reply_text: str = "fake-reply-marker") -> None:
        self._reply_text = reply_text
        self.sent: list[str] = []

    @property
    def name(self) -> str:
        return "chatgpt"

    async def send(self, prompt: str, **_kwargs: object) -> object:
        from datetime import UTC, datetime

        from chat_bridge_mcp.peers.base import PeerReply

        self.sent.append(prompt)
        now = datetime.now(UTC)
        return PeerReply(
            text=self._reply_text,
            model_used="fake-model",
            duration_ms=1,
            started_at=now,
            finished_at=now,
            peer="chatgpt",
            char_count=len(self._reply_text),
        )


def test_forward_chatgpt_tool_is_registered() -> None:
    """forward_chatgpt must be registered (T17 acceptance criterion)."""
    import asyncio

    from chat_bridge_mcp.server import mcp

    tool_names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "forward_chatgpt" in tool_names, (
        f"forward_chatgpt not registered; tools present: {sorted(tool_names)}"
    )


@pytest.mark.asyncio
async def test_forward_chatgpt_returns_guardrail_chat_surface_for_empty_source_reply() -> None:
    """Empty source_reply -> guardrail.wrap raises GuardrailFailure -> chat surface."""
    from chat_bridge_mcp.server import mcp

    tool = await mcp.get_tool("forward_chatgpt")
    fake = _FakeChatGPTForForward()
    _tools.set_clients(chatgpt=fake)  # type: ignore[arg-type]
    try:
        result = await tool.fn(  # type: ignore[misc]
            source_peer="claude", source_reply=""
        )
    finally:
        _tools._reset()
    assert result == "Internal: prompt rejected by guardrail. Report as a bug."
    assert fake.sent == [], (
        f"forward_chatgpt injected an empty source_reply into chatgpt; sent={fake.sent!r}"
    )


@pytest.mark.asyncio
async def test_forward_chatgpt_returns_chatgpt_not_attached_chat_surface() -> None:
    """No chatgpt client bound -> PeerNotAttachedError chat surface."""
    from chat_bridge_mcp.server import mcp

    tool = await mcp.get_tool("forward_chatgpt")
    _tools._reset()
    try:
        result = await tool.fn(  # type: ignore[misc]
            source_peer="claude", source_reply="a real reply"
        )
    finally:
        _tools._reset()
    assert result == "chatgpt peer is not attached. Run `chat-bridge-mcp restart`."


@pytest.mark.asyncio
async def test_forward_chatgpt_wraps_source_reply_in_nonce_frame() -> None:
    """Happy path: forward_chatgpt wraps via guardrail, sends wrapped text."""
    import re

    from chat_bridge_mcp.server import mcp

    tool = await mcp.get_tool("forward_chatgpt")
    fake = _FakeChatGPTForForward()
    _tools.set_clients(chatgpt=fake)  # type: ignore[arg-type]
    try:
        result = await tool.fn(  # type: ignore[misc]
            source_peer="claude",
            source_reply="the quick brown fox",
            ask_for_opinion=False,
        )
    finally:
        _tools._reset()
    assert result == "fake-reply-marker"
    assert len(fake.sent) == 1
    wrapped = fake.sent[0]
    nonces = re.findall(r"<<nonce=([^>]+)>>", wrapped)
    assert len(nonces) == 2
    assert nonces[0] == nonces[1]
    assert "the quick brown fox" in wrapped
    assert "log for context" in wrapped
    assert "claude" in wrapped
