from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .epub import EpubError, inspect_epub
from .events import EventBus
from .models import STAGES, Book, Job, JobEvent, JobStatus, SourceFiles

# Wall-clock seconds per stage. Short enough to watch a job finish while
# developing, long enough that the progress UI has something to show. Extract
# does real work; the timings below still pace the remaining placeholder stages.
DEFAULT_STAGE_SECONDS: dict[str, float] = {
    "extract": 0.2,
    "transcribe": 4.0,
    "align": 3.0,
    "build": 1.5,
    "package": 1.0,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_job_id() -> str:
    return f"job_{uuid4().hex[:10]}"


class JobStore:
    """In-memory jobs, each advanced by a background task.

    The ``extract`` stage is real: it reads the uploaded EPUB's package
    document and records the book's metadata. ``transcribe``, ``align``,
    ``build`` and ``package`` still just walk a timer — they stand in for the
    alignment engine, which is not implemented yet.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        stage_seconds: dict[str, float] | None = None,
        tick_seconds: float = 0.2,
        epub_reader=inspect_epub,
    ) -> None:
        self.bus = bus
        self._stage_seconds = stage_seconds or DEFAULT_STAGE_SECONDS
        self._tick_seconds = max(tick_seconds, 0.001)
        self._epub_reader = epub_reader
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Where each job's uploaded files live. Kept off the wire model.
        self._epub_paths: dict[str, Path] = {}
        self._audio_paths: dict[str, Path] = {}

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def create(
        self,
        *,
        job_id: str,
        title: str,
        source: SourceFiles,
        epub_path: Path,
        audio_path: Path,
    ) -> Job:
        now = utcnow()
        job = Job(
            job_id=job_id,
            title=title,
            status="queued",
            source=source,
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.job_id] = job
        self._epub_paths[job.job_id] = epub_path
        self._audio_paths[job.job_id] = audio_path
        self.bus.publish(job.job_id, JobEvent(type="snapshot", job=job))
        self._tasks[job.job_id] = asyncio.create_task(self._run(job.job_id))
        return job

    async def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None

        task = self._tasks.pop(job_id, None)
        if task is not None:
            task.cancel()

        if job.status not in ("succeeded", "failed", "cancelled"):
            self._apply(job, status="cancelled")
            self._finish(job, "cancelled")
        return job

    async def aclose(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return

        self._apply(job, status="running")
        total = sum(self._stage_seconds[stage] for stage in STAGES)
        elapsed = 0.0

        try:
            self._apply(job, stage="extract")
            await asyncio.sleep(0)
            await self._extract(job)
            elapsed += self._stage_seconds["extract"]
            self._apply(job, progress=round(elapsed / total, 4))

            for stage in STAGES[1:]:
                seconds = self._stage_seconds[stage]
                self._apply(job, stage=stage)
                steps = max(1, round(seconds / self._tick_seconds))
                for step in range(1, steps + 1):
                    await asyncio.sleep(self._tick_seconds)
                    progress = (elapsed + seconds * (step / steps)) / total
                    self._apply(job, progress=round(progress, 4))
                elapsed += seconds
        except asyncio.CancelledError:
            self._tasks.pop(job_id, None)
            raise
        except Exception as exc:
            self._apply(
                job,
                status="failed",
                stage=None,
                error=str(exc) or "Extraction failed.",
            )
            self._finish(job, "failed")
            self._tasks.pop(job_id, None)
            return

        self._apply(job, status="succeeded", stage=None, progress=1.0)
        self._finish(job, "succeeded")
        self._tasks.pop(job_id, None)

    async def _extract(self, job: Job) -> None:
        path = self._epub_paths.get(job.job_id)
        if path is None:
            raise EpubError("The uploaded EPUB is no longer available.")

        info = await asyncio.to_thread(self._epub_reader, path, fallback_title=job.title)
        self._apply(
            job,
            title=info.title,
            book=Book(
                title=info.title,
                author=info.author,
                language=info.language,
                chapters=info.chapters,
                identifier=info.identifier,
            ),
        )

    def _apply(self, job: Job, **changes: object) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = utcnow()
        self.bus.publish(job.job_id, JobEvent(type="progress", job=job))

    def _finish(self, job: Job, status: JobStatus) -> None:
        self.bus.publish(job.job_id, JobEvent(type="done", job=job))
