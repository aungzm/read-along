"""One interruptible subprocess per job, reused across its pipeline stages."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import signal
import subprocess
from multiprocessing.connection import Connection

from .config import get_settings


def _serve(connection: Connection, settings: dict) -> None:
    if os.name != "nt":
        os.setsid()
    # Spawned workers do not inherit in-memory configuration overrides. Supply
    # the same validated settings as the API, including archive size limits.
    for key, value in settings.items():
        name = f"READ_ALONG_{key.upper()}"
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = json.dumps(value) if isinstance(value, (list, dict)) else str(value)
    get_settings.cache_clear()
    try:
        while True:
            function, args, kwargs = connection.recv()
            try:
                result = function(*args, **kwargs)
            except Exception as exc:
                # Send a portable error rather than requiring exception classes
                # from optional libraries to be importable in the API process.
                connection.send((False, str(exc) or type(exc).__name__))
            else:
                connection.send((True, result))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


async def _drain(task: asyncio.Task) -> None:
    """Finish cleanup even when cancellation is requested more than once."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not task.cancelled():
        task.exception()


class ProcessWorker:
    def __init__(self) -> None:
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=_serve, args=(child, get_settings().model_dump(mode="json")), daemon=True
        )
        try:
            self.process.start()
        except BaseException:
            self.connection.close()
            raise
        finally:
            child.close()
        self._closing: asyncio.Task | None = None

    def _exchange(self, function, args, kwargs):
        try:
            self.connection.send((function, args, kwargs))
            return self.connection.recv()
        except (EOFError, BrokenPipeError, OSError):
            return False, "The processing worker exited unexpectedly."
        except Exception as exc:
            return False, str(exc) or type(exc).__name__

    async def run(self, function, *args, **kwargs):
        exchange = asyncio.create_task(asyncio.to_thread(self._exchange, function, args, kwargs))
        try:
            ok, result = await asyncio.shield(exchange)
            if not ok:
                raise RuntimeError(result)
            return result
        except asyncio.CancelledError:
            await self.aclose()
            await _drain(exchange)
            raise

    def _stop(self) -> None:
        try:
            if self.process.is_alive():
                if os.name == "nt":
                    # Include children such as Java/EPUBCheck. Only this job's
                    # owned process tree is targeted.
                    try:
                        subprocess.run(
                            ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                            capture_output=True,
                            timeout=5,
                            check=False,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                else:
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        # Cancellation may precede the child's setsid().
                        self.process.terminate()
                self.process.join(timeout=2)
                if self.process.is_alive():
                    if os.name != "nt":
                        try:
                            os.killpg(self.process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    self.process.kill()
                    self.process.join()
            else:
                self.process.join()
        finally:
            if os.name != "nt" and self.process.pid is not None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.connection.close()
            self.process.close()

    async def aclose(self) -> None:
        if self._closing is None:
            self._closing = asyncio.create_task(asyncio.to_thread(self._stop))
        await _drain(self._closing)
        self._closing.result()
