"""Server-sent events.

docs/04_FRONTEND_SPEC.md section 3: `GET /api/stream` carries `attempt`, `incident.opened`,
`incident.updated`, `incident.closed`, `action.executed`, `action.refused`, `escalation.opened`,
`escalation.decided`, `ledger.appended`, `sim.tick` and `sim.finished`. Pages subscribe to what
they need and refetch on relevant events.

The stream is a fan-out over an in-process queue. Salvage is one process (Architecture section 1),
so a broker would be a dependency bought for nothing.

Events carry ids and counts, never a message body or a contact, for the same reason the ledger
does not (docs/03_SECURITY_AND_ACCESS.md section 5): the browser is a place data ends up.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

# Every event name the frontend spec lists. A name outside this set is a bug rather than a new
# feature, so publish() refuses it.
EVENT_NAMES = frozenset(
    {
        "attempt",
        "incident.opened",
        "incident.updated",
        "incident.closed",
        "action.executed",
        "action.refused",
        "escalation.opened",
        "escalation.decided",
        "ledger.appended",
        "sim.tick",
        "sim.finished",
    }
)

# Per-subscriber queue depth. A slow browser tab drops old events rather than growing without
# bound or stalling the producer.
QUEUE_SIZE = 256


class UnknownEvent(ValueError):
    """An event name the frontend does not know how to handle."""


@dataclass
class EventBus:
    """One process, one bus."""

    subscribers: list[asyncio.Queue] = field(default_factory=list)
    published: int = 0
    dropped: int = 0

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def publish(self, name: str, payload: dict[str, Any]) -> None:
        if name not in EVENT_NAMES:
            raise UnknownEvent(
                f"{name!r} is not an event the dashboard handles; the set is in "
                "salvage/api/stream.py and docs/04_FRONTEND_SPEC.md section 3"
            )
        self.published += 1
        message = {"event": name, "data": payload}
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # The tab is not keeping up. Dropping the oldest is better than blocking the
                # simulator, and the pages refetch on any event they care about anyway.
                self.dropped += 1
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


BUS = EventBus()


async def event_source(bus: EventBus | None = None) -> AsyncIterator[dict[str, str]]:
    """The generator sse-starlette consumes.

    A comment line every fifteen seconds keeps a proxy from closing an idle connection, which is
    what an ops console left open on a second monitor mostly is.
    """
    bus = bus or BUS
    queue = bus.subscribe()
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                yield {"event": "ping", "data": "{}"}
                continue
            yield {"event": message["event"], "data": json.dumps(message["data"], default=str)}
    finally:
        bus.unsubscribe(queue)
