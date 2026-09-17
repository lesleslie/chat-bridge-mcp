from __future__ import annotations

from datetime import datetime, UTC

import pytest

from chat_bridge_mcp.exceptions import (
    BridgeError,
    StreamingTimeoutError,
)
from chat_bridge_mcp.peers.base import (
    DesktopPeerAdapter,
    PeerHealth,
    PeerReply,
    PeerStatus,
)


class FakePeer(DesktopPeerAdapter):
    """Concrete subclass used to test the abstract base contract only.

    The real subclasses (claude.py, chatgpt.py) call ``super().__init__()``
    with ``(config, runtime)`` and follow the attach/detach lifecycle.
    Here we exercise only the base class invariants (counter increments,
    status/health snapshots, dataclass frozenness).
    """

    name = "fake"
    cdp_port = 19229

    def __init__(self, *, ok: bool = True) -> None:
        # Bypass the (config, runtime) signature so the test can build
        # a peer without standing up a ChatBridgeConfig. We still need
        # the base-class state (feed_state, _page_id, ...) so the public
        # API behaves as documented.
        DesktopPeerAdapter.__init__(self, config=None, runtime=None)
        self.ok = ok
        self.connected = False
        self.sent: list[str] = []

    async def attach(self) -> None:
        # `ok=False` exercises the error path: connected stays False and
        # _send_uncounted raises. `ok=True` (default) sets connected=True.
        self.connected = self.ok
        # Per base-class contract: subclasses MUST set entities_count=1
        # at the end of successful attach() so status()/health() can
        # report attached=True.
        self.feed_state.entities_count = 1

    async def detach(self) -> None:
        self.connected = False
        self.feed_state.entities_count = 0

    async def _send_uncounted(self, prompt: str, *, system: str | None = None) -> PeerReply:
        self.sent.append(prompt)
        if not self.connected:
            raise StreamingTimeoutError("not connected", peer=self.name)
        now = datetime.now(UTC)
        return PeerReply(
            text="ok",
            model_used=None,
            duration_ms=1,
            started_at=now,
            finished_at=now,
            peer=self.name,
            char_count=2,
        )


@pytest.mark.asyncio
async def test_send_increments_cycles_total_on_success():
    p = FakePeer()
    await p.attach()
    assert p.feed_state.cycles_total == 0
    await p.send("hello")
    assert p.feed_state.cycles_total == 1
    assert p.feed_state.errors_total == 0
    assert p.last_call_succeeded is True


@pytest.mark.asyncio
async def test_send_increments_errors_total_on_exception_and_still_counts_cycle():
    p = FakePeer(ok=False)
    await p.attach()
    with pytest.raises(StreamingTimeoutError):
        await p.send("anything")
    assert p.feed_state.cycles_total == 1  # always incremented
    assert p.feed_state.errors_total == 1
    assert p.last_call_succeeded is False


@pytest.mark.asyncio
async def test_status_snapshot_uses_in_memory_counters():
    p = FakePeer()
    await p.attach()
    await p.send("x")
    s = p.status()
    assert s.name == "fake"
    assert s.attached is True
    assert s.last_reply_char_count == 2


@pytest.mark.asyncio
async def test_health_shape_matches_four_signal():
    p = FakePeer()
    await p.attach()
    await p.send("x")
    h = await p.health()
    assert isinstance(h, PeerHealth)
    assert h.cycles_total == 1
    assert h.errors_total == 0
    assert h.entities_count in (0, 1)
    assert isinstance(h.last_updated_timestamp, str)


def test_peer_reply_dataclass_is_frozen():
    r = PeerReply(
        text="x",
        model_used=None,
        duration_ms=1,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        peer="claude",
        char_count=1,
    )
    with pytest.raises(Exception):  # FrozenInstanceError, AttributeError, etc.
        r.peer = "chatgpt"
