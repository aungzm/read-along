from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from support import FAST_STAGES, SLOW_STAGES, create_job, make_client, running_server

pytestmark = pytest.mark.anyio


async def test_unknown_job_stream_is_not_found(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=FAST_STAGES) as client:
        response = await client.get("/api/jobs/nope/events")

    assert response.status_code == 404


async def test_event_stream_opens_with_a_snapshot(tmp_path: Path) -> None:
    # Slow stages keep the job alive while the stream is read. Cancelling it
    # publishes a `done` event, which closes the stream cleanly.
    async with running_server(tmp_path, stage_seconds=SLOW_STAGES) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            created = (await create_job(client)).json()
            job_id = created["jobId"]

            async with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")

                lines: list[str] = []
                cancelled = False
                async for line in response.aiter_lines():
                    lines.append(line)
                    if line == "event: snapshot" and not cancelled:
                        await client.post(f"/api/jobs/{job_id}/cancel")
                        cancelled = True
                    if line == "event: done":
                        break

    text = "\n".join(lines)
    assert "event: snapshot" in text
    assert "event: done" in text
    assert job_id in text
