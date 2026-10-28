"""statistics_series: one statistic for one region over time, across the reforms."""

from __future__ import annotations

import pytest

from kildeverk.core.errors import ToolError
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def series(ctx, **arguments):
    return await OPS["statistics_series"].invoke(ctx, arguments)


async def test_ssb_summed_series_reaches_past_the_reforms(ctx, replay):
    result = await series(ctx, table_id="07459", region="Tromsø", from_year=2010)
    data = result["data"]
    assert data["region_code"] == "5501" and data["method"] == "summed_to_todays_borders"
    periods = [p["period"] for p in data["points"]]
    assert periods[0] == "2010" and len(periods) >= 16 and periods == sorted(periods)
    sent = [r for r in replay.requests if "/data" in r.url.path]
    assert "K-5501" in (sent[-1].content.decode() + str(sent[-1].url))


async def test_an_old_code_is_followed_to_today(ctx):
    result = await series(ctx, table_id="07459", region="1201", from_year=2015)
    assert result["data"]["region_code"] == "4601"
    assert "1201 is today 4601 Bergen." in result["notes"]


async def test_non_additive_measure_follows_renumberings_only(ctx):
    result = await series(
        ctx,
        table_id="11342",
        region="5501",
        measure="FolkeLandArealKm2",
        measure_kind="non_additive",
    )
    data = result["data"]
    assert data["method"] == "harmonised" and data["points"][0]["period"] == "2007"
    assert any("from 3 codes (1902, 5401, 5501)" in n for n in result["notes"])


async def test_additive_measure_is_rebuilt_from_the_regions_that_merged(ctx):
    result = await series(
        ctx,
        table_id="06913",
        region="Tromsø",
        measure="Levende",
        from_year=2015,
        measure_kind="additive",
    )
    data = result["data"]
    assert data["method"] == "harmonised" and data["points"][0]["period"] == "2015"
    assert all(p["value"] > 500 for p in data["points"] if p["value"] is not None)
    assert {p["source_id"] for p in result["provenance"]} == {"ssb_statbank", "ssb_klass"}


async def test_several_measures_need_a_choice(ctx):
    with pytest.raises(ToolError) as caught:
        await series(ctx, table_id="11342", region="5501")
    error = caught.value.body
    assert error.code == "AMBIGUOUS" and "FolkeLandArealKm2" in error.message
    assert error.next_call.tool == "statistics_series"


async def test_a_required_dimension_is_named(ctx):
    with pytest.raises(ToolError) as caught:
        await series(ctx, table_id="12558", region="5501", measure="AntHush")
    assert caught.value.body.code == "INVALID_ARGUMENT"
    assert "filters" in caught.value.body.message
