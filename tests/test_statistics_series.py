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
        table_id="11342",
        region="Tromsø",
        measure="Folkemengde",
        from_year=2015,
        measure_kind="additive",
    )
    data = result["data"]
    assert data["method"] == "harmonised" and data["points"][0]["period"] == "2015"
    assert all(70_000 < p["value"] < 90_000 for p in data["points"])
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


async def test_series_uses_the_hist_codelist_and_its_prefix(ctx, replay):
    result = await series(ctx, table_id="06913", region="Tromsø", measure="Levende", from_year=2015)
    assert result["data"]["method"] == "summed_to_todays_borders"
    assert result["data"]["points"][0]["period"] == "2015"


# --- statistics_rank ---------------------------------------------------------------


async def rank(ctx, **arguments):
    return await OPS["statistics_rank"].invoke(ctx, arguments)


async def test_rank_municipalities_by_value_with_norway_for_reference(ctx):
    result = await rank(ctx, table_id="07459", limit=5)
    data = result["data"]
    assert data["method"] == "summed_to_todays_borders" and data["total_regions"] > 350
    assert data["rows"][0]["code"] == "0301" and data["rows"][1]["code"] == "4601"
    assert [r["rank"] for r in data["rows"]] == [1, 2, 3, 4, 5]
    assert data["country"]["code"] == "0" and data["country"]["value"] > 5_000_000
    assert all(not r["code"].startswith(("K-", "K_")) for r in data["rows"])


async def test_rank_by_change_since_an_earlier_year(ctx):
    result = await rank(ctx, table_id="07459", compare_to="2015", limit=5)
    rows = result["data"]["rows"]
    assert result["data"]["ranked_by"] == "change_pct"
    assert [r["change_pct"] for r in rows] == sorted((r["change_pct"] for r in rows), reverse=True)
    assert rows[0]["change"] == rows[0]["value"] - rows[0]["earlier"]
    assert any("min_value" in n for n in result["notes"])


async def test_rank_counties_lowest_first(ctx):
    result = await rank(ctx, table_id="07459", level="county", order="lowest")
    rows = result["data"]["rows"]
    assert result["data"]["total_regions"] == 15
    assert [r["value"] for r in rows] == sorted(r["value"] for r in rows)


async def test_rank_skips_a_year_without_figures_and_small_regions(ctx):
    result = await rank(
        ctx, table_id="06913", measure="Levende", compare_to="2015", min_value=1000, limit=5
    )
    data = result["data"]
    assert data["period"] != "2026"
    assert any("has no figures yet" in n for n in result["notes"])
    assert all(r["value"] >= 1000 for r in data["rows"])
