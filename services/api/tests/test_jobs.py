from __future__ import annotations

from pathlib import Path

import pytest
from support import (
    FAST_STAGES,
    SLOW_STAGES,
    create_job,
    epub_bytes,
    make_client,
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

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
