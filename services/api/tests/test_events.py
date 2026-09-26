from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from support import FAST_STAGES, SLOW_STAGES, create_job, make_client, running_server

from app.events import EventBus
from app.models import Job
from app.routers.jobs import job_events
from app.store import JobStore

pytestmark = pytest.mark.anyio


async def test_unknown_job_stream_is_not_found(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=FAST_STAGES) as client:
        response = await client.get("/api/jobs/nope/events")

    assert response.status_code == 404


async def test_event_stream_opens_with_a_snapshot(tmp_path: Path) -> None:
    # Slow stages keep the job alive while the stream is read. Cancelling it
    # publishes a `done` event, which closes the stream cleanly.
    async with running_server(tmp_path, stage_seconds=SLOW_STAGES) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            created = (await create_job(client)).json()
            job_id = created["jobId"]

            async with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")

                lines: list[str] = []
                cancelled = False
                async for line in response.aiter_lines():
                    lines.append(line)
                    if line == "event: snapshot" and not cancelled:
                        await client.post(f"/api/jobs/{job_id}/cancel")
                        cancelled = True
                    if line == "event: done":
                        break

    text = "\n".join(lines)
    assert "event: snapshot" in text
    assert "event: done" in text
    assert job_id in text


async def test_finished_job_http_stream_reaches_eof(tmp_path: Path) -> None:
    async with running_server(tmp_path, stage_seconds=SLOW_STAGES) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            job_id = (await create_job(client)).json()["jobId"]
            await client.post(f"/api/jobs/{job_id}/cancel")
            response = await client.get(f"/api/jobs/{job_id}/events", timeout=2)
            assert response.status_code == 200
            assert response.text.count("event: snapshot") == 1
            assert '"status":"cancelled"' in response.text


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def live_job() -> tuple[JobStore, Job]:
    job = Job(
        job_id="stream-test",
        title="Stream",
        status="running",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    store = JobStore(EventBus(queue_size=1))
    store._jobs[job.job_id] = job
    return store, job


def payload(chunk: str) -> dict:
    return json.loads(chunk.split("data: ", 1)[1])


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
async def test_terminal_snapshot_closes_stream_and_unsubscribes(status: str) -> None:
    store, job = live_job()
    job.status = status
    response = await job_events(job.job_id, ConnectedRequest(), store)
    iterator = response.body_iterator
    snapshot = payload(await anext(iterator))
    assert snapshot["type"] == "snapshot"
    assert snapshot["job"]["status"] == status
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(iterator), timeout=0.2)
    assert not store.bus._subscribers


async def test_completion_during_snapshot_delivery_is_not_missed() -> None:
    store, job = live_job()
    response = await job_events(job.job_id, ConnectedRequest(), store)
    iterator = response.body_iterator
    assert payload(await anext(iterator))["job"]["status"] == "running"
    assert job.job_id in store.bus._subscribers
    # This interval used to be before subscription. A one-item queue also
    # exercises overflow when progress and done are published together.
    store._apply(job, status="succeeded", progress=1)
    store._finish(job, "succeeded")
    event = payload(await asyncio.wait_for(anext(iterator), timeout=0.2))
    assert event["type"] == "done"
    assert event["job"]["status"] == "succeeded"
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)
    assert not store.bus._subscribers


async def test_snapshot_uses_latest_store_state_when_stream_starts() -> None:
    store, job = live_job()
    response = await job_events(job.job_id, ConnectedRequest(), store)
    store._jobs[job.job_id] = job.model_copy(update={"status": "cancelled"})
    iterator = response.body_iterator
    assert payload(await anext(iterator))["job"]["status"] == "cancelled"
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


async def test_heartbeat_recovers_terminal_state_without_a_done_event(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.jobs.HEARTBEAT_SECONDS", 0.01)
    store, job = live_job()
    response = await job_events(job.job_id, ConnectedRequest(), store)
    iterator = response.body_iterator
    await anext(iterator)
    job.status = "failed"
    event = payload(await asyncio.wait_for(anext(iterator), timeout=0.2))
    assert event["type"] == "done"
    assert event["job"]["status"] == "failed"
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


async def test_terminal_progress_event_finishes_stream_without_done_publication() -> None:
    store, job = live_job()
    response = await job_events(job.job_id, ConnectedRequest(), store)
    iterator = response.body_iterator
    await anext(iterator)
    store._apply(job, status="cancelled", stage=None)
    event = payload(await asyncio.wait_for(anext(iterator), timeout=0.2))
    assert event["type"] == "done"
    assert event["job"]["status"] == "cancelled"
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


async def test_stream_disconnect_releases_subscription() -> None:
    store, job = live_job()
    response = await job_events(job.job_id, ConnectedRequest(), store)
    iterator = response.body_iterator
    await anext(iterator)
    assert store.bus._subscribers
    await iterator.aclose()
    assert not store.bus._subscribers
