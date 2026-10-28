"""A few real calls per source, to notice when an upstream changes. Not run in CI.

uv run pytest -m live
"""

from __future__ import annotations

import pytest

from kildeverk.context import build_context
from kildeverk.core.cache import ResponseCache
from kildeverk.settings import Settings
from kildeverk.sources.registry import operations

pytestmark = pytest.mark.live
OPS = {op.name: op for op in operations()}


@pytest.fixture
async def live():
    ctx = build_context(Settings(_env_file=None), cache=ResponseCache(":memory:"))
    yield ctx
    await ctx.aclose()


async def test_ssb_search_describe_and_fetch(live):
    found = await OPS["statistics_search_tables"].invoke(live, {"query": "population"})
    assert found["data"]["tables"]
    described = await OPS["statistics_describe_table"].invoke(live, {"table_id": "07459"})
    data = await OPS["statistics_get_data"].invoke(live, described["data"]["example_arguments"])
    assert data["data"]["row_count"] == 1
    assert isinstance(data["data"]["rows"][0]["value"], int)
