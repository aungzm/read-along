from __future__ import annotations

import pytest
from support import FAST_STAGES, make_client

pytestmark = pytest.mark.anyio


async def test_health_reports_ok() -> None:
    async with make_client(stage_seconds=FAST_STAGES) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": "0.0.0"}
