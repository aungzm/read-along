from __future__ import annotations

import asyncio
import multiprocessing
import os
from pathlib import Path

import httpx
import pytest
from support import (
    blocking_packager,
    blocking_transcriber,
    crashing_transcriber,
    create_job,
    fake_transcriber,
    launch_child,
    wait_for_terminal,
)

from app.main import create_app
from app.worker import ProcessWorker

pytestmark = pytest.mark.anyio


async def wait_for_file(path: Path) -> None:
    for _ in range(500):
        if path.exists() and path.stat().st_size:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"Worker did not create {path.name}.")


@pytest.mark.parametrize("stage", ["transcribe", "package"])
async def test_cancel_stops_real_worker_before_returning_and_removes_partial_output(
    tmp_path: Path, monkeypatch, stage: str
) -> None:
    if stage == "package":
        monkeypatch.setattr("app.store.package_epub", blocking_packager)
    app = create_app(
        data_dir=tmp_path,
        transcriber=blocking_transcriber if stage == "transcribe" else fake_transcriber,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            job_id = (await create_job(client)).json()["jobId"]
            workspace = tmp_path / job_id
            marker = workspace / ("transcriber.pid" if stage == "transcribe" else "packager.pid")
            await wait_for_file(marker)
            pid = int(marker.read_text())
            heartbeat = workspace / "heartbeat"
            await wait_for_file(heartbeat)
            responses = await asyncio.gather(
                client.post(f"/api/jobs/{job_id}/cancel"),
                client.post(f"/api/jobs/{job_id}/cancel"),
            )
            assert all(response.json()["status"] == "cancelled" for response in responses)
            assert all(response.json()["stage"] is None for response in responses)
            assert pid not in {process.pid for process in multiprocessing.active_children()}
            size = heartbeat.stat().st_size
            await asyncio.sleep(0.05)
            assert heartbeat.stat().st_size == size
            assert not (workspace / ".result.partial.epub").exists()
            assert not (workspace / "result.epub").exists()
            assert (workspace / "source.epub").exists()
            assert (workspace / "audio.mp3").exists()
            assert (await client.get(f"/api/jobs/{job_id}/download")).status_code == 409
            assert app.state.store.has_capacity()
        finally:
            await app.state.store.aclose()


async def test_shutdown_stops_worker_and_marks_job_cancelled(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, transcriber=blocking_transcriber)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            job_id = (await create_job(client)).json()["jobId"]
            marker = tmp_path / job_id / "transcriber.pid"
            await wait_for_file(marker)
            pid = int(marker.read_text())
            await asyncio.wait_for(app.state.store.aclose(), timeout=10)
            assert pid not in {process.pid for process in multiprocessing.active_children()}
            assert app.state.store.get(job_id).status == "cancelled"
            assert not app.state.store._tasks
        finally:
            await app.state.store.aclose()


async def test_unexpected_worker_exit_fails_job_without_hanging(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, transcriber=crashing_transcriber)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            job_id = (await create_job(client)).json()["jobId"]
            job = await wait_for_terminal(client, job_id)
            assert job["status"] == "failed"
            assert "worker exited unexpectedly" in job["error"]
        finally:
            await app.state.store.aclose()


async def test_worker_start_failure_fails_job(tmp_path: Path, monkeypatch) -> None:
    def broken_start():
        raise OSError("Process could not start.")

    monkeypatch.setattr("app.store.ProcessWorker", broken_start)
    app = create_app(data_dir=tmp_path, transcriber=fake_transcriber)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        job_id = (await create_job(client)).json()["jobId"]
        job = await wait_for_terminal(client, job_id)
        assert job["status"] == "failed"
        assert "Process could not start" in job["error"]


def process_is_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            assert kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return exit_code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Linux init may not yet have reaped an exited orphan.
    status = Path(f"/proc/{pid}/stat")
    return not (status.exists() and status.read_text().split(")", 1)[1].strip().startswith("Z"))


async def test_cancellation_terminates_worker_subprocess_tree(tmp_path: Path) -> None:
    worker = ProcessWorker()
    task = asyncio.create_task(worker.run(launch_child, tmp_path))
    try:
        await wait_for_file(tmp_path / "child.pid")
        pid = int((tmp_path / "child.pid").read_text())
        assert process_is_running(pid)
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not process_is_running(pid)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await worker.aclose()
