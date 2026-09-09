from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from ..config import get_settings
from ..models import Job, JobEvent, SourceFiles
from ..store import JobCapacityError, JobStore, new_job_id

router = APIRouter(prefix="/jobs", tags=["jobs"])

# How long the stream may sit idle before sending a comment to keep it open.
HEARTBEAT_SECONDS = 15.0

# One mebibyte per read, so a large audiobook never lands in memory whole.
CHUNK_BYTES = 1 << 20

EPUB_SUFFIXES = {".epub"}
AUDIO_SUFFIXES = {
    ".m4b",
    ".mp3",
    ".m4a",
}


def get_store(request: Request) -> JobStore:
    return request.app.state.store


def get_data_dir(request: Request) -> Path:
    return request.app.state.data_dir


StoreDep = Annotated[JobStore, Depends(get_store)]
DataDirDep = Annotated[Path, Depends(get_data_dir)]


async def _save_upload(
    upload: UploadFile,
    workspace: Path,
    *,
    stem: str,
    suffixes: set[str],
    max_bytes: int,
) -> tuple[Path, int]:
    """Stream one upload to ``workspace`` and return its path and byte count."""

    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type '{suffix or 'unknown'}'. Expected one of {allowed}.",
        )

    destination = workspace / f"{stem}{suffix}"
    written = 0
    with destination.open("wb") as sink:
        while chunk := await upload.read(CHUNK_BYTES):
            written += len(chunk)
            if written > max_bytes:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    "The upload is larger than the configured limit.",
                )
            sink.write(chunk)
    return destination, written


@router.get("", response_model=list[Job])
async def list_jobs(store: StoreDep) -> list[Job]:
    return store.list()


@router.post("", response_model=Job, status_code=status.HTTP_201_CREATED)
async def create_job(
    store: StoreDep,
    data_dir: DataDirDep,
    epub: Annotated[UploadFile, File(...)],
    audio: Annotated[UploadFile, File(...)],
) -> Job:
    """Create a job from an uploaded EPUB and audiobook.

    The files are written to a per-job workspace under ``data_dir``; the
    extract stage then reads the EPUB's metadata from disk.
    """

    settings = get_settings()
    if not store.has_capacity():
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "The processing queue is full. Try again shortly.",
            headers={"Retry-After": "5"},
        )
    job_id = new_job_id()
    workspace = data_dir / job_id
    workspace.mkdir(parents=True, exist_ok=True)

    try:
        epub_path, epub_bytes = await _save_upload(
            epub,
            workspace,
            stem="source",
            suffixes=EPUB_SUFFIXES,
            max_bytes=settings.max_upload_bytes,
        )
        audio_path, audio_bytes = await _save_upload(
            audio,
            workspace,
            stem="audio",
            suffixes=AUDIO_SUFFIXES,
            max_bytes=settings.max_upload_bytes,
        )
    except BaseException:
        shutil.rmtree(workspace, ignore_errors=True)
        raise

    source = SourceFiles(
        epub_name=epub.filename or epub_path.name,
        audio_name=audio.filename or audio_path.name,
        epub_bytes=epub_bytes,
        audio_bytes=audio_bytes,
    )
    title = Path(source.epub_name).stem or "Untitled"

    try:
        return store.create(
            job_id=job_id,
            title=title,
            source=source,
            epub_path=epub_path,
            audio_path=audio_path,
        )
    except JobCapacityError as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, str(exc), headers={"Retry-After": "5"}
        ) from exc


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: str, store: StoreDep) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job")
    return job


@router.get("/{job_id}/download")
async def download_job(job_id: str, store: StoreDep) -> FileResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job")
    path = store.result_path(job_id)
    if path is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A completed EPUB is not available")
    return FileResponse(path, media_type="application/epub+zip", filename=f"{job_id}.epub")


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
