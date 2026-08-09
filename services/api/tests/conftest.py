from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run the async tests on asyncio; trio is not a dependency."""
    return "asyncio"
