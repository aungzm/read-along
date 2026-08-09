from __future__ import annotations

import httpx
import pytest
from support import FAST_STAGES, make_client, running_server

pytestmark = pytest.mark.anyio


async def test_unknown_job_stream_is_not_found() -> None:
    async with make_client(stage_seconds=FAST_STAGES) as client:
        response = await client.get("/api/jobs/nope/events")

    assert response.status_code == 404


async def test_event_stream_opens_with_a_snapshot() -> None:
    async with running_server(stage_seconds=FAST_STAGES) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            created = (await client.post("/api/jobs", json={"title": "Dune"})).json()

            async with client.stream("GET", f"/api/jobs/{created['jobId']}/events") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")

                lines: list[str] = []
                async for line in response.aiter_lines():
                    lines.append(line)
                    if len(lines) >= 4:
                        break

    text = "\n".join(lines)
    assert "event: snapshot" in text
    assert created["jobId"] in text
