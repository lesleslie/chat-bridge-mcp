"""MCP tool registry for chat-bridge-mcp.

The module-level `mcp` singleton lives in `chat_bridge_mcp.server`. The
``@mcp.tool()`` decorators bind against that singleton when
:meth:`register_tools` is invoked from server.py, AFTER ``mcp =
FastMCP(...)`` has executed. This ordering avoids the circular import.

Task 11b adds two tool stubs (ask_chatgpt, get_peer_health) so the named
integration tests in spec §9.1 can exercise the lifecycle + four-signal
shape end-to-end. The full tool surface (forward_chatgpt, ask_claude,
etc.) is filled in by a later task; the stubs return the minimum the
tests assert on.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chat_bridge_mcp.peers.base import DesktopPeerAdapter


_clients: dict[str, DesktopPeerAdapter] = {}
_tools_registered: bool = False


def set_clients(**clients: DesktopPeerAdapter) -> None:
    """Bind peer adapters at startup. Per-peer kwargs: claude=, chatgpt=."""
    _clients.update(clients)


def get_client(name: str) -> DesktopPeerAdapter:
    """Look up the adapter for `name` ('claude' | 'chatgpt').

    Raises KeyError when the named client has not been bound yet (the
    bridge was not started up — the caller should treat that as a fatal
    wiring error).
    """
    return _clients[name]


def get_clients() -> dict[str, DesktopPeerAdapter]:
    """Snapshot of the bound peer-adapter registry (for diagnostics)."""
    return dict(_clients)


def _reset() -> None:
    """Test-only: clear the registry."""
    _clients.clear()


def _render_error(exc: BaseException, default_peer: str | None = None) -> str:
    """Render a BridgeError as its chat-surface string (imported lazily
    to avoid a circular import at module load time).

    ``default_peer`` is the peer name to inject when the exception is
    a PeerNotAttachedError that did not carry a peer attribute (e.g.
    raised by the CDPSession wrapper when the WebSocket disconnects
    before the adapter can decorate it).
    """
    from chat_bridge_mcp.exceptions import BridgeError, PeerNotAttachedError
    from chat_bridge_mcp.server import _tool_error_string

    if isinstance(exc, BridgeError):
        if isinstance(exc, PeerNotAttachedError) and not exc.peer and default_peer:
            exc.peer = default_peer
        return _tool_error_string(exc)
    return "internal error; see logs"


def register_tools() -> None:
    """Bind @mcp.tool() decorators against the singleton.

    Idempotent: subsequent calls are no-ops. Called from server.py after
    `mcp = FastMCP(...)` so the FastMCP instance is fully constructed
    before tool registration.
    """
    global _tools_registered
    if _tools_registered:
        return
    # Late import: server.mcp must exist before we reference it.
    from chat_bridge_mcp.server import mcp

    @mcp.tool()
    async def ask_chatgpt(question: str, system: str | None = None) -> str:
        """Send `question` to ChatGPT Desktop and return the plaintext reply.

        Per spec §5.1.a: empty question returns an error string; if `system` is
        provided it's prepended as a system-level instruction. No guardrail — verbatim.
        """
        if not question.strip():
            return "Empty question. Provide non-empty text."
        text = f"{system}\n\n{question}" if system else question
        try:
            client = get_client("chatgpt")
        except KeyError:
            from chat_bridge_mcp.exceptions import PeerNotAttachedError

            return _render_error(
                PeerNotAttachedError("chatgpt", peer="chatgpt"),
                default_peer="chatgpt",
            )
        try:
            reply = await client.send(text)
        except Exception as exc:  # noqa: BLE001 (chat surface always returns; CancelledError propagates correctly)
            return _render_error(exc, default_peer="chatgpt")
        return reply.text

    @mcp.tool()
    async def ask_claude(question: str, system: str | None = None) -> str:
        """Send `question` to Claude Desktop and return the plaintext reply.

        Per spec §5.1.a: empty question returns an error string; if `system` is
        provided it's prepended as a system-level instruction. No guardrail — verbatim.
        """
        if not question.strip():
            return "Empty question. Provide non-empty text."
        text = f"{system}\n\n{question}" if system else question
        try:
            client = get_client("claude")
        except KeyError:
            from chat_bridge_mcp.exceptions import PeerNotAttachedError

            return _render_error(
                PeerNotAttachedError("claude", peer="claude"),
                default_peer="claude",
            )
        try:
            reply = await client.send(text)
        except Exception as exc:  # noqa: BLE001 (chat surface always returns; CancelledError propagates correctly)
            return _render_error(exc, default_peer="claude")
        return reply.text

    @mcp.tool()
    async def forward_chatgpt(
        source_peer: str, source_reply: str, ask_for_opinion: bool = True
    ) -> str:
        """Wrap source_reply in the guardrail nonce template and inject
        it into ChatGPT Desktop. See spec section 5.1.b: the prior output
        from ``source_peer`` is wrapped in the strict-isolation framing
        (section 10a.2) so ChatGPT treats it as data, not instructions.
        Returns the chatgpt adapter's plaintext reply, or the pinned
        chat-surface error string on failure.
        """
        from chat_bridge_mcp import guardrail

        try:
            client = get_client("chatgpt")
        except KeyError:
            from chat_bridge_mcp.exceptions import PeerNotAttachedError

            return _render_error(
                PeerNotAttachedError("chatgpt", peer="chatgpt"),
                default_peer="chatgpt",
            )
        try:
            wrapped = guardrail.wrap(
                source_reply,
                source_peer=source_peer,
                ask_for_opinion=ask_for_opinion,
            )
        except Exception as exc:  # noqa: BLE001 (chat surface always returns; CancelledError propagates correctly)
            return _render_error(exc, default_peer="chatgpt")
        try:
            reply = await client.send(wrapped)
        except Exception as exc:  # noqa: BLE001 (chat surface always returns; CancelledError propagates correctly)
            return _render_error(exc, default_peer="chatgpt")
        return reply.text

    @mcp.tool()
    async def forward_claude(
        source_peer: str, source_reply: str, ask_for_opinion: bool = True
    ) -> str:
        """Wrap source_reply in the guardrail nonce template and inject
        it into Claude Desktop. Symmetric to ``forward_chatgpt``; see
        spec section 5.1.b. The prior output from ``source_peer`` is
        wrapped in the strict-isolation framing (section 10a.2) so Claude
        treats it as data, not instructions. Returns the claude
        adapter's plaintext reply, or the pinned chat-surface error
        string on failure.
        """
        from chat_bridge_mcp import guardrail

        try:
            client = get_client("claude")
        except KeyError:
            from chat_bridge_mcp.exceptions import PeerNotAttachedError

            return _render_error(
                PeerNotAttachedError("claude", peer="claude"),
                default_peer="claude",
            )
        try:
            wrapped = guardrail.wrap(
                source_reply,
                source_peer=source_peer,
                ask_for_opinion=ask_for_opinion,
            )
        except Exception as exc:  # noqa: BLE001 (chat surface always returns; CancelledError propagates correctly)
            return _render_error(exc, default_peer="claude")
        try:
            reply = await client.send(wrapped)
        except Exception as exc:  # noqa: BLE001 (chat surface always returns; CancelledError propagates correctly)
            return _render_error(exc, default_peer="claude")
        return reply.text

    @mcp.tool()
    async def get_peer_health(peer: str) -> str:
        """Return the four-signal health envelope for `peer` as JSON."""
        try:
            client = get_client(peer)
        except KeyError:
            from chat_bridge_mcp.exceptions import PeerNotAttachedError

            return _render_error(PeerNotAttachedError(peer, peer=peer), default_peer=peer)
        health = await client.health()
        return json.dumps(health.__dict__, default=str)

    @mcp.tool()
    async def list_peers() -> str:
        """Return the operator-facing roster of bound peers as a JSON array."""
        try:
            records: list[dict[str, object]] = []
            for adapter in get_clients().values():
                health = await adapter.health()
                records.append(
                    {
                        "name": health.name,
                        "attached": health.attached,
                        "cycles_total": health.cycles_total,
                        "errors_total": health.errors_total,
                        "last_updated_timestamp": health.last_updated_timestamp,
                        "last_call_succeeded": health.last_call_succeeded,
                        "entities_count": health.entities_count,
                    }
                )
            return json.dumps(records, default=str)
        except Exception as exc:  # noqa: BLE001
            return _render_error(exc)

    _tools_registered = True
