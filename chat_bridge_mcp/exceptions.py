from __future__ import annotations

from typing import Any


class BridgeError(Exception):
    """Base exception for chat-bridge-mcp. Never raised directly.

    Each subclass carries:
      - peer:    the peer name this error pertains to ("claude" | "chatgpt" | None)
      - context: free-form dict for the /health envelope and structured logging
    """

    peer: str | None = None

    def __init__(
        self,
        message: str = "",
        *,
        peer: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        if peer is not None:
            self.peer = peer
        self.context = dict(context) if context else {}
        super().__init__(message)

    def __str__(self) -> str:
        if self.peer is not None:
            return f"[{self.peer}] {self.message}"
        return self.message


class PeerNotAttachedError(BridgeError):
    """CDP target page discovery returned zero matches, or WebSocket dropped."""


class SelectorMissingError(BridgeError):
    """settings/selectors.yaml missing a required key for the current OS."""


class SelectorUnmatchedError(BridgeError):
    """Configured selector exists in selectors.yaml but no DOM match (selector drift)."""


class StreamingTimeoutError(BridgeError):
    """Response did not complete within streaming_timeout_seconds."""


class GuardrailFailure(BridgeError):
    """Guardrail template fails validation, or source_reply contains the nonce."""


class CDPProtocolError(BridgeError):
    """Malformed JSON-RPC response from CDP target, or CDP-level WS disconnect surfaced."""