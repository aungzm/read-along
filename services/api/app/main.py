from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .events import EventBus
from .models import Stage
from .routers import health, jobs
from .store import JobStore


def create_app(
    *,
    stage_seconds: dict[Stage, float] | None = None,
    data_dir: Path | None = None,
) -> FastAPI:
    """Build the application.

    ``stage_seconds`` and ``data_dir`` are injectable so tests can run the
    pipeline instantly and keep uploads in a temporary directory.
    """

    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.store.aclose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )
    app.state.data_dir = Path(data_dir) if data_dir is not None else settings.data_dir
    app.state.store = JobStore(EventBus(), stage_seconds=stage_seconds)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")

    return app


app = create_app()
