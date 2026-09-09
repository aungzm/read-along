from __future__ import annotations

import asyncio
import io
import threading
import zipfile
from pathlib import Path

import httpx
import pytest
from starlette import formparsers
from support import (
    create_job,
    epub_bytes,
    fake_transcriber,
    make_client,
    upload_files,
    wait_for_terminal,
)

from app.config import Settings, get_settings
from app.epub import EpubError, inspect_epub, validate_archive
from app.events import EventBus
from app.main import create_app
from app.pipeline import extract_sentences, package_epub
from app.store import JobCapacityError, JobStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def configure(monkeypatch):
    def update(**values):
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), name, value)

    return update


async def test_oversized_content_length_rejected_before_body_read(
    tmp_path: Path, configure
) -> None:
    configure(max_request_bytes=200)

    async def body():
        raise AssertionError("The rejected body must not be read.")
        yield b""  # pragma: no cover

    async with make_client(tmp_path) as client:
        response = await client.post("/api/jobs", content=body(), headers={"Content-Length": "201"})
    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("length", [None, "1"])
async def test_streamed_limit_closes_partial_multipart_files(
    tmp_path: Path, configure, monkeypatch, length: str | None
) -> None:
    configure(max_request_bytes=200)
    opened = []
    original = formparsers.SpooledTemporaryFile

    def track(*args, **kwargs):
        file = original(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", track)

    async def body():
        yield (
            b'--test\r\nContent-Disposition: form-data; name="epub"; filename="book.epub"'
            b"\r\n\r\n" + b"a" * 40
        )
        yield b"b" * 200
        raise AssertionError("Reading must stop when the byte budget is exhausted.")

    headers = {"Content-Type": "multipart/form-data; boundary=test"}
    if length is not None:
        headers["Content-Length"] = length
    async with make_client(tmp_path) as client:
        response = await client.post("/api/jobs", content=body(), headers=headers)
        assert (await client.get("/api/jobs")).json() == []
    assert response.status_code == 413
    assert opened and all(file.closed for file in opened)
    assert list(tmp_path.iterdir()) == []


async def test_exact_request_limit_allows_valid_upload(tmp_path: Path, configure) -> None:
    request = httpx.Request("POST", "http://test/api/jobs", files=upload_files())
    body = request.read()
    configure(max_request_bytes=len(body))
    async with make_client(tmp_path) as client:
        response = await client.post("/api/jobs", content=body, headers=request.headers)
        assert response.status_code == 201
        assert (await wait_for_terminal(client, response.json()["jobId"]))["status"] == "succeeded"


async def test_upload_admission_is_bounded_and_slots_are_released(
    tmp_path: Path, configure
) -> None:
    configure(max_concurrent_uploads=1)
    started, release = asyncio.Event(), asyncio.Event()
    request = httpx.Request("POST", "http://test/api/jobs", files=upload_files())
    payload = request.read()

    async def body():
        started.set()
        await release.wait()
        yield payload

    async with make_client(tmp_path) as client:
        first = asyncio.create_task(
            client.post("/api/jobs", content=body(), headers=request.headers)
        )
        await asyncio.wait_for(started.wait(), 2)
        try:
            rejected = await create_job(client)
            assert rejected.status_code == 429
            assert rejected.headers["Retry-After"] == "5"
        finally:
            release.set()
        response = await first
        assert response.status_code == 201
        await wait_for_terminal(client, response.json()["jobId"])
        next_response = await create_job(client)
        assert next_response.status_code == 201
        await wait_for_terminal(client, next_response.json()["jobId"])


async def test_per_file_limit_still_applies(tmp_path: Path, configure) -> None:
    configure(max_upload_bytes=50)
    async with make_client(tmp_path) as client:
        response = await create_job(client, epub=b"a" * 100)
    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


async def test_failed_workspace_write_is_cleaned_up(tmp_path: Path, monkeypatch) -> None:
    from app.routers import jobs

    async def broken_save(upload, workspace, **kwargs):
        (workspace / "partial").write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(jobs, "_save_upload", broken_save)
    async with make_client(tmp_path) as client:
        with pytest.raises(OSError, match="disk full"):
            await create_job(client)
    assert list(tmp_path.iterdir()) == []


async def test_cancelled_workspace_write_is_cleaned_up(tmp_path: Path, monkeypatch) -> None:
    from app.routers import jobs

    async def cancelled_save(upload, workspace, **kwargs):
        (workspace / "partial").write_bytes(b"partial")
        raise asyncio.CancelledError

    monkeypatch.setattr(jobs, "_save_upload", cancelled_save)
    async with make_client(tmp_path) as client:
        with pytest.raises(asyncio.CancelledError):
            await create_job(client)
    assert list(tmp_path.iterdir()) == []


async def test_queue_race_rejection_cleans_uploaded_workspace(tmp_path: Path, monkeypatch) -> None:
    def full(*args, **kwargs):
        raise JobCapacityError("Queue filled while uploading.")

    monkeypatch.setattr(JobStore, "create", full)
    async with make_client(tmp_path) as client:
        response = await create_job(client)
    assert response.status_code == 429
    assert list(tmp_path.iterdir()) == []


async def test_archive_rejected_before_transcription(tmp_path: Path, configure) -> None:
    configure(max_archive_bytes=100)
    called = False

    def transcriber(_path):
        nonlocal called
        called = True
        return ()

    async with make_client(tmp_path, transcriber=transcriber) as client:
        response = await create_job(client)
        job = await wait_for_terminal(client, response.json()["jobId"])
    assert job["status"] == "failed"
    assert "expanded-size" in job["error"]
    assert not called


@pytest.mark.parametrize(
    "setting, value, message",
    [
        ("max_archive_bytes", 100, "total expanded-size"),
        ("max_archive_entry_bytes", 100, "entry exceeds"),
        ("max_archive_entries", 1, "too many"),
    ],
)
async def test_archive_limits_apply_before_reading_xml_or_packaging(
    tmp_path: Path, configure, setting: str, value: int, message: str
) -> None:
    path = tmp_path / "book.epub"
    path.write_bytes(epub_bytes())
    configure(**{setting: value})
    with pytest.raises(EpubError, match=message):
        inspect_epub(path)
    with pytest.raises(EpubError, match=message):
        extract_sentences(path)
    # Packaging independently revalidates input, even if earlier stages were bypassed.
    from app.pipeline import Sentence, SentenceTiming, build_overlays

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    sentence = Sentence("OEBPS/chapter-0.xhtml", "s1", "Chapter 0.", 0, 10)
    overlays = build_overlays(
        (SentenceTiming(sentence, 0, 1),), "OEBPS/audio/book.mp3", tmp_path / "stage"
    )
    with pytest.raises(EpubError, match=message):
        package_epub(path, audio, (sentence,), overlays, tmp_path / "result.epub")
    assert not (tmp_path / "result.epub").exists()


async def test_compressed_non_xml_members_count_toward_archive_budget(configure) -> None:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("one.bin", b"a" * 1000)
        archive.writestr("two.bin", b"b" * 1000)
    assert len(data.getvalue()) < 500
    configure(max_archive_bytes=1500, max_archive_entry_bytes=1100)
    with zipfile.ZipFile(data) as archive, pytest.raises(EpubError, match="total expanded-size"):
        validate_archive(archive)


async def test_archive_at_exact_limits_is_allowed(configure) -> None:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("one.bin", b"a" * 10)
    configure(max_archive_bytes=10, max_archive_entry_bytes=10, max_archive_entries=1)
    with zipfile.ZipFile(data) as archive:
        validate_archive(archive)


async def test_duplicate_archive_entries_are_rejected() -> None:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("one.bin", b"one")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("one.bin", b"two")
    with zipfile.ZipFile(data) as archive, pytest.raises(EpubError, match="duplicate"):
        validate_archive(archive)


async def test_job_queue_and_processing_remain_bounded_after_cancellation(
    tmp_path: Path, configure
) -> None:
    configure(max_concurrent_jobs=1, max_pending_jobs=2)
    started, release = threading.Event(), threading.Event()
    calls = []

    def transcriber(path):
        calls.append(path)
        if len(calls) == 1:
            started.set()
            if not release.wait(10):
                raise TimeoutError("test worker was not released")
        return fake_transcriber(path)

    app = create_app(data_dir=tmp_path, transcriber=transcriber)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            first_id = (await create_job(client)).json()["jobId"]
            assert await asyncio.to_thread(started.wait, 2)
            second_id = (await create_job(client)).json()["jobId"]
            await asyncio.sleep(0.02)
            assert (await client.get(f"/api/jobs/{second_id}")).json()["status"] == "queued"
            assert len(calls) == 1
            response = await create_job(client)
            assert response.status_code == 429
            assert len(list(tmp_path.iterdir())) == 2

            async def rejected_body():
                raise AssertionError("A full queue must reject before multipart parsing.")
                yield b""  # pragma: no cover

            assert (await client.post("/api/jobs", content=rejected_body())).status_code == 429
            cancelled = await client.post(f"/api/jobs/{first_id}/cancel")
            assert cancelled.json()["status"] == "cancelled"
            # Repeated cancellation must not free the worker slot either.
            await client.post(f"/api/jobs/{first_id}/cancel")
            await asyncio.sleep(0.02)
            assert len(calls) == 1
            assert not app.state.store.has_capacity()
            release.set()
            assert (await wait_for_terminal(client, second_id))["status"] == "succeeded"
            assert len(calls) == 2
            assert app.state.store.has_capacity()
        finally:
            release.set()
            await app.state.store.aclose()


async def test_store_capacity_is_rechecked_at_creation(tmp_path: Path) -> None:
    from app.models import SourceFiles

    store = JobStore(EventBus(), max_pending_jobs=1)
    args = dict(
        title="Book",
        source=SourceFiles(
            epub_name="book.epub", audio_name="audio.mp3", epub_bytes=1, audio_bytes=1
        ),
        epub_path=tmp_path / "book.epub",
        audio_path=tmp_path / "audio.mp3",
    )
    try:
        store.create(job_id="first", **args)
        with pytest.raises(JobCapacityError):
            store.create(job_id="second", **args)
        # Cancelling before _run starts must not leave a permanent queue entry.
        await store.cancel("first")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert store.has_capacity()
    finally:
        await store.aclose()


async def test_limits_require_positive_configuration() -> None:
    from pydantic import ValidationError

    for name in (
        "max_upload_bytes",
        "max_request_bytes",
        "max_concurrent_uploads",
        "max_concurrent_jobs",
        "max_pending_jobs",
        "max_archive_bytes",
        "max_archive_entry_bytes",
        "max_archive_entries",
    ):
        with pytest.raises(ValidationError):
            Settings(**{name: 0}, _env_file=None)
