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
