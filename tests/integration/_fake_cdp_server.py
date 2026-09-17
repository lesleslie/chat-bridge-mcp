"""Tiny CDP-shaped fake: HTTP /json + WebSocket Runtime.evaluate.

Used by tests/integration/test_server_lifecycle.py to boot the bridge
against a real subprocess instead of real Claude/ChatGPT Desktop.
Writes the bound ports to <tmp>/cdp_ports.json for the bridge_proc
fixture to read.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import websockets


def _eval_handler(expr: str) -> object:
    """Route a Runtime.evaluate expression to a fake JS return value.

    Selectors: when the expression is `document.querySelectorAll(...).length`
    (the call shape the bridge uses for selector self-tests), return a
    positive integer so the bridge's attach self-test passes. For innerText
    extraction patterns (`document.querySelector(...)?.innerText ?? ''`),
    return an empty string so the streaming-done detector falls back to
    the content-hash stability path. For the model-selector lookup, return
    a fake model name. For anything else, echo back the expression under
    a stable shape so callers can sanity-check round-tripping.
    """
    stripped = expr.strip()
    if stripped.startswith("1 + 1"):
        return 2
    # The chatgpt adapter's response-extraction expression contains BOTH
    # `querySelectorAll` AND `innerText`, so check innerText FIRST so the
    # extraction path returns a string (the count-check would return a
    # number, which the adapter's `text_str = text_obj if isinstance(...)`
    # would coerce to "").
    if "innerText" in expr:
        # Return a fixed marker so integration tests can assert
        # ask_chatgpt returned *some* plaintext reply. The streaming-done
        # detector will see three stable consecutive polls and exit
        # cleanly.
        return "fake-reply-marker"
    if "querySelectorAll" in expr and ".length" in expr:
        # The chatgpt adapter polls the stop_generating_indicator selector
        # to detect when streaming finished. Return 0 (count of absent
        # elements) so the adapter exits the polling loop after 3
        # consecutive absent polls. For input_box / send_button /
        # response_container self-tests, return a positive count.
        if "Stop" in expr or "stop" in expr:
            return 0
        return 3
    if "model-selector" in expr:
        return "fake-model"
    if "querySelector" in expr and ".focus" in expr:
        return None
    if "Object.getOwnPropertyDescriptor" in expr and (
        "value" in expr and "set.call" in expr
    ):
        # React setter invocation; return None to signal success.
        return None
    return {"echoed": expr}


EVAL_HANDLER: Callable[[str], object] = _eval_handler


# Bound port discovery (the bridge reads this file)
PORTS_FILE = Path(
    os.environ.get(
        "CHAT_BRIDGE_MCP_FAKE_CDP_PORTS_FILE",
        str(Path(tempfile.gettempdir()) / "fake_cdp_ports.json"),
    )
)


def _build_json_handler(claude_port: int, chatgpt_port: int, ws_port: int) -> type[BaseHTTPRequestHandler]:
    """Closure-bound HTTP handler returning the discovery /json payload."""

    class _JsonHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/json":
                self.send_error(404)
                return
            payload = [
                {
                    "id": f"PAGE-{port}-{n}",
                    "type": "page",
                    "webSocketDebuggerUrl": (
                        f"ws://127.0.0.1:{ws_port}/devtools/page/PAGE-{port}-{n}"
                    ),
                    "title": (
                        f"Fake ChatGPT {n}"
                        if port == chatgpt_port
                        else f"Fake Claude {n}"
                    ),
                }
                for port in (claude_port, chatgpt_port)
                for n in range(2)
            ]
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object, **kwargs: object) -> None:
            return

    return _JsonHandler


async def _ws_handler(ws: object) -> None:
    """Handle JSON-RPC: respond to Runtime.evaluate by routing to EVAL_HANDLER.

    Modern `websockets` (>=11) calls the handler with the connection only,
    not (ws, path). The path is reachable via ``ws.request.path`` if needed.
    """
    try:
        async for raw in ws:  # type: ignore[attr-defined]
            msg = json.loads(raw)
            if msg.get("method") != "Runtime.evaluate":
                await ws.send(json.dumps({"id": msg["id"], "result": {}}))  # type: ignore[attr-defined]
                continue
            expr = msg.get("params", {}).get("expression", "")
            value = EVAL_HANDLER(expr)
            await ws.send(  # type: ignore[attr-defined]
                json.dumps(
                    {
                        "id": msg["id"],
                        "result": {
                            "result": {
                                "type": "object" if isinstance(value, dict) else "number",
                                "value": value,
                            }
                        },
                    }
                )
            )
    except Exception as exc:  # noqa: BLE001 (intentional blanket catch in fake infra)
        print(f"[fake-cdp] ws_handler exception: {exc!r}", flush=True)


def _write_ports(claude_port: int, chatgpt_port: int) -> None:
    PORTS_FILE.write_text(
        json.dumps({"claude_port": claude_port, "chatgpt_port": chatgpt_port})
    )
    print(f"[fake-cdp] wrote ports to {PORTS_FILE}", flush=True)


async def main() -> None:
    claude_port = 9229  # Electron default
    chatgpt_port = 9230
    ws_port = 9232
    _write_ports(claude_port, chatgpt_port)

    # Serve /json on BOTH per-peer CDP ports (9229 + 9230) so the bridge
    # can discover targets on whichever port it was configured for. The
    # websocket debugger URL each handler returns points at the shared
    # ws_port (9232).
    claude_httpd = HTTPServer(
        ("127.0.0.1", claude_port), _build_json_handler(claude_port, chatgpt_port, ws_port)
    )
    chatgpt_httpd = HTTPServer(
        ("127.0.0.1", chatgpt_port), _build_json_handler(claude_port, chatgpt_port, ws_port)
    )
    ws_server = await websockets.serve(_ws_handler, "127.0.0.1", ws_port)
    import threading

    claude_thread = threading.Thread(target=claude_httpd.serve_forever, daemon=True)
    chatgpt_thread = threading.Thread(target=chatgpt_httpd.serve_forever, daemon=True)
    claude_thread.start()
    chatgpt_thread.start()
    try:
        await ws_server.wait_closed()
    finally:
        claude_httpd.shutdown()
        chatgpt_httpd.shutdown()
        ws_server.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
