"""Hydrology tools against recorded HydAPI responses."""

from __future__ import annotations

import httpx
import pytest

from kildeverk.context import build_context
from kildeverk.core.cache import ResponseCache
from kildeverk.core.errors import ToolError
from kildeverk.settings import Settings
from kildeverk.sources.nve_hydapi.models import FindStationsInput, ObservationsInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


async def test_station_by_name_with_series_and_floods(ctx, replay):
    result = await call(ctx, "water_find_stations", name="Bulken")
    station = result["data"]["stations"][0]
    assert station["id"] == "62.5.0" and station["municipality_code"] == "4621"
    assert station["active"] is True and station["catchment_km2"] > 1000
    discharge = next(s for s in station["series"] if s["parameter"] == 1001)
    assert discharge["alias"] == "discharge"
    assert discharge["resolutions"] == ["instantaneous", "hourly", "daily"]
    floods = station["flood_statistics"]
    assert floods["mean_annual"] < floods["return_10y"] < floods["return_50y"]
    [prov] = result["provenance"]
    assert prov["licence"]["id"] == "NLOD-2.0"
    assert prov["request"]["url"].endswith("Stations?Active=0&StationName=Bulken")
    assert replay.requests[-1].headers["x-api-key"] == "test-key"


async def test_stations_near_a_point_are_sorted_by_distance(ctx):
    result = await call(
        ctx, "water_find_stations", lat=60.63, lon=6.42, radius_km=15, parameter="discharge"
    )
    stations = result["data"]["stations"]
    distances = [s["distance_km"] for s in stations]
    assert stations and distances == sorted(distances) and distances[-1] <= 15
    assert all(any(series["parameter"] == 1001 for series in s["series"]) for s in stations)
    assert "Polygon=POLYGON" in result["provenance"][0]["request"]["url"]


async def test_daily_discharge_with_quality(ctx):
    result = await call(
        ctx,
        "water_observations",
        station="62.5.0",
        parameter="discharge",
        start="2026-10-01",
        end="2026-10-08",
    )
    data = result["data"]
    assert data["row_count"] == 7 and data["unit"] == "m³/s" and data["method"] == "Mean"
    assert data["parameter_name"] == "Discharge"
    assert {r["quality"] for r in data["rows"]} <= {
        "uncontrolled",
        "primary_controlled",
        "secondary_controlled",
    }
    url = result["provenance"][0]["request"]["url"]
    assert (
        "ResolutionTime=1440" in url
        and "ReferenceTime=2026-10-01T00%3A00%3A00Z%2F2026-10-08T00%3A00%3A00Z" in url
    )


async def test_latest_value_without_a_period(ctx):
    result = await call(
        ctx, "water_observations", station="62.5.0", parameter="water_level", resolution="hourly"
    )
    assert result["data"]["row_count"] == 1
    assert any("latest value" in note for note in result["notes"])


async def test_missing_series_points_to_the_station_listing(ctx):
    error = await fails(ctx, "water_observations", station="62.5.0", parameter="snow_depth")
    assert error["code"] == "NOT_FOUND"
    assert error["next_call"] == {"tool": "water_find_stations", "arguments": {"station": "62.5.0"}}


async def test_unknown_parameter_name_is_refused_before_any_request(ctx, replay):
    before = len(replay.requests)
    error = await fails(ctx, "water_observations", station="62.5.0", parameter="flow")
    assert error["code"] == "INVALID_ARGUMENT" and "discharge" in error["message"]
    assert len(replay.requests) == before


def test_inputs_are_checked():
    with pytest.raises(ValueError, match="give station, name"):
        FindStationsInput()
    with pytest.raises(ValueError, match="both start and end"):
        ObservationsInput(station="62.5.0", start="2024-01-01")
    with pytest.raises(ValueError):
        ObservationsInput(station="62-5-0")


async def test_without_a_key_the_tools_say_how_to_get_one(replay):
    ctx = build_context(
        Settings(_env_file=None),
        client=httpx.AsyncClient(transport=replay),
        cache=ResponseCache(":memory:"),
    )
    error = await fails(ctx, "water_find_stations", name="Bulken")
    assert error["code"] == "NOT_CONFIGURED" and "KILDEVERK_NVE_API_KEY" in error["message"]
    await ctx.aclose()
