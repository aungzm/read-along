from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import uvicorn

from app.main import create_app

# Every request through httpx's ASGI transport runs the app in-process, which
# is fast but buffers streaming responses. Tests that need the event stream use
# `running_server` and a real listener instead.
FAST_STAGES = dict.fromkeys(("extract", "transcribe", "align", "build", "package"), 0.01)
SLOW_STAGES = dict.fromkeys(FAST_STAGES, 30.0)


def make_client(**kwargs: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app(**kwargs))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def wait_for_terminal(
    client: httpx.AsyncClient,
    job_id: str,
    timeout: float = 5.0,
) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    job: dict = {}

    while loop.time() < deadline:
        job = (await client.get(f"/api/jobs/{job_id}")).json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        await asyncio.sleep(0.02)

    raise AssertionError(f"job {job_id} never reached a terminal state: {job}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def running_server(**kwargs: object) -> AsyncIterator[str]:
    """Serve the app on a real port for the duration of the block."""
    config = uvicorn.Config(
        create_app(**kwargs),
        host="127.0.0.1",
        port=_free_port(),
        log_level="warning",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:
        raise RuntimeError("uvicorn did not start")

    try:
        yield f"http://127.0.0.1:{config.port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
