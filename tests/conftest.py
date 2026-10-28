from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from kildeverk.context import Context, build_context
from kildeverk.core.cache import ResponseCache
from kildeverk.settings import Settings
from kildeverk.testing import ReplayTransport

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def replay() -> ReplayTransport:
    return ReplayTransport(*sorted(FIXTURES.glob("*/cassette.json")))


@pytest.fixture
async def ctx(replay: ReplayTransport) -> AsyncIterator[Context]:
    context = build_context(
        # Placeholder credentials: replayed requests never reach Frost or HydAPI.
        Settings(_env_file=None, frost_client_id="test-client", nve_api_key="test-key"),
        client=httpx.AsyncClient(transport=replay),
        cache=ResponseCache(":memory:"),
    )
    yield context
    await context.aclose()
