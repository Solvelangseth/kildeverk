"""Weather tools against recorded MET Norway responses."""

from __future__ import annotations

import httpx
import pytest

from kildeverk.context import build_context
from kildeverk.core.cache import ResponseCache
from kildeverk.core.errors import ToolError
from kildeverk.settings import Settings
from kildeverk.sources.met.models import FindStationsInput, ObservationsInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


# --- forecast -----------------------------------------------------------------


async def test_forecast_rounds_coordinates_and_flattens_steps(ctx, replay):
    result = await call(ctx, "weather_forecast", lat=60.3913, lon=5.3221, hours=24)
    data = result["data"]
    assert data["location"]["lat"] == 60.391 and data["location"]["lon"] == 5.322
    assert len(data["points"]) == 25  # hourly, both ends included
    first = data["points"][0]
    assert first["precipitation_hours"] == 1 and first["symbol"]
    assert isinstance(first["temperature_c"], float)
    [prov] = result["provenance"]
    assert prov["request"]["url"].endswith("compact?lat=60.391&lon=5.322")
    assert prov["licence"]["id"] == "CC-BY-4.0" and "MET Norway" in prov["citation"]
    assert "kildeverk/" in replay.requests[-1].headers["user-agent"]


async def test_forecast_needs_no_frost_credentials(replay):
    ctx = build_context(
        Settings(_env_file=None),
        client=httpx.AsyncClient(transport=replay),
        cache=ResponseCache(":memory:"),
    )
    result = await call(ctx, "weather_forecast", lat=60.3913, lon=5.3221, hours=1)
    assert result["data"]["points"]
    error = await fails(ctx, "weather_find_stations", name="Blindern")
    assert error["code"] == "NOT_CONFIGURED" and "KILDEVERK_FROST_CLIENT_ID" in error["message"]
    await ctx.aclose()


async def test_forecast_rejects_impossible_coordinates(ctx):
    assert (await fails(ctx, "weather_forecast", lat=95, lon=5))["code"] == "INVALID_ARGUMENT"


# --- stations -----------------------------------------------------------------


async def test_nearest_stations(ctx):
    result = await call(ctx, "weather_find_stations", lat=60.3913, lon=5.3221, limit=3)
    stations = result["data"]["stations"]
    assert len(stations) == 3
    assert [s["distance_km"] for s in stations] == sorted(s["distance_km"] for s in stations)
    assert all(s["valid_to"] is None for s in stations)
    assert stations[0]["municipality_code"] == "4601"
    [prov] = result["provenance"]
    assert prov["licence"]["id"] == "CC-BY-3.0-NO"
    assert "nearest%28POINT%285.322+60.391%29%29" in prov["request"]["url"]


async def test_stations_by_name(ctx):
    stations = (await call(ctx, "weather_find_stations", name="Blindern"))["data"]["stations"]
    assert "SN18700" in {s["id"] for s in stations}


def test_station_search_needs_one_way_to_search():
    with pytest.raises(ValueError, match="either lat and lon, or name"):
        FindStationsInput(lat=60.0, lon=5.0, name="Bergen")
    with pytest.raises(ValueError, match="both lat and lon"):
        FindStationsInput(lat=60.0)


async def test_station_elements_are_grouped(ctx):
    data = (
        await call(
            ctx, "weather_station_elements", station="SN50540", element_search="precipitation"
        )
    )["data"]
    names = [e["element"] for e in data["elements"]]
    assert names == sorted(names) and len(names) == len(set(names))
    assert all("precipitation" in name for name in names)
    daily = next(e for e in data["elements"] if e["element"] == "sum(precipitation_amount P1D)")
    assert daily["resolutions"] == ["P1D"] and daily["unit"] == "mm"


# --- observations -------------------------------------------------------------


async def test_observations_with_friendly_names_and_one_series_each(ctx):
    result = await call(
        ctx,
        "weather_observations",
        station="SN50540",
        elements=["daily_mean_temperature", "daily_precipitation"],
        start="2026-10-01",
        end="2026-10-08",
    )
    data = result["data"]
    assert data["elements"]["daily_precipitation"] == "sum(precipitation_amount P1D)"
    assert data["row_count"] == 14  # 7 days x 2 elements, no alternative series
    keys = [(r["time"], r["element"]) for r in data["rows"]]
    assert len(keys) == len(set(keys))
    rain = next(r for r in data["rows"] if r["element"] == "daily_precipitation")
    assert rain["unit"] == "mm" and rain["time_offset"] == "PT6H"
    url = result["provenance"][0]["request"]["url"]
    assert "timeoffsets=default" in url and "levels=default" in url
    assert "referencetime=2026-10-01T00%3A00%3A00Z%2F2026-10-08T00%3A00%3A00Z" in url


async def test_unknown_element_points_to_what_the_station_measures(ctx):
    error = await fails(
        ctx,
        "weather_observations",
        station="SN50540",
        elements=["nonsense"],
        start="2026-10-01",
        end="2026-10-04",
    )
    assert error["code"] == "INVALID_ARGUMENT"
    assert error["next_call"] == {
        "tool": "weather_station_elements",
        "arguments": {"station": "SN50540"},
    }


async def test_no_data_in_the_period_is_not_found_with_frosts_reason(ctx):
    error = await fails(
        ctx,
        "weather_observations",
        station="SN50540",
        elements=["temperature"],
        start="2030-10-01",
        end="2030-10-04",
    )
    assert error["code"] == "NOT_FOUND" and "No data found" in error["message"]


def test_observation_period_is_checked():
    with pytest.raises(ValueError, match="end must be after start"):
        ObservationsInput(
            station="SN18700", elements="temperature", start="2024-02-01", end="2024-01-01"
        )
    with pytest.raises(ValueError, match="ten years"):
        ObservationsInput(
            station="SN18700", elements="temperature", start="2000-01-01", end="2024-01-01"
        )
    assert ObservationsInput(
        station="SN18700", elements="temperature,snow_depth", start="2024-01-01", end="2024-01-02"
    ).elements == ["temperature", "snow_depth"]


async def test_rejected_credentials_are_not_configured(ctx):
    up = ctx.upstream("met_frost")
    up.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={}))
    )
    error = await fails(ctx, "weather_find_stations", name="Bergen")
    assert error["code"] == "NOT_CONFIGURED"
    await up.client.aclose()
