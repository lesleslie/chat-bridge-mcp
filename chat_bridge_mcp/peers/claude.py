from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from chat_bridge_mcp.cdp import CDPConnection, CDPSession
from chat_bridge_mcp.exceptions import (
    PeerNotAttachedError,
    SelectorUnmatchedError,
    StreamingTimeoutError,
)
from chat_bridge_mcp.peers.base import DesktopPeerAdapter, PeerReply
from chat_bridge_mcp.selectors import SelectorSet


def _react_set_value_js(value: str) -> str:
    """JS expression that sets the input value through React's native
    setter and dispatches a bubbling 'input' event so React's synthetic
    listener picks up the change (§5.1.c step 3).

    Naive `el.value = ...` assignment bypasses React's controlled-input
    override; using `Object.getOwnPropertyDescriptor(prototype, 'value').set`
    is the load-bearing workaround.
    """
    return (
        "(() => {"
        "  const el = document.querySelector(arguments[0]);"
        "  if (el) {"
        "    const proto = Object.getPrototypeOf(el);"
        "    const desc = Object.getOwnPropertyDescriptor(proto, 'value');"
        f"    desc.set.call(el, {json.dumps(value)});"
        "    el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));"
        "  }"
        "})()"
    )


def _react_clear_value_js() -> str:
    """JS expression that clears the input box via React's native setter."""
    return (
        "(() => {"
        "  const el = document.querySelector(arguments[0]);"
        "  if (el) {"
        "    const proto = Object.getPrototypeOf(el);"
        "    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, '');"
        "    el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));"
        "  }"
        "})()"
    )


def _focus_input_js() -> str:
    """JS expression that focuses the input box before value injection."""
    return (
        "(() => {"
        "  const el = document.querySelector(arguments[0]);"
        "  if (el) el.focus();"
        "})()"
    )


def _extract_last_response_js() -> str:
    """JS expression that returns the innerText of the last response_container node."""
    return (
        "(() => {"
        "  const nodes = document.querySelectorAll(arguments[0]);"
        "  return (nodes.length && Array.from(nodes).pop()?.innerText) || '';"
        "})()"
    )


def _extract_model_label_js() -> str:
    """JS expression that best-effort extracts the model label."""
    return (
        "document.querySelector('[data-testid=\"model-selector\"]')?.textContent ?? null"
    )


