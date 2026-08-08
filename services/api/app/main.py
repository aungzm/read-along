from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .events import EventBus
from .models import Stage
from .routers import health, jobs
from .store import JobStore


def create_app(*, stage_seconds: dict[Stage, float] | None = None) -> FastAPI:
    """Build the application.

    ``stage_seconds`` is injectable so tests can run the pipeline instantly.
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
