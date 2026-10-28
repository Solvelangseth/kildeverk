"""Flood, landslide and avalanche warnings against recorded Varsom responses."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.nve_varsom.models import AvalancheInput, FloodLandslideInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}
STORM_HANS = {"start": "2023-08-08", "end": "2023-08-09"}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def test_nationwide_warnings_during_storm_hans(ctx):
    result = await call(ctx, "hazards_flood_landslide", **STORM_HANS)
    warnings = result["data"]["warnings"]
    top = warnings[0]
    assert top["level"] == 4 and top["level_name"] == "red"
    assert {w["kind"] for w in warnings} == {"flood", "landslide"}
    assert [w["level"] for w in warnings] == sorted((w["level"] for w in warnings), reverse=True)
    assert top["valid_from"] == "2023-08-08T07:00:00+02:00"
    assert "3305" in {m["code"] for m in top["municipalities"]}
    assert len(result["provenance"]) == 2
    assert {p["licence"]["id"] for p in result["provenance"]} == {"NLOD-2.0"}
    assert result["provenance"][0]["request"]["url"].endswith(
        "/api/Warning/2/2023-08-08/2023-08-09"
    )


async def test_one_municipality_with_texts_and_causes(ctx):
    result = await call(
        ctx, "hazards_flood_landslide", municipality="3305", min_level=1, **STORM_HANS
    )
    flood = next(w for w in result["data"]["warnings"] if w["kind"] == "flood")
    assert flood["municipalities"] == [{"code": "3305", "name": "Ringerike"}]
    assert flood["warning"] and flood["advice"] and flood["consequences"]
    assert "Heavy rainfall" in flood["causes"]


async def test_a_county_query_merges_one_warning_across_municipalities(ctx):
    result = await call(
        ctx,
        "hazards_flood_landslide",
        county="34",
        kinds=["landslide"],
        start="2023-08-08",
        end="2023-08-08",
    )
    warnings = result["data"]["warnings"]
    ids = [w["id"] for w in warnings]
    assert len(ids) == len(set(ids))
    assert sum(len(w["municipalities"]) for w in warnings) > len(warnings)


async def test_a_quiet_day_is_an_empty_result_with_a_note(ctx):
    result = await call(ctx, "hazards_flood_landslide", municipality="4621", start="2026-10-01")
    assert result["data"]["warnings"] == []
    assert "No flood or landslide warning" in result["notes"][0]


def test_flood_input_rules():
    with pytest.raises(ValidationError):
        FloodLandslideInput(municipality="3305", county="33")
    with pytest.raises(ValidationError):
        FloodLandslideInput(start="2023-01-01", end="2023-03-01")
    with pytest.raises(ValidationError):
        FloodLandslideInput(end="2023-01-01")


async def test_avalanche_region_in_detail(ctx):
    result = await call(ctx, "hazards_avalanche", region=3011, start="2026-03-10")
    [forecast] = result["data"]["forecasts"]
    assert forecast["region"] == "Tromsø" and forecast["date"] == "2026-03-10"
    assert forecast["level"] == 2 and forecast["level_name"] == "moderate"
    problem = forecast["problems"][0]
    assert problem["aspects"] == ["N", "NE", "E", "SE", "S"]
    assert problem["heights"] == "above 400 m"
    assert forecast["advice"] and forecast["danger_assessment"]


async def test_avalanche_by_point_finds_the_region(ctx):
    result = await call(ctx, "hazards_avalanche", lat=69.65, lon=18.96, start="2026-03-10")
    assert result["data"]["forecasts"][0]["region_id"] == 3011


async def test_avalanche_summary_lists_every_region_highest_first(ctx):
    result = await call(ctx, "hazards_avalanche", start="2026-03-10")
    forecasts = result["data"]["forecasts"]
    assert len(forecasts) == 46
    levels = [f["level"] for f in forecasts]
    assert levels == sorted(levels, reverse=True) and levels[0] >= 2
    assert all(f["problems"] == [] for f in forecasts)


async def test_unknown_region_points_to_the_summary(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, "hazards_avalanche", region=3999, start="2026-03-10")
    error = caught.value.envelope()["error"]
    assert error["code"] == "NOT_FOUND" and error["next_call"] == {
        "tool": "hazards_avalanche",
        "arguments": {},
    }


async def test_out_of_season_says_so(ctx):
    result = await call(ctx, "hazards_avalanche", region=3011, start="2026-10-01")
    assert result["data"]["forecasts"][0]["level_name"] == "no rating"
    assert any("December to June" in n for n in result["notes"])


def test_avalanche_input_rules():
    with pytest.raises(ValidationError):
        AvalancheInput(region=3011, lat=69.6, lon=18.9)
    with pytest.raises(ValidationError):
        AvalancheInput(lat=69.6)
