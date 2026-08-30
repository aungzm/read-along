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


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_job_id() -> str:
    return f"job_{uuid4().hex[:10]}"


class JobStore:
    """In-memory jobs, each processed by a background task."""

    def __init__(
        self,
        bus: EventBus,
        *,
        stage_seconds: dict[str, float] | None = None,
        epub_reader=inspect_epub,
        transcriber: Callable[[Path], tuple[TranscriptSegment, ...]] = transcribe_audio,
    ) -> None:
        self.bus = bus
        # Optional per-stage delay is used by tests to exercise cancellation.
        self._stage_seconds = stage_seconds or {}
        self._epub_reader = epub_reader
        self._transcriber = transcriber
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Where each job's uploaded files live. Kept off the wire model.
        self._epub_paths: dict[str, Path] = {}
        self._audio_paths: dict[str, Path] = {}

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

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
        try:
            self._apply(job, stage="extract")
            await self._pause("extract")
            await self._extract(job)
            epub_path = self._epub_paths[job_id]
            audio_path = self._audio_paths[job_id]
            sentences = await asyncio.to_thread(extract_sentences, epub_path)
            self._apply(job, progress=0.2, stage="transcribe")
            await self._pause("transcribe")
            transcript = await asyncio.to_thread(self._transcriber, audio_path)
            self._apply(job, progress=0.4, stage="align")
            await self._pause("align")
            matches = await asyncio.to_thread(locate_passages, sentences, transcript)
            timings = await asyncio.to_thread(align_sentences, audio_path, matches)
            report = review_alignment(sentences, timings)
            if report.status != "ready":
                raise ValueError(
                    f"Alignment {report.status}: {report.matched_sentences}/"
                    f"{report.total_sentences} sentences matched. {'; '.join(report.issues)}"
                )
            self._apply(job, progress=0.6, stage="build")
            await self._pause("build")
            audio_archive = f"OEBPS/audio/read-along{audio_path.suffix.lower()}"
            overlays = await asyncio.to_thread(
                build_overlays, timings, audio_archive, epub_path.parent / "overlays"
            )
            self._apply(job, progress=0.8, stage="package")
            await self._pause("package")
            await asyncio.to_thread(
                package_epub,
                epub_path,
                audio_path,
                sentences,
                overlays,
                epub_path.parent / "result.epub",
            )
        except asyncio.CancelledError:
            self._tasks.pop(job_id, None)
            raise
        except Exception as exc:
            self._apply(
                job,
                status="failed",
                stage=None,
                error=str(exc) or "Processing failed.",
            )
            self._finish(job, "failed")
            self._tasks.pop(job_id, None)
            return

        self._apply(job, status="succeeded", stage=None, progress=1.0)
        self._finish(job, "succeeded")
        self._tasks.pop(job_id, None)

    async def _pause(self, stage: str) -> None:
        await asyncio.sleep(self._stage_seconds.get(stage, 0))

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
