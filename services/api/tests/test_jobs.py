from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from support import (
    FAST_STAGES,
    SLOW_STAGES,
    create_job,
    empty_transcriber,
    epub_bytes,
    make_client,
    unavailable_transcriber,
    upload_files,
    wait_for_terminal,
)

pytestmark = pytest.mark.anyio


async def test_create_extracts_the_epub(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=FAST_STAGES) as client:
        created = await create_job(client)
        assert created.status_code == 201

        body = created.json()
        # Before the extract stage runs, the title falls back to the file name.
        assert body["status"] == "queued"
        assert body["title"] == "book"
        assert body["source"]["epubName"] == "book.epub"
        assert body["book"] is None

        job = await wait_for_terminal(client, body["jobId"])
        assert job["status"] == "succeeded"
        assert job["progress"] == 1.0
        # Extract is real: metadata comes back from the package document.
        assert job["title"] == "The Wind in the Willows"
        assert job["book"] == {
            "title": "The Wind in the Willows",
            "author": "Kenneth Grahame",
            "language": "en",
            "chapters": 3,
            "identifier": "urn:uuid:test",
        }

        listed = (await client.get("/api/jobs")).json()
        assert [item["jobId"] for item in listed] == [body["jobId"]]


async def test_unreadable_epub_fails_the_job(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=FAST_STAGES) as client:
        created = await create_job(client, epub=b"this is not a zip archive")
        job = await wait_for_terminal(client, created.json()["jobId"])

    assert job["status"] == "failed"
    assert "zip" in job["error"].lower()


async def test_wrong_file_type_is_rejected(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=FAST_STAGES) as client:
        response = await client.post("/api/jobs", files=upload_files(epub_name="book.pdf"))

    assert response.status_code == 400
    assert "epub" in response.json()["detail"].lower()


async def test_unsupported_epub_audio_is_rejected(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.post("/api/jobs", files=upload_files(audio_name="book.flac"))

    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"].lower()


async def test_missing_files_are_rejected(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=FAST_STAGES) as client:
        response = await client.post(
            "/api/jobs",
            files={"epub": ("book.epub", epub_bytes(), "application/epub+zip")},
        )

    assert response.status_code == 422


async def test_unknown_job_is_not_found(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=FAST_STAGES) as client:
        missing = await client.get("/api/jobs/nope")
        cancel = await client.post("/api/jobs/nope/cancel")

    assert missing.status_code == 404
    assert cancel.status_code == 404


async def test_cancel_stops_a_running_job(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=SLOW_STAGES) as client:
        created = await create_job(client)
        job_id = created.json()["jobId"]

        response = await client.post(f"/api/jobs/{job_id}/cancel")
        download = await client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert download.status_code == 409


async def test_completed_job_downloads_a_synced_epub(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        job_id = (await create_job(client)).json()["jobId"]
        assert (await client.get(f"/api/jobs/{job_id}/download")).status_code == 409
        job = await wait_for_terminal(client, job_id)
        response = await client.get(f"/api/jobs/{job_id}/download")

    assert job["status"] == "succeeded"
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "OEBPS/chapter-0.smil" in archive.namelist()
        assert "OEBPS/audio/read-along.mp3" in archive.namelist()
        package = archive.read("OEBPS/content.opf")
        assert b'media-overlay="ra-overlay-' in package
        assert b"<" in archive.read("OEBPS/chapter-0.xhtml")


async def test_incomplete_alignment_never_offers_download(tmp_path: Path) -> None:
    async with make_client(tmp_path, transcriber=empty_transcriber) as client:
        job_id = (await create_job(client)).json()["jobId"]
        job = await wait_for_terminal(client, job_id)
        response = await client.get(f"/api/jobs/{job_id}/download")

    assert job["status"] == "failed"
    assert "0/3 sentences matched" in job["error"]
    assert response.status_code == 409


async def test_unmatched_table_text_prevents_false_full_coverage(tmp_path: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(epub_bytes())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["OEBPS/chapter-0.xhtml"] = parts["OEBPS/chapter-0.xhtml"].replace(
        b"</body>", b"<table><tr><td>Unspoken table text.</td></tr></table></body>"
    )
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    async with make_client(tmp_path) as client:
        job_id = (await create_job(client, epub=data.getvalue())).json()["jobId"]
        job = await wait_for_terminal(client, job_id)
        response = await client.get(f"/api/jobs/{job_id}/download")
    assert job["status"] == "failed"
    assert "3/4 sentences matched" in job["error"]
    assert response.status_code == 409


async def test_transcription_error_fails_the_job(tmp_path: Path) -> None:
    async with make_client(tmp_path, transcriber=unavailable_transcriber) as client:
        job_id = (await create_job(client)).json()["jobId"]
        job = await wait_for_terminal(client, job_id)

    assert job["status"] == "failed"
    assert "optional dependency" in job["error"]
