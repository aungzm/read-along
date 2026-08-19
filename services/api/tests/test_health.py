from __future__ import annotations

from pathlib import Path

import pytest
from support import FAST_STAGES, make_client

pytestmark = pytest.mark.anyio


async def test_health_reports_ok(tmp_path: Path) -> None:
    async with make_client(tmp_path, stage_seconds=FAST_STAGES) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": "0.0.0"}
