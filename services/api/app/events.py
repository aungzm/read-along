from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .models import JobEvent


class EventBus:
    """Fan a job's events out to any number of waiting subscribers.

    Each subscriber gets its own bounded queue. A subscriber that stops reading
    is allowed to lose events rather than block the job that is producing them;
    the client can recover the current state from ``GET /api/jobs/{id}``.
    """

    def __init__(self, *, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue[JobEvent]]] = defaultdict(set)

    def publish(self, job_id: str, event: JobEvent) -> None:
        for queue in list(self._subscribers.get(job_id, ())):
            try:
                # Each delivery owns a snapshot, including nested book/source
                # models. Neither the producer nor another subscriber can
                # change this queued event after publication.
                queue.put_nowait(event.model_copy(deep=True))
            except asyncio.QueueFull:
                continue

    @asynccontextmanager
    async def subscribe(self, job_id: str) -> AsyncIterator[asyncio.Queue[JobEvent]]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers[job_id].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[job_id].discard(queue)
            if not self._subscribers[job_id]:
                self._subscribers.pop(job_id, None)