class ClaudeDesktopAdapter(DesktopPeerAdapter):
    """Drives Claude Desktop via the Chrome DevTools Protocol on the
    configured `cdp_claude_port` (default 9229)."""

    name = "claude"
    cdp_port = 9229

    def __init__(self, config: Any, runtime: Any) -> None:
        super().__init__(config, runtime)
        self._selectors: SelectorSet | None = None
        self._target: dict[str, Any] | None = None
        self._session: CDPSession | None = None

    async def attach(self) -> None:
        # Local import: selectors loader imports config, avoid cycle.
        from chat_bridge_mcp.selectors import load_selectors

        selectors_by_peer = await asyncio.to_thread(
            load_selectors, self.config.selectors_file
        )
        self._selectors = selectors_by_peer["claude"]
        target = await CDPConnection.find_top_level_target(
            self.config.cdp_host, self.config.cdp_claude_port
        )
        self._target = target
        # Lazy WebSocket open: defer CDPConnection.attach() to first send()
        # so the WS is opened on the same asyncio loop that handles the
        # request. See chatgpt.py for the full rationale.
        self._session = None

        # Self-test via a probe session; close it before returning so the
        # streaming loop opens its own session lazily.
        selectors_to_check: list[tuple[str, str]] = [
            ("input_box", self._selectors.input_box),
            ("send_button", self._selectors.send_button),
            ("response_container", self._selectors.response_container),
        ]
        probe_session = await CDPConnection.attach(target)
        try:
            for sel_name, selector in selectors_to_check:
                count = await probe_session.query_selector_all(selector)
                if count < 1:
                    raise SelectorUnmatchedError(
                        f"Claude Desktop selector '{sel_name}' matched no elements",
                        peer="claude",
                        context={"selector_name": sel_name, "configured": selector},
                    )
        finally:
            await probe_session.close()

        self._page_id = target.get("id")
        # Per base-class contract: set entities_count so status()/health()
        # report attached=True via the four-signal shape.
        self.feed_state.entities_count = 1

    async def detach(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._target = None
        self._page_id = None
        self.feed_state.entities_count = 0

    async def _ensure_session(self) -> CDPSession:
        """Lazy WebSocket open on the caller's event loop.

        Known v1 limitation: under concurrent first-time callers (e.g., two
        ask_claude() calls arriving simultaneously before any WS exists), both
        may observe _session is None and each call CDPConnection.attach — the
        loser's WS is silently overwritten and never closed (WS leak). The
        test fixture supports multiple concurrent WS connections, so the
        concurrent-call spec §5.6 contract pins correctly; the leak is
        cosmetic on subprocess shutdown. TODO: per-call WS lifecycle in v0.2.0
        — open in _send_uncounted, close in finally.
        """
        if self._session is None and self._target is not None:
            try:
                self._session = await CDPConnection.attach(self._target)
            except Exception as exc:
                raise PeerNotAttachedError(
                    f"claude CDP target unreachable: {exc}",
                    peer="claude",
                ) from exc
        if self._session is None:
            raise PeerNotAttachedError("claude peer not attached", peer="claude")
        return self._session

    async def _send_uncounted(self, prompt: str, *, system: str | None = None) -> PeerReply:
        if self._selectors is None:
            raise PeerNotAttachedError("claude peer not attached", peer="claude")
        s = self._selectors
        session = await self._ensure_session()
        started = datetime.now(UTC)

        # 1. Clear the input box (React-friendly setter).
        await session.evaluate(
            f"({_react_clear_value_js()})({json.dumps(s.input_box)})"
        )
        # 2. Focus the input box so the React onChange fires predictably.
        await session.evaluate(
            f"({_focus_input_js()})({json.dumps(s.input_box)})"
        )
        # 3. Set the value (React-friendly setter) and dispatch Enter.
        await session.evaluate(
            f"({_react_set_value_js(prompt)})({json.dumps(s.input_box)})"
        )
        await session.dispatch_key_event("Enter", "Enter")

        # 4. Streaming-done detection.
        #    When stop_generating_indicator is configured: require 3
        #    consecutive absent polls (mirrors the content-hash stability
        #    semantic used when the indicator is None, §5.1.c step 5).
        #    When not configured: poll for content-hash stability across 3
        #    consecutive polls of the response_container innerText.
        timeout = float(self.config.streaming_timeout_seconds)
        interval = float(self.config.polling_interval_seconds)
        deadline = datetime.now(UTC).timestamp() + timeout
        if s.stop_generating_indicator:
            consecutive_absent = 0
            while datetime.now(UTC).timestamp() < deadline:
                count = await session.query_selector_all(s.stop_generating_indicator)
                if count == 0:
                    consecutive_absent += 1
                    if consecutive_absent >= 3:
                        break
                else:
                    consecutive_absent = 0
                await asyncio.sleep(interval)
            else:
                raise StreamingTimeoutError(
                    f"claude response did not complete within {timeout}s",
                    peer="claude",
                    context={"timeout": timeout},
                )
        else:
            last_hash: int | None = None
            stable_count = 0
            while datetime.now(UTC).timestamp() < deadline:
                text_obj = await session.evaluate(
                    f"(document.querySelector({json.dumps(s.response_container)})?.innerText ?? '')"
                )
                text_str = text_obj if isinstance(text_obj, str) else ""
                h = hash(text_str)
                if h == last_hash:
                    stable_count += 1
                    if stable_count >= 3:
                        break
                else:
                    stable_count = 1
                    last_hash = h
                await asyncio.sleep(interval)
            else:
                raise StreamingTimeoutError(
                    f"claude response did not stabilize within {timeout}s",
                    peer="claude",
                    context={"timeout": timeout},
                )

        # 5. Extract last assistant message innerText.
        text_obj = await session.evaluate(
            f"({_extract_last_response_js()})({json.dumps(s.response_container)})"
        )
        text = text_obj if isinstance(text_obj, str) else ""

        # 6. Extract model label (best-effort; None is fine).
        model_used_obj = await session.evaluate(_extract_model_label_js())
        model_used = model_used_obj if isinstance(model_used_obj, str) else None

        finished = datetime.now(UTC)
        return PeerReply(
            text=text,
            model_used=model_used,
            duration_ms=int((finished - started).total_seconds() * 1000),
            started_at=started,
            finished_at=finished,
            peer="claude",
            char_count=len(text),
        )