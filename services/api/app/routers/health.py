from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..models import Health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(version=get_settings().version)
