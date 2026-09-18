from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any

from mcp_common.health.feed import (
    HealthFeedState,
    record_error,
    record_success,
)

from chat_bridge_mcp.exceptions import BridgeError

if TYPE_CHECKING:
    from chat_bridge_mcp.cdp import CDPSession, CDPConnection


@dataclass(frozen=True)
class PeerReply:
    text: str
    model_used: str | None
    duration_ms: int
    started_at: datetime
    finished_at: datetime
    peer: str
    char_count: int


@dataclass(frozen=True)
class PeerStatus:
    name: str
    attached: bool
    last_call_at: str | None  # ISO-8601-formatted timestamp
    last_reply_char_count: int | None


@dataclass(frozen=True)
class PeerHealth:
    """Deep surface returned by `get_peer_health(peer)`.

    Mirrors the four-signal wiring-discipline contract:
    entities_count / last_updated_timestamp / errors_total / cycles_total.
    """

    name: str
    attached: bool
    cdp_port: int
    page_id: str | None
    last_call_succeeded: bool | None
    last_call_error: str | None
    total_calls: int
    errors_total: int
    cycles_total: int
    entities_count: int
    last_updated_timestamp: str  # ISO-8601-formatted


class DesktopPeerAdapter(ABC):
    """Per-peer adapter: drives one desktop via CDP.

    Subclasses implement ``_send_uncounted``; ``send()`` wraps it with the
    try/finally counter pattern pinned in §5.1.c step 8.

    Lifecycle contract for subclasses:
      - ``attach()`` MUST set ``self.feed_state.entities_count = 1`` at the
        end of a successful run so ``status()`` and ``health()`` can report
        ``attached=True`` via the four-signal shape.
      - ``detach()`` MUST set ``self.feed_state.entities_count = 0`` so the
        adapter reports as detached on the next probe.
    """

    name: str  # subclasses set: "claude" | "chatgpt"
    cdp_port: int  # subclasses set (per-peer; see C6 fix below)

    def __init__(self, config: Any, runtime: Any) -> None:
        self.config = config
        self.runtime = runtime
        self.feed_state = HealthFeedState()
        self._page_id: str | None = None
        self._last_call_at: datetime | None = None
        self._last_reply_char_count: int | None = None
        self.last_call_succeeded: bool | None = None
        self._session: CDPSession | None = None
        self._target: CDPConnection | None = None
        # Guards the check-then-act race in _ensure_session when two concurrent
        # first-time callers both observe _session is None. NOT a serialization
        # lock on _send_uncounted — spec §5.6's no-serialization rule still holds;
        # the lock covers only the (small) gap between "is _session None?" and
        # "now it's not None".
        self._session_lock: asyncio.Lock = asyncio.Lock()
        self._last_call_error: str | None = None

    @abstractmethod
    async def attach(self) -> None:
        """Open CDP, resolve the page, run selector self-test, cache page_id.

        Subclasses MUST set ``self.feed_state.entities_count = 1`` at the
        end of successful ``attach()`` so that ``status()``/``health()``
        can report ``attached=True`` via the four-signal shape.
        """

    @abstractmethod
    async def detach(self) -> None:
        """Close CDP session and websocket. Should reset ``entities_count`` to 0."""

    @abstractmethod
    async def _send_uncounted(self, prompt: str, *, system: str | None = None) -> PeerReply:
        """The peer-specific send without counter bookkeeping."""

    async def send(self, prompt: str, *, system: str | None = None) -> PeerReply:
        # Per spec §5.1.c step 8: cycles_total++ at top of try:, errors_total++
        # in except:, success update in else:. The finally-style guarantee
        # is provided by Python's try/except/else (a missing else would skip
        # the success branch on exception).
        self.feed_state.cycles_total += 1
        self.feed_state.last_updated_timestamp = time.time()
        try:
            result = await self._send_uncounted(prompt, system=system)
        except BridgeError as exc:
            # `record_error(state)` only sets `last_error_at` / `first_unhealthy_at`
            # timestamps; it does NOT increment `errors_total`. We do that
            # manually so the per-peer four-signal shape stays correct.
            self.feed_state.errors_total += 1
            record_error(self.feed_state)
            self.last_call_succeeded = False
            self._last_call_error = str(exc)
            self._last_call_at = datetime.now(UTC)
            raise
        else:
            record_success(self.feed_state)
            self.last_call_succeeded = True
            self._last_call_error = None
            self._last_call_at = datetime.now(UTC)
            self._last_reply_char_count = result.char_count
            return result

    def status(self) -> PeerStatus:
        return PeerStatus(
            name=self.name,
            attached=self.feed_state.entities_count > 0,
            last_call_at=self._last_call_at.isoformat() if self._last_call_at else None,
            last_reply_char_count=self._last_reply_char_count,
        )

    async def health(self) -> PeerHealth:
        if self._last_call_at is not None:
            ts: str = self._last_call_at.isoformat()
        elif self.feed_state.last_updated_timestamp is not None:
            ts = datetime.fromtimestamp(
                self.feed_state.last_updated_timestamp, UTC
            ).isoformat()
        else:
            ts = datetime.now(UTC).isoformat()
        return PeerHealth(
            name=self.name,
            attached=self.feed_state.entities_count > 0,
            cdp_port=self.cdp_port,
            page_id=self._page_id,
            last_call_succeeded=self.last_call_succeeded,
            last_call_error=self._last_call_error,
            total_calls=self.feed_state.cycles_total,
            errors_total=self.feed_state.errors_total,
            cycles_total=self.feed_state.cycles_total,
            entities_count=self.feed_state.entities_count,
            last_updated_timestamp=ts,
        )
