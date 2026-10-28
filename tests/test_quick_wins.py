"""MetAlerts, municipality at a point, sea level and reservoir fill, against recordings."""

from __future__ import annotations

from itertools import pairwise

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.kartverket_sea.ops import SeaLevelInput
from kildeverk.sources.met.alerts import WarningsInput
from kildeverk.sources.nve_reservoirs.ops import ReservoirsInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


# --- weather_warnings --------------------------------------------------------------


async def test_archive_month_keeps_the_latest_revision_and_the_peak_level(ctx):
    result = await call(ctx, "weather_warnings", month="2023-08", min_level=3)
    warnings = result["data"]["warnings"]
    assert [w["highest_level"] for w in warnings] == sorted(
        (w["highest_level"] for w in warnings), reverse=True
    )
    hans = [w for w in warnings if w["highest_level"] == 4]
    assert hans and all(w["valid_from"].startswith("2023-08-07") for w in hans)
    # One storm-Hans warning was eased from red to orange in its last revision.
    assert any(w["level"] < w["highest_level"] for w in hans)
    keys = [(w["event"], w["area"], w["valid_from"]) for w in warnings]
    assert len(keys) == len(set(keys))
    assert any("earlier revisions" in n for n in result["notes"])
    assert result["provenance"][0]["licence"]["id"] == "CC-BY-4.0"


async def test_warnings_for_a_county_and_a_point(ctx):
    county = await call(ctx, "weather_warnings", month="2023-08", county="03")
    assert all("03" in w["counties"] for w in county["data"]["warnings"])
    point = await call(ctx, "weather_warnings", month="2023-08", lat=60.17, lon=10.25, min_level=1)
    assert point["data"]["total_matches"] > 0
    assert "lat=60.17" in point["provenance"][0]["request"]["url"]


async def test_no_matching_warning_says_so(ctx):
    result = await call(ctx, "weather_warnings", month="2023-08", domain="marine", min_level=4)
    assert result["data"]["warnings"] == [] and "No weather warning" in result["notes"][0]


def test_warning_input_rules():
    with pytest.raises(ValidationError):
        WarningsInput(lat=60.0)
    with pytest.raises(ValidationError):
        WarningsInput(month="2023-13")


# --- regions_at_point --------------------------------------------------------------


async def test_point_to_municipality_and_county(ctx):
    result = await call(ctx, "regions_at_point", lat=60.39, lon=5.32)
    assert result["data"] == {
        "municipality_code": "4601",
        "municipality": "Bergen",
        "county_code": "46",
        "county": "Vestland",
        "at_date": None,
    }


async def test_sea_territory_belongs_to_a_municipality(ctx):
    result = await call(ctx, "regions_at_point", lat=59.0, lon=5.0)
    assert result["data"]["municipality"] == "Karmøy"


async def test_far_out_at_sea_is_not_found(ctx):
    error = await fails(ctx, "regions_at_point", lat=66.0, lon=1.0)
    assert error["code"] == "NOT_FOUND" and error["next_call"]["tool"] == "places_search"


# --- sea_level ---------------------------------------------------------------------


async def test_water_level_at_a_gauge(ctx):
    result = await call(
        ctx, "sea_level", lat=60.396, lon=5.32, start="2026-10-27T00:00", end="2026-10-27T06:00"
    )
    data = result["data"]
    assert data["location"]["gauge"] == "BGO" and data["reference"] == "chart_datum"
    series = {s["type"]: s for s in data["series"]}
    assert {"observation", "prediction", "weathereffect"} <= set(series)
    obs, pre, weather = (
        series[t]["points"][0]["cm"] for t in ("observation", "prediction", "weathereffect")
    )
    assert obs == pytest.approx(pre + weather, abs=1)
    assert series["observation"]["points"][0]["time"] == "2026-10-27T00:00:00+01:00"


async def test_summer_time_start_is_honoured(ctx, replay):
    result = await call(
        ctx,
        "sea_level",
        lat=59.91,
        lon=10.73,
        reference="mean_sea_level",
        start="2026-10-01T00:00",
        end="2026-10-01T03:00",
    )
    first = result["data"]["series"][0]["points"][0]["time"]
    assert first == "2026-10-01T00:00:00+02:00"
    assert "fromtime=2026-09-30T23%3A00" in str(replay.requests[-1].url)


