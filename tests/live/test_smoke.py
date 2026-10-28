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


async def test_klass_history_and_a_reform_conversion(live):
    found = await OPS["regions_resolve"].invoke(live, {"query": "Bergen", "level": "municipality"})
    assert found["data"]["matches"][0]["code"] == "4601"
    result = await OPS["regions_harmonise"].invoke(
        live,
        {
            "level": "municipality",
            "target": "2020",
            "measure": "additive",
            "rows": [
                {"region": "1508", "period": "2024", "value": 1},
                {"region": "1580", "period": "2024", "value": 2},
            ],
        },
    )
    assert result["data"]["rows"][0] == {
        "region": "1507",
        "region_name": "Ålesund",
        "period": "2024",
        "value": 3.0,
        "method": "summed",
        "sources": ["1508", "1580"],
    }
