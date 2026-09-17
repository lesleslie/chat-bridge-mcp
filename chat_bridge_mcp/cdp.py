from __future__ import annotations

import json
from typing import Any

import httpx
import websockets

from chat_bridge_mcp.exceptions import CDPProtocolError, PeerNotAttachedError


class CDPConnection:
    """One-time setup helpers: discover targets, find the right page, attach."""

    @staticmethod
    async def discover_targets(host: str, port: int) -> list[dict[str, Any]]:
        """GET http://{host}:{port}/json; return list of debug target dicts."""
        url = f"http://{host}:{port}/json"
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def find_top_level_target(host: str, port: int) -> dict[str, Any]:
        """Return the first target with type=='page' and no parentId.

        Filters out iframes inside stray Electron dev windows.
        """
        for target in await CDPConnection.discover_targets(host, port):
            if target.get("type") != "page":
                continue
            if target.get("parentId"):
                continue
            return target
        raise PeerNotAttachedError(
            f"no top-level page target at {host}:{port}",
            context={"host": host, "port": port},
        )

    @staticmethod
    async def attach(target: dict[str, Any]) -> CDPSession:
        """Open a WebSocket connection to the target's debugger URL."""
        ws_url = target["webSocketDebuggerUrl"]
        ws = await websockets.connect(ws_url, max_size=4 * 1024 * 1024)
        return CDPSession(ws)


class CDPSession:
    """Bound WebSocket session. Sends JSON-RPC and returns the matching response.

    Message ordering: each `send()` call holds a unique monotonically
    increasing `id`. The receive loop skips events (messages with no
    `id` field or with a `method` field) and skips replies whose id
    does not match the in-flight request. Only the matching id
    completes the `send()` call.
    """

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._next_id = 0
        self._closed = False

    async def send(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send JSON-RPC and await the matching response, skipping events.

        Raises:
            CDPProtocolError: malformed JSON, CDP-level error response, or
                send-on-closed-session.
            PeerNotAttachedError: the underlying WebSocket disconnected
                mid-call (the bridge should treat this as fatal-attachment
                loss and surface the chat-surface "not attached" copy to
                the user).
        """
        if self._closed:
            raise CDPProtocolError("send on closed CDPSession")
        self._next_id += 1
        msg_id = self._next_id
        try:
            await self._ws.send(
                json.dumps({"id": msg_id, "method": method, "params": params or {}})
            )
            while True:
                raw = await self._ws.recv()
                try:
                    response = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise CDPProtocolError(
                        f"CDP returned non-JSON: {raw!r}"
                    ) from exc
                # Skip events: messages with a `method` field are notifications
                # from the target; messages without an `id` are not replies.
                if "method" in response or "id" not in response:
                    continue
                # Skip replies for other in-flight requests (out-of-order).
                if response["id"] != msg_id:
                    continue
                if "error" in response:
                    raise CDPProtocolError(
                        f"CDP {method} returned error: {response['error']}"
                    )
                return response.get("result", {})
        except (PeerNotAttachedError, CDPProtocolError, json.JSONDecodeError):
            # Domain-level errors raised above propagate as-is so callers
            # can branch on the specific exception type.
            raise
        except Exception as exc:
            # Any WebSocket-level failure (ConnectionClosed, ConnectionReset,
            # InvalidState, etc.) means the CDP target is no longer reachable.
            # Translate to PeerNotAttachedError so the chat surface can
            # render the operator-facing "not attached" copy.
            raise PeerNotAttachedError(
                f"CDP target disconnected during {method}: {exc}",
                context={"method": method, "ws_error": type(exc).__name__},
            ) from exc

    async def evaluate(
        self, expression: str, *, await_promise: bool = False
    ) -> Any:
        """Run `expression` in the page's main frame and return the value."""
        result = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        )
        inner = result.get("result")
        if not isinstance(inner, dict):
            return None
        if "exceptionDetails" in inner:
            raise CDPProtocolError(
                f"Runtime.evaluate raised: {inner['exceptionDetails']}"
            )
        return inner.get("value")

    async def dispatch_key_event(
        self,
        key: str,
        code: str,
        modifiers: int = 0,
    ) -> None:
        """Send keyDown/char/keyUp events for a single keystroke (CJK)."""
        for ev_type in ("keyDown", "char", "keyUp"):
            await self.send(
                "Input.dispatchKeyEvent",
                {
                    "type": ev_type,
                    "key": key,
                    "code": code,
                    "modifiers": modifiers,
                },
            )

    async def query_selector_all(self, selector: str) -> int:
        """Return the count of elements matching `selector` in the main frame."""
        # NodeList isn't always JSON-serializable by `returnByValue`, so
        # we ask JS for the length directly.
        value = await self.evaluate(
            f"document.querySelectorAll({json.dumps(selector)}).length"
        )
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    async def close(self) -> None:
        """Close the underlying WebSocket; idempotent."""
        if self._closed:
            return
        self._closed = True
        await self._ws.close()