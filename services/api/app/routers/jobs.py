from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ..models import Job, JobCreate, JobEvent
from ..store import JobStore

router = APIRouter(prefix="/jobs", tags=["jobs"])

# How long the stream may sit idle before sending a comment to keep it open.
HEARTBEAT_SECONDS = 15.0


def get_store(request: Request) -> JobStore:
    return request.app.state.store


StoreDep = Annotated[JobStore, Depends(get_store)]


@router.get("", response_model=list[Job])
async def list_jobs(store: StoreDep) -> list[Job]:
    return store.list()


@router.post("", response_model=Job, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, store: StoreDep) -> Job:
    return store.create(payload)


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: str, store: StoreDep) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job")
    return job


@router.post("/{job_id}/cancel", response_model=Job)
async def cancel_job(job_id: str, store: StoreDep) -> Job:
    job = await store.cancel(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job")
    return job


def _format_event(event: JobEvent) -> str:
    payload = event.model_dump_json(by_alias=True)
    return f"event: {event.type}\ndata: {payload}\n\n"


@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    store: StoreDep,
) -> StreamingResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job")

    async def stream() -> AsyncIterator[str]:
        yield _format_event(JobEvent(type="snapshot", job=job))

        async with store.bus.subscribe(job_id) as queue:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _format_event(event)
                if event.type == "done":
                    break

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache, no-transform",
            "x-accel-buffering": "no",
        },
    )
