"""place_overview combines other tools; parts that fail become notes."""

from __future__ import annotations

import pytest

from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.sources import composite
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


def _prov(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "source_name": source_id,
        "publisher": "p",
        "licence": {"id": "NLOD-2.0", "name": "NLOD", "url": "https://data.norge.no/nlod/en/2.0"},
        "request": {"method": "GET", "url": f"https://example.test/{source_id}", "body": None},
        "retrieved_at": "2026-10-28T12:00:00Z",
        "cache": {"hit": False, "age_s": 0},
        "citation": "c",
    }


PARTS = {
    "regions_at_point": {
        "data": {
            "municipality_code": "4601",
            "municipality": "Bergen",
            "county_code": "46",
            "county": "Vestland",
        },
        "provenance": [_prov("kartverket")],
    },
    "terrain_elevation": {
        "data": {"points": [{"elevation_m": 4.07}]},
        "provenance": [_prov("kartverket")],
    },
    "weather_forecast": {
        "data": {
            "points": [
                {
                    "time": "2026-10-28T14:00:00Z",
                    "temperature_c": 11.2,
                    "wind_speed_ms": 4.3,
                    "symbol": "rain",
                    "precipitation_mm": 1.5,
                },
                {
                    "time": "2026-10-28T15:00:00Z",
                    "temperature_c": 10.2,
                    "wind_speed_ms": 5.0,
                    "symbol": "rain",
                    "precipitation_mm": 1.2,
                },
            ]
        },
        "provenance": [_prov("met_locationforecast")],
    },
    "weather_warnings": {
        "data": {
            "warnings": [
                {"level_name": "yellow", "event": "Gale", "valid_to": "2026-10-29T13:00:00+00:00"}
            ]
        },
        "provenance": [_prov("met_metalerts")],
    },
    "transit_find_stops": {
        "data": {
            "stops": [
                {
                    "id": "NSR:StopPlace:30853",
                    "name": "Olav Kyrres gate",
                    "distance_km": 0.14,
                    "modes": ["bus"],
                }
            ]
        },
        "provenance": [_prov("entur_geocoder")],
    },
    "places_search": {
        "data": {"places": [{"name": "Nygårdsparken", "type": "Park", "distance_m": 874.0}]},
        "provenance": [_prov("kartverket")],
    },
    "hazards_flood_landslide": {
        "data": {
            "warnings": [
                {
                    "kind": "flood",
                    "level_name": "yellow",
                    "title": "Flood warning yellow level",
                    "valid_to": "2026-10-29T07:00:00+01:00",
                }
            ]
        },
        "provenance": [_prov("nve_varsom")],
    },
}


@pytest.fixture
def parts(monkeypatch):
    calls: list[tuple[str, dict]] = []
    failing: set[str] = set()

    async def fake(ctx, tool, arguments):
        calls.append((tool, arguments))
        if tool in failing:
            return ToolError(ErrorCode.UPSTREAM_UNAVAILABLE, f"{tool} is down.", retry_after_s=30)
        return PARTS[tool]

    monkeypatch.setattr(composite, "_part", fake)
    return calls, failing


async def test_overview_combines_every_part(ctx, parts):
    calls, _ = parts
    result = await OPS["place_overview"].invoke(ctx, {"lat": 60.3913, "lon": 5.3221})
    data = result["data"]
    assert data["municipality"]["name"] == "Bergen" and data["elevation_m"] == 4.07
    assert data["weather"]["next_6h_precipitation_mm"] == 2.7
    assert data["weather"]["next_6h_temperature_range_c"] == [10.2, 11.2]
    assert [w["kind"] for w in data["warnings"]] == ["weather", "flood"]
    assert data["nearest_stops"][0]["name"] == "Olav Kyrres gate"
    assert ("hazards_flood_landslide", {"municipality": "4601"}) in calls
    follow = {f["tool"] for f in data["follow_up"]}
    assert {"transit_departures", "schools_search", "companies_search"} <= follow
    assert {p["source_id"] for p in result["provenance"]} == {
        "kartverket",
        "met_locationforecast",
        "met_metalerts",
        "entur_geocoder",
        "nve_varsom",
    }
    assert result["notes"] == []


async def test_a_failing_part_becomes_a_note(ctx, parts):
    calls, failing = parts
    failing.update({"weather_forecast", "regions_at_point"})
    result = await OPS["place_overview"].invoke(ctx, {"lat": 60.3913, "lon": 5.3221})
    data = result["data"]
    assert data["weather"] is None and data["municipality"] is None
    assert data["nearest_stops"]  # the rest still answers
    assert any("No weather: weather_forecast is down." in n for n in result["notes"])
    assert any("flood and landslide warnings were not looked up" in n for n in result["notes"])
    assert "hazards_flood_landslide" not in {tool for tool, _ in calls}


async def test_a_point_at_sea_suggests_sea_level(ctx, parts, monkeypatch):
    monkeypatch.setitem(
        PARTS, "terrain_elevation", {"data": {"points": [{"elevation_m": -40.0}]}, "provenance": []}
    )
    result = await OPS["place_overview"].invoke(ctx, {"lat": 60.0, "lon": 5.0})
    assert "sea_level" in {f["tool"] for f in result["data"]["follow_up"]}