async def test_tide_table_for_a_station(ctx):
    result = await call(
        ctx,
        "sea_level",
        station="BGO",
        kind="tide_table",
        start="2026-10-27T00:00",
        end="2026-10-29T00:00",
    )
    tides = result["data"]["tides"]
    assert len(tides) >= 7 and {t["kind"] for t in tides} == {"high", "low"}
    assert all(a["kind"] != b["kind"] for a, b in pairwise(tides))


async def test_modelled_point_away_from_a_gauge(ctx):
    result = await call(
        ctx, "sea_level", lat=63.0, lon=7.5, start="2026-10-27T00:00", end="2026-10-27T03:00"
    )
    assert result["data"]["location"]["gauge"] == "KSU"
    assert "height factor" in result["data"]["location"]["description"]


async def test_inland_and_unknown_gauge_are_not_found(ctx):
    inland = await fails(ctx, "sea_level", lat=61.5, lon=9.0, start="2026-10-27T00:00")
    assert inland["code"] == "NOT_FOUND" and "too far away from the coast" in inland["message"]
    unknown = await fails(ctx, "sea_level", station="XXX", start="2026-10-27T00:00")
    assert unknown["code"] == "NOT_FOUND"


def test_sea_level_input_rules():
    with pytest.raises(ValidationError):
        SeaLevelInput()
    with pytest.raises(ValidationError):
        SeaLevelInput(station="BGO", lat=60, lon=5)
    with pytest.raises(ValidationError):
        SeaLevelInput(station="BGO", start="2026-01-01T00:00", end="2026-03-01T00:00")


# --- energy_reservoirs -------------------------------------------------------------


async def test_latest_week_with_the_normal_range(ctx):
    result = await call(ctx, "energy_reservoirs")
    data = result["data"]
    assert [r["area"] for r in data["rows"]] == ["NO", "NO1", "NO2", "NO3", "NO4", "NO5"]
    norway = data["rows"][0]
    assert norway["fill_twh"] == pytest.approx(
        norway["capacity_twh"] * norway["fill_pct"] / 100, rel=1e-3
    )
    normal = norway["normal"]
    assert normal["min_pct"] <= normal["median_pct"] <= normal["max_pct"]
    assert data["next_publication"] is not None
    assert len(result["provenance"]) == 2


async def test_a_year_of_weeks_for_one_area(ctx):
    result = await call(ctx, "energy_reservoirs", areas=["NO2"], from_year=2022, to_year=2022)
    rows = result["data"]["rows"]
    assert len(rows) == 52 and {r["year"] for r in rows} == {2022}
    assert [r["week"] for r in rows] == list(range(1, 53))
    assert result["data"]["next_publication"] is None


def test_reservoir_input_rules():
    with pytest.raises(ValidationError):
        ReservoirsInput(areas=["NO6"])
    with pytest.raises(ValidationError):
        ReservoirsInput(to_year=2020)


async def test_point_on_a_past_date_follows_klass_back(ctx):
    result = await call(ctx, "regions_at_point", lat=69.65, lon=18.96, date="2019-06-01")
    then = result["data"]["at_date"]
    assert result["data"]["municipality_code"] == "5501"
    assert then["certain"] is True
    assert then["municipalities"] == [{"code": "1902", "name": "Tromsø"}]
    assert [c["code"] for c in then["counties"]] == ["19"]
    assert "ssb_klass" in {p["source_id"] for p in result["provenance"]}


async def test_a_merged_municipality_gives_candidates_not_a_guess(ctx):
    result = await call(ctx, "regions_at_point", lat=60.36, lon=5.0, date="2019-06-01")
    then = result["data"]["at_date"]
    assert then["certain"] is False
    assert {m["name"] for m in then["municipalities"]} == {"Sund", "Fjell", "Øygarden"}
    assert [c["code"] for c in then["counties"]] == ["12"]
    assert any("cannot say which" in n for n in result["notes"])


async def test_past_date_must_be_within_klass_history(ctx):
    error = await fails(ctx, "regions_at_point", lat=60.39, lon=5.32, date="1950-01-01")
    assert error["code"] == "INVALID_ARGUMENT"
