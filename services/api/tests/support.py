from __future__ import annotations

import asyncio
import io
import socket
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn

from app.main import create_app

# Every request through httpx's ASGI transport runs the app in-process, which
# is fast but buffers streaming responses. Tests that need the event stream use
# `running_server` and a real listener instead.
FAST_STAGES = dict.fromkeys(("extract", "transcribe", "align", "build", "package"), 0.01)
SLOW_STAGES = dict.fromkeys(FAST_STAGES, 30.0)

_CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def make_client(data_dir: Path, **kwargs: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app(data_dir=data_dir, **kwargs))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def epub_bytes(
    *,
    title: str = "The Wind in the Willows",
    author: str | None = "Kenneth Grahame",
    language: str | None = "en",
    chapters: int = 3,
) -> bytes:
    """Build a minimal but valid EPUB archive in memory."""

    metadata = [f"<dc:title>{title}</dc:title>"]
    if author is not None:
        metadata.append(f"<dc:creator>{author}</dc:creator>")
    if language is not None:
        metadata.append(f"<dc:language>{language}</dc:language>")
    metadata.append('<dc:identifier id="bookid">urn:uuid:test</dc:identifier>')
    itemrefs = "".join(f'<itemref idref="chapter-{index}"/>' for index in range(chapters))
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    {''.join(metadata)}
  </metadata>
  <manifest/>
  <spine>
    {itemrefs}
  </spine>
</package>
"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", _CONTAINER_XML)
        archive.writestr("OEBPS/content.opf", opf)
    return buffer.getvalue()


def upload_files(
    *,
    epub: bytes | None = None,
    epub_name: str = "book.epub",
    audio: bytes | None = None,
    audio_name: str = "audio.mp3",
) -> dict[str, tuple[str, bytes, str]]:
    return {
        "epub": (
            epub_name,
            epub if epub is not None else epub_bytes(),
            "application/epub+zip",
        ),
        "audio": (audio_name, audio if audio is not None else b"ID3-fake-audio", "audio/mpeg"),
    }


async def create_job(client: httpx.AsyncClient, **kwargs: object) -> httpx.Response:
    return await client.post("/api/jobs", files=upload_files(**kwargs))


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
async def running_server(data_dir: Path, **kwargs: object) -> AsyncIterator[str]:
    """Serve the app on a real port for the duration of the block."""
    config = uvicorn.Config(
        create_app(data_dir=data_dir, **kwargs),
        host="127.0.0.1",
        port=_free_port(),
        log_level="warning",
        # Long-lived SSE streams would otherwise hold shutdown open.
        timeout_graceful_shutdown=2,
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
