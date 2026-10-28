"""Tools that answer one question from several sources at once.

They call the other tools through the registry, so every part keeps its own provenance,
budget and cache. A part that fails becomes a note; the rest of the answer still comes back.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Result
from kildeverk.core.errors import NextCall, ToolError
from kildeverk.core.operation import Operation


class PlaceOverviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=57, le=72)
    lon: float = Field(ge=4, le=32)


class Municipality(BaseModel):
    code: str
    name: str
    county_code: str
    county: str


class WeatherNow(BaseModel):
    time: dt.datetime | None
    temperature_c: float | None
    wind_speed_ms: float | None
    symbol: str | None
    next_6h_precipitation_mm: float | None
    next_6h_temperature_range_c: list[float] | None


class Warning(BaseModel):
    kind: str = Field(description="'weather', 'flood' or 'landslide'.")
    level: str
    title: str | None
    valid_to: dt.datetime | None


class NearbyStop(BaseModel):
    id: str
    name: str
    distance_km: float | None
    modes: list[str]


class NearbyPlace(BaseModel):
    name: str
    type: str
    distance_m: float | None


class PlaceOverviewOutput(BaseModel):
    lat: float
    lon: float
    municipality: Municipality | None
    elevation_m: float | None = Field(description="Negative at sea: the depth.")
    weather: WeatherNow | None
    warnings: list[Warning] = Field(description="Weather, flood and landslide warnings in force.")
    nearest_stops: list[NearbyStop]
    nearby_places: list[NearbyPlace]
    follow_up: list[NextCall] = Field(description="Calls that go deeper, ready to make.")


async def _part(ctx: Context, tool: str, arguments: dict[str, Any]) -> dict[str, Any] | ToolError:
    from kildeverk.sources.registry import operations

    op = next(o for o in operations() if o.name == tool)
    try:
        return await op.invoke(ctx, arguments)
    except ToolError as exc:
        return exc


def _time(value: Any) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if isinstance(value, str) else None


async def place_overview(ctx: Context, args: PlaceOverviewInput) -> Result[PlaceOverviewOutput]:
    point = {"lat": args.lat, "lon": args.lon}
    region, height, forecast, alerts, stops, places = await asyncio.gather(
        _part(ctx, "regions_at_point", point),
        _part(ctx, "terrain_elevation", {"points": [point]}),
        _part(ctx, "weather_forecast", {**point, "hours": 6}),
        _part(ctx, "weather_warnings", point),
        _part(ctx, "transit_find_stops", {**point, "radius_km": 1, "limit": 3}),
        _part(ctx, "places_search", {**point, "radius_m": 1000, "limit": 5}),
    )
    municipality = None
    if isinstance(region, dict):
        d = region["data"]
        municipality = Municipality(
            code=d["municipality_code"],
            name=d["municipality"],
            county_code=d["county_code"],
            county=d["county"],
        )
    # Flood and landslide warnings are issued per municipality, so they wait for it.
    hazards: dict[str, Any] | ToolError | None = None
    if municipality:
        hazards = await _part(ctx, "hazards_flood_landslide", {"municipality": municipality.code})

    parts = {
        "municipality": region,
        "elevation": height,
        "weather": forecast,
        "weather warnings": alerts,
        "nearest stops": stops,
        "nearby places": places,
    }
    if hazards is not None:
        parts["flood and landslide warnings"] = hazards
    provenance: list[Provenance] = []
    notes: list[str] = []
    for name, part in parts.items():
        if isinstance(part, ToolError):
            notes.append(f"No {name}: {part.body.message}")
        else:
            provenance.extend(Provenance.model_validate(p) for p in part["provenance"])
    if municipality is None and isinstance(region, ToolError):
        notes.append("Without a municipality, flood and landslide warnings were not looked up.")

    weather = None
    if isinstance(forecast, dict) and forecast["data"]["points"]:
        pts = forecast["data"]["points"]
        temps = [p["temperature_c"] for p in pts if p["temperature_c"] is not None]
        rain = [p["precipitation_mm"] for p in pts[:6] if p["precipitation_mm"] is not None]
        weather = WeatherNow(
            time=_time(pts[0]["time"]),
            temperature_c=pts[0]["temperature_c"],
            wind_speed_ms=pts[0]["wind_speed_ms"],
            symbol=pts[0]["symbol"],
            next_6h_precipitation_mm=round(sum(rain), 1) if rain else None,
            next_6h_temperature_range_c=[min(temps), max(temps)] if temps else None,
        )

    warnings: list[Warning] = []
    if isinstance(alerts, dict):
        warnings += [
            Warning(
                kind="weather",
                level=w["level_name"],
                title=w["event"],
                valid_to=_time(w["valid_to"]),
            )
            for w in alerts["data"]["warnings"]
        ]
    if isinstance(hazards, dict):
        warnings += [
            Warning(
                kind=w["kind"],
                level=w["level_name"],
                title=w["title"],
                valid_to=_time(w["valid_to"]),
            )
            for w in hazards["data"]["warnings"]
        ]

    elevation = None
    if isinstance(height, dict) and height["data"]["points"]:
        elevation = height["data"]["points"][0]["elevation_m"]
    nearest = (
        [
            NearbyStop(id=s["id"], name=s["name"], distance_km=s["distance_km"], modes=s["modes"])
            for s in stops["data"]["stops"]
        ]
        if isinstance(stops, dict)
        else []
    )
    named = (
        [
            NearbyPlace(name=p["name"], type=p["type"], distance_m=p["distance_m"])
            for p in places["data"]["places"]
        ]
        if isinstance(places, dict)
        else []
    )

    follow_up = [NextCall(tool="weather_forecast", arguments={**point, "hours": 48})]
    if nearest:
        follow_up.append(NextCall(tool="transit_departures", arguments={"stop": nearest[0].id}))
    if municipality:
        follow_up += [
            NextCall(tool="addresses_search", arguments=point),
            NextCall(tool="schools_search", arguments={"municipality": municipality.code}),
            NextCall(
                tool="companies_search",
                arguments={"municipality": [municipality.code], "sort": "most_employees"},
            ),
        ]
    if elevation is not None and elevation < 0:
        follow_up.append(NextCall(tool="sea_level", arguments=point))

    return Result(
        data=PlaceOverviewOutput(
            lat=args.lat,
            lon=args.lon,
            municipality=municipality,
            elevation_m=elevation,
            weather=weather,
            warnings=warnings,
            nearest_stops=nearest,
            nearby_places=named,
            follow_up=follow_up,
        ),
        provenance=provenance,
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="place_overview",
        title="Overview of a place",
        description=(
            "Everything Kildeverk knows about a point in Norway in one call: its municipality "
            "and county, elevation, the weather now and over the next 6 hours, weather, flood "
            "and landslide warnings in force, the nearest public transport stops and named "
            "places nearby, plus ready-made follow-up calls. Parts that fail become notes."
        ),
        input_model=PlaceOverviewInput,
        output_model=PlaceOverviewOutput,
        handler=place_overview,
        source_ids=(
            "kartverket",
            "met_locationforecast",
            "met_metalerts",
            "nve_varsom",
            "entur_geocoder",
        ),
        http_method="GET",
        http_path="/v1/places/overview",
        examples=({"lat": 60.3913, "lon": 5.3221},),
    ),
)
