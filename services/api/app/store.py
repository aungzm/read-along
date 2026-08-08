from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from .events import EventBus
from .models import STAGES, Job, JobCreate, JobEvent, JobStatus

# Wall-clock seconds per stage. Short enough to watch a job finish while
# developing, long enough that the progress UI has something to show.
DEFAULT_STAGE_SECONDS: dict[str, float] = {
    "extract": 1.5,
    "transcribe": 4.0,
    "align": 3.0,
    "build": 1.5,
    "package": 1.0,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobStore:
    """In-memory jobs, each advanced by a background task.

    This stands in for the alignment engine. It walks ``STAGES`` on a timer and
    publishes progress so the frontend has a live job to render; no EPUB is
    parsed and no audio is transcribed.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        stage_seconds: dict[str, float] | None = None,
        tick_seconds: float = 0.2,
    ) -> None:
        self.bus = bus
        self._stage_seconds = stage_seconds or DEFAULT_STAGE_SECONDS
        self._tick_seconds = max(tick_seconds, 0.001)
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def create(self, payload: JobCreate) -> Job:
        now = utcnow()
        job = Job(
            job_id=f"job_{uuid4().hex[:10]}",
            title=payload.title,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.job_id] = job
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
            for stage in STAGES:
                seconds = self._stage_seconds[stage]
                self._apply(job, stage=stage)
                steps = max(1, round(seconds / self._tick_seconds))
                for step in range(1, steps + 1):
                    await asyncio.sleep(self._tick_seconds)
                    progress = (elapsed + seconds * (step / steps)) / total
                    self._apply(job, progress=round(progress, 4))
                elapsed += seconds
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(job_id, None)

        self._apply(job, status="succeeded", stage=None, progress=1.0)
        self._finish(job, "succeeded")

    def _apply(self, job: Job, **changes: object) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = utcnow()
        self.bus.publish(job.job_id, JobEvent(type="progress", job=job))

    def _finish(self, job: Job, status: JobStatus) -> None:
        self.bus.publish(job.job_id, JobEvent(type="done", job=job))
