from __future__ import annotations

import pytest
from support import FAST_STAGES, SLOW_STAGES, make_client, wait_for_terminal

pytestmark = pytest.mark.anyio


async def test_create_runs_to_success() -> None:
    async with make_client(stage_seconds=FAST_STAGES) as client:
        created = await client.post("/api/jobs", json={"title": "Dune"})
        assert created.status_code == 201

        body = created.json()
        assert body["title"] == "Dune"
        assert body["status"] == "queued"

        job = await wait_for_terminal(client, body["jobId"])
        assert job["status"] == "succeeded"
        assert job["progress"] == 1.0

        listed = (await client.get("/api/jobs")).json()
        assert [item["jobId"] for item in listed] == [body["jobId"]]


async def test_empty_title_is_rejected() -> None:
    async with make_client(stage_seconds=FAST_STAGES) as client:
        response = await client.post("/api/jobs", json={"title": ""})

    assert response.status_code == 422


async def test_unknown_job_is_not_found() -> None:
    async with make_client(stage_seconds=FAST_STAGES) as client:
        missing = await client.get("/api/jobs/nope")
        cancel = await client.post("/api/jobs/nope/cancel")

    assert missing.status_code == 404
    assert cancel.status_code == 404


async def test_cancel_stops_a_running_job() -> None:
    async with make_client(stage_seconds=SLOW_STAGES) as client:
        created = await client.post("/api/jobs", json={"title": "Slow"})
        job_id = created.json()["jobId"]

        response = await client.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
