"""MET's nowcast, ocean forecast and air quality forecast, against recordings."""

from __future__ import annotations

import datetime as dt
import itertools

import pytest

from kildeverk.core.errors import ToolError
from kildeverk.sources.met import products
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


# --- weather_nowcast ---------------------------------------------------------------


async def test_nowcast_says_when_rain_starts(ctx):
    result = await call(ctx, "weather_nowcast", lat=60.3913, lon=5.3221)
    data = result["data"]
    steps = data["steps"]
    assert len(steps) >= 20
    times = [dt.datetime.fromisoformat(s["time"]) for s in steps]
    assert all(b - a == dt.timedelta(minutes=5) for a, b in itertools.pairwise(times))
    assert data["radar_coverage"] == "ok" and data["now"]["temperature_c"] is not None
    rates = [s["precipitation_mm_per_h"] or 0 for s in steps]
    assert data["max_mm_per_h"] == max(rates)
    wet = [s["time"] for s, r in zip(steps, rates, strict=True) if r >= products.WET_MM_PER_H]
    if data["raining_now"]:
        assert data["rain_starts_at"] is None
    else:
        assert data["rain_starts_at"] == (wet[0] if wet else None)
    assert result["provenance"][0]["source_id"] == "met_nowcast"


async def test_nowcast_outside_the_nordic_area_points_to_the_forecast(ctx):
    error = await fails(ctx, "weather_nowcast", lat=78.22, lon=15.65)
    assert error["code"] == "INVALID_ARGUMENT" and "Nordic" in error["message"]
    assert error["next_call"]["tool"] == "weather_forecast"


# --- sea_forecast ------------------------------------------------------------------


async def test_sea_forecast_for_the_nearest_grid_point(ctx):
    result = await call(ctx, "sea_forecast", lat=60.1, lon=4.9, hours=24)
    data = result["data"]
    assert (
        abs(data["grid_point"]["lat"] - 60.1) < 0.05 and abs(data["grid_point"]["lon"] - 4.9) < 0.05
    )
    steps = data["steps"]
    assert len(steps) == 25  # the first step and 24 hours after it
    assert all(s["sea_temperature_c"] is not None for s in steps)
    assert data["highest_waves_m"] == max(s["wave_height_m"] for s in steps)
    assert any("significant wave height" in n for n in result["notes"])


async def test_no_sea_forecast_on_land(ctx):
    error = await fails(ctx, "sea_forecast", lat=61.5, lon=9.0)
    assert error["code"] == "NOT_FOUND" and "on land" in error["message"]


# --- air_quality_forecast ----------------------------------------------------------


@pytest.fixture
def recorded_now(monkeypatch):
    # The recordings were made on 2026-10-29 around 17:00 UTC.
    monkeypatch.setattr(products, "_now", lambda: dt.datetime(2026, 10, 29, 17, 20, tzinfo=dt.UTC))


async def test_air_quality_hour_by_hour_with_the_worst_hour_explained(ctx, recorded_now):
    result = await call(ctx, "air_quality_forecast", lat=59.9139, lon=10.7522)
    data = result["data"]
    assert data["area"]["area_class"] == "grunnkrets" and data["area"]["path"].startswith("Oslo/")
    hours = data["hours"]
    times = [h["time"] for h in hours]
    assert times == sorted(set(times))  # upstream repeats an hour and is out of order
    assert times[0] == "2026-10-29T17:00:00Z"
    for hour in hours:
        assert hour["level"] == products._level(hour["aqi"])[0]
        assert hour["dominant"] in {"NO2", "PM10", "PM2.5", "O3"}
    worst = data["worst"]
    assert worst["aqi"] == max(h["aqi"] for h in hours)
    assert worst["sources_pct"] and sum(worst["sources_pct"].values()) <= 101


async def test_air_quality_for_a_whole_municipality(ctx, recorded_now):
    result = await call(ctx, "air_quality_forecast", lat=63.4305, lon=10.3951, area="kommune")
    assert result["data"]["area"]["area_code"] == "5001"


async def test_air_quality_outside_norway(ctx):
    error = await fails(ctx, "air_quality_forecast", lat=55.0, lon=3.0)
    assert error["code"] == "INVALID_ARGUMENT" and "Norway only" in error["message"]


def test_levels_follow_mets_classes():
    assert [products._level(x)[0] for x in (1.0, 1.99, 2.0, 3.5, 4.0, 4.99)] == [
        "low",
        "low",
        "moderate",
        "high",
        "very high",
        "very high",
    ]


# --- weather_normals ---------------------------------------------------------------


@pytest.fixture
def recorded_today(monkeypatch):
    from kildeverk.sources.met import normals

    monkeypatch.setattr(normals, "_today", lambda: dt.date(2026, 10, 29))


async def test_normals_compared_with_this_year(ctx, recorded_today):
    result = await call(ctx, "weather_normals", station="SN18700", year=2026)
    data = result["data"]
    assert (data["period"], data["year"]) == ("1991/2020", 2026)
    assert data["year_normal_temperature_c"] is not None
    months = {m["month"]: m for m in data["months"]}
    assert sorted(months) == list(range(1, 13))
    september, october, november = months[9], months[10], months[11]
    assert september["complete"] is True and october["complete"] is False
    assert november["observed_temperature_c"] is None and november["complete"] is None
    assert september["temperature_anomaly_c"] == pytest.approx(
        september["observed_temperature_c"] - september["normal_temperature_c"], abs=0.05
    )
    assert september["precipitation_pct_of_normal"] == round(
        september["observed_precipitation_mm"] / september["normal_precipitation_mm"] * 100
    )
    assert any("not over" in n for n in result["notes"])
    assert [p["licence"]["id"] for p in result["provenance"]] == ["CC-BY-3.0-NO", "CC-BY-3.0-NO"]


async def test_an_older_normal_period(ctx, recorded_today):
    data = (await call(ctx, "weather_normals", station="SN50540", year=2025, period="1961/1990"))[
        "data"
    ]
    assert data["period"] == "1961/1990"
    assert all(m["complete"] is True for m in data["months"])


async def test_a_year_without_observations_keeps_the_normals(ctx, recorded_today):
    result = await call(ctx, "weather_normals", station="SN18700", year=1900)
    assert all(m["observed_temperature_c"] is None for m in result["data"]["months"])
    assert result["data"]["months"][0]["normal_temperature_c"] is not None
    assert any("no monthly temperature" in n for n in result["notes"])
    assert len(result["provenance"]) == 1


async def test_a_future_year_is_refused(ctx, recorded_today):
    error = await fails(ctx, "weather_normals", station="SN18700", year=2027)
    assert error["code"] == "INVALID_ARGUMENT"
