from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.events import EventBus
from app.models import Book, Job, JobEvent, SourceFiles

pytestmark = pytest.mark.anyio


def job() -> Job:
    return Job(
        job_id="snapshot-test",
        title="Original",
        status="running",
        progress=0.2,
        created_at=datetime(2026, 9, 26, tzinfo=UTC),
        updated_at=datetime(2026, 9, 26, tzinfo=UTC),
        book=Book(title="Original book"),
        source=SourceFiles(
            epub_name="original.epub", audio_name="audio.mp3", epub_bytes=1, audio_bytes=2
        ),
    )


async def test_published_events_preserve_state_and_nested_models() -> None:
    bus = EventBus()
    current = job()
    event = JobEvent(type="progress", job=current)
    async with bus.subscribe(current.job_id) as queue:
        bus.publish(current.job_id, event)
        current.status = "succeeded"
        current.progress = 1
        current.title = "Changed"
        current.book.title = "Changed book"
        current.source.epub_name = "changed.epub"
        current.updated_at = datetime(2026, 9, 27, tzinfo=UTC)
        event.type = "done"
        received = queue.get_nowait()
    assert received.type == "progress"
    assert received.job.status == "running"
    assert received.job.progress == 0.2
    assert received.job.title == "Original"
    assert received.job.book.title == "Original book"
    assert received.job.source.epub_name == "original.epub"
    assert received.job.updated_at == datetime(2026, 9, 26, tzinfo=UTC)


async def test_subscriber_mutation_cannot_change_other_deliveries_or_producer() -> None:
    bus = EventBus()
    current = job()
    async with bus.subscribe(current.job_id) as first, bus.subscribe(current.job_id) as second:
        bus.publish(current.job_id, JobEvent(type="progress", job=current))
        received = first.get_nowait()
        received.type = "done"
        received.job.status = "failed"
        received.job.book.title = "Changed by subscriber"
        other = second.get_nowait()
    assert other.type == "progress"
    assert other.job.status == current.status == "running"
    assert other.job.book.title == current.book.title == "Original book"


async def test_successive_events_keep_their_publication_states() -> None:
    bus = EventBus()
    current = job()
    async with bus.subscribe(current.job_id) as queue:
        bus.publish(current.job_id, JobEvent(type="progress", job=current))
        current.progress = 0.8
        bus.publish(current.job_id, JobEvent(type="progress", job=current))
        current.status = "succeeded"
        current.progress = 1
        bus.publish(current.job_id, JobEvent(type="done", job=current))
        received = [queue.get_nowait() for _ in range(3)]
    assert [event.job.progress for event in received] == [0.2, 0.8, 1]
    assert [event.job.status for event in received] == ["running", "running", "succeeded"]
