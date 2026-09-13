from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .epub import EpubError, inspect_epub
from .events import EventBus
from .models import Book, Job, JobEvent, JobStatus, SourceFiles
from .pipeline import (
    TranscriptSegment,
    align_sentences,
    build_overlays,
    extract_sentences,
    locate_passages,
    package_epub,
    review_alignment,
    transcribe_audio,
)
from .worker import ProcessWorker


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_job_id() -> str:
    return f"job_{uuid4().hex[:10]}"


class JobCapacityError(Exception):
    """All running/queued job slots are occupied."""


class JobStore:
    """In-memory jobs, each processed by a background task."""

    def __init__(
        self,
        bus: EventBus,
        *,
        stage_seconds: dict[str, float] | None = None,
        epub_reader=inspect_epub,
        transcriber: Callable[[Path], tuple[TranscriptSegment, ...]] = transcribe_audio,
        max_concurrent_jobs: int = 1,
        max_pending_jobs: int = 4,
    ) -> None:
        self.bus = bus
        # Optional per-stage delay is used by tests to exercise cancellation.
        self._stage_seconds = stage_seconds or {}
        self._epub_reader = epub_reader
        self._transcriber = transcriber
        self._workers = asyncio.Semaphore(max_concurrent_jobs)
        self._max_pending_jobs = max_pending_jobs
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._process_workers: dict[str, ProcessWorker] = {}
        self._cancel_locks: dict[str, asyncio.Lock] = {}
        # Where each job's uploaded files live. Kept off the wire model.
        self._epub_paths: dict[str, Path] = {}
        self._audio_paths: dict[str, Path] = {}

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def has_capacity(self) -> bool:
        return len(self._tasks) < self._max_pending_jobs

    def result_path(self, job_id: str) -> Path | None:
        job = self.get(job_id)
        if job is None or job.status != "succeeded":
            return None
        path = self._epub_paths[job_id].parent / "result.epub"
        return path if path.is_file() else None

    def create(
        self,
        *,
        job_id: str,
        title: str,
        source: SourceFiles,
        epub_path: Path,
        audio_path: Path,
    ) -> Job:
        if not self.has_capacity():
            raise JobCapacityError("The processing queue is full. Try again shortly.")
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
        task = asyncio.create_task(self._run(job.job_id))
        self._tasks[job.job_id] = task
        # Also handles cancellation before the coroutine's first instruction.
        task.add_done_callback(lambda _task: self._tasks.pop(job.job_id, None))
        return job

    async def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None

        async with self._cancel_locks.setdefault(job_id, asyncio.Lock()):
            if job.status not in ("succeeded", "failed", "cancelled"):
                task = self._tasks.get(job_id)
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if job.status == "failed":
                    return job
                self._apply(job, status="cancelled", stage=None)
                self._finish(job, "cancelled")
        return job

    async def aclose(self) -> None:
        tasks = list(self._tasks.values())
        await asyncio.gather(*(self.cancel(job_id) for job_id in list(self._tasks)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job_id: str) -> None:
        try:
            async with self._workers:
                worker = ProcessWorker()
                self._process_workers[job_id] = worker
                try:
                    await self._process(job_id)
                finally:
                    await worker.aclose()
                    self._process_workers.pop(job_id, None)
        except asyncio.CancelledError:
            # The owned process has stopped and released its file handles.
            workspace = self._epub_paths[job_id].parent
            (workspace / ".result.partial.epub").unlink(missing_ok=True)
            (workspace / "result.epub").unlink(missing_ok=True)
            raise
        except Exception as exc:
            job = self._jobs[job_id]
            if job.status not in ("succeeded", "failed", "cancelled"):
                self._apply(job, status="failed", stage=None, error=str(exc))
                self._finish(job, "failed")
        finally:
            self._tasks.pop(job_id, None)

    async def _work(self, job_id: str, function, *args, **kwargs):
        return await self._process_workers[job_id].run(function, *args, **kwargs)

    async def _process(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return

        self._apply(job, status="running")
        try:
            self._apply(job, stage="extract")
            await self._pause("extract")
            await self._extract(job)
            epub_path = self._epub_paths[job_id]
            audio_path = self._audio_paths[job_id]
            sentences = await self._work(job_id, extract_sentences, epub_path)
            self._apply(job, progress=0.2, stage="transcribe")
            await self._pause("transcribe")
            transcript = await self._work(job_id, self._transcriber, audio_path)
            self._apply(job, progress=0.4, stage="align")
            await self._pause("align")
            matches = await self._work(job_id, locate_passages, sentences, transcript)
            timings = await self._work(job_id, align_sentences, audio_path, matches)
            report = review_alignment(sentences, timings)
            if report.status != "ready":
                raise ValueError(
                    f"Alignment {report.status}: {report.matched_sentences}/"
                    f"{report.total_sentences} sentences matched. {'; '.join(report.issues)}"
                )
            self._apply(job, progress=0.6, stage="build")
            await self._pause("build")
            audio_archive = f"OEBPS/audio/read-along{audio_path.suffix.lower()}"
            overlays = await self._work(
                job_id, build_overlays, timings, audio_archive, epub_path.parent / "overlays"
            )
            self._apply(job, progress=0.8, stage="package")
            await self._pause("package")
            await self._work(
                job_id,
                package_epub,
                epub_path,
                audio_path,
                sentences,
                overlays,
                epub_path.parent / "result.epub",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._apply(
                job,
                status="failed",
                stage=None,
                error=str(exc) or "Processing failed.",
            )
            self._finish(job, "failed")
            return

        self._apply(job, status="succeeded", stage=None, progress=1.0)
        self._finish(job, "succeeded")

    async def _pause(self, stage: str) -> None:
        await asyncio.sleep(self._stage_seconds.get(stage, 0))

    async def _extract(self, job: Job) -> None:
        path = self._epub_paths.get(job.job_id)
        if path is None:
            raise EpubError("The uploaded EPUB is no longer available.")

        info = await self._work(job.job_id, self._epub_reader, path, fallback_title=job.title)
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
