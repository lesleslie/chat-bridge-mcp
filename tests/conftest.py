"""Shared fixtures for chat-bridge-mcp tests.

The `fake_cdp` fixture is the FakeCdpServer used by `tests/unit/test_cdp.py`
to exercise the production CDPConnection / CDPSession against an in-process
HTTP /json endpoint and a real websockets.serve() handler bound to port 0.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import pytest
import websockets

# An async callable that may inject raw JSON messages onto the live
# WebSocket before the fixture sends the matching response. Used by the
# out-of-order-response test to simulate a CDP target whose events arrive
# interleaved with reply frames.
BeforeResponseHook = Callable[[Any, dict[str, Any]], "asyncio.Future[None] | None"]


class FakeCdpServer:
    """Tiny CDP-shaped fake: HTTP /json + WebSocket JSON-RPC.

    - HTTP GET /json returns a single fake target of type "page" whose
      webSocketDebuggerUrl points at the embedded WS server.
    - The WS server accepts JSON-RPC requests and replies with the shape
      the production CDPSession expects:
        * Runtime.evaluate -> {"id": N, "result": {"result": {"value": V}}}
        * anything else     -> {"id": N, "result": {}}
    - `eval_handler` defaults to a small int-arithmetic parser so simple
      expressions like `"1 + 1"` evaluate to 2.
    - `before_response_hook` (optional async callable) is invoked with the
      live WS and the incoming message after it has been parsed but
      before the fixture sends its reply. Tests can use it to inject
      out-of-order responses, events, or error envelopes.
    """

    def __init__(
        self,
        eval_handler: Callable[[str], Any] | None = None,
        before_response_hook: BeforeResponseHook | None = None,
    ) -> None:
        self.eval_handler: Callable[[str], Any] = eval_handler or self._default_eval
        self.before_response_hook: BeforeResponseHook | None = before_response_hook
        self.host = "127.0.0.1"
        self.port_http = 0
        self.port_ws = 0
        self.received: list[dict[str, Any]] = []
        self._http_server: asyncio.AbstractServer | None = None
        self._ws_server: Any = None

    @staticmethod
    def _default_eval(expression: str) -> Any:
        """Evaluate a tiny subset of JavaScript expressions on the server.

        Supports integer literals and `int (+|-|*|/) int`. Anything else
        returns None. We deliberately do NOT pass through to Python's
        `eval()` because the fixture must be safe even if a future test
        accidentally points it at attacker-controlled text.
        """
        expr = expression.strip()
        try:
            if re.fullmatch(r"-?\d+", expr):
                return int(expr)
            match = re.fullmatch(r"\s*(-?\d+)\s*([+\-*/])\s*(-?\d+)\s*", expr)
            if match:
                left, op, right = match.groups()
                l, r = int(left), int(right)
                if op == "+":
                    return l + r
                if op == "-":
                    return l - r
                if op == "*":
                    return l * r
                if op == "/" and r != 0:
                    return l // r
        except (ValueError, ZeroDivisionError):
            return None
        return None

    def target_descriptor(self) -> dict[str, Any]:
        """Build the single fake target entry returned by /json."""
        return {
            "id": "PAGE-FAKE-1",
            "type": "page",
            "title": "Fake Chat Page",
            "url": "about:blank",
            "webSocketDebuggerUrl": (
                f"ws://{self.host}:{self.port_ws}/devtools/page/PAGE-FAKE-1"
            ),
        }

    async def start(self) -> None:
        """Bind HTTP /json (port 0) and the WS server (port 0)."""

        async def handle_http(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                request_line = await reader.readline()
                # Skip headers
                while True:
                    line = await reader.readline()
                    if line in (b"\r\n", b"", b"\n"):
                        break
                parts = request_line.split(b" ")
                if len(parts) < 2:
                    return
                path = parts[1].decode("ascii", errors="ignore")
                if path.startswith("/json"):
                    body = json.dumps([self.target_descriptor()]).encode("utf-8")
                    response = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                        b"Connection: close\r\n\r\n" + body
                    )
                    writer.write(response)
                    await writer.drain()
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass

        async def handle_ws(ws: Any) -> None:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self.received.append(msg)
                msg_id = msg.get("id")
                if msg_id is None:
                    # Unsolicited request (e.g., an event from the client);
                    # CDP targets ignore these. Do not reply.
                    continue
                if self.before_response_hook is not None:
                    result = self.before_response_hook(ws, msg)
                    if asyncio.iscoroutine(result):
                        await result
                method = msg.get("method")
                if method == "Runtime.evaluate":
                    params = msg.get("params") or {}
                    expr = params.get("expression", "")
                    value = self.eval_handler(expr)
                    response = {
                        "id": msg_id,
                        "result": {"result": {"value": value}},
                    }
                else:
                    response = {"id": msg_id, "result": {}}
                await ws.send(json.dumps(response))

        self._http_server = await asyncio.start_server(
            handle_http, host=self.host, port=0
        )
        sock = self._http_server.sockets[0]
        self.port_http = sock.getsockname()[1]

        self._ws_server = await websockets.serve(handle_ws, host=self.host, port=0)
        ws_sock = self._ws_server.sockets[0]
        self.port_ws = ws_sock.getsockname()[1]

    async def stop(self) -> None:
        if self._http_server is not None:
            self._http_server.close()
            await self._http_server.wait_closed()
            self._http_server = None
        if self._ws_server is not None:
            self._ws_server.close()
            await self._ws_server.wait_closed()
            self._ws_server = None


@pytest.fixture
async def fake_cdp():
    """Yield a started FakeCdpServer; stop it on teardown."""
    server = FakeCdpServer()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()