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
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
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


# --- municipality_profile ----------------------------------------------------------


class MunicipalityProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    municipality: str = Field(
        min_length=2,
        max_length=60,
        description="A municipality code, old or current ('1201', '4601'), or a name ('Bergen').",
    )


class Population(BaseModel):
    latest: int
    year: str
    change_1y_pct: float | None
    change_since: str | None = Field(description="The earliest year the change below is from.")
    change_since_pct: float | None


class Employer(BaseModel):
    org_number: str
    name: str
    employees: int | None
    industry: str | None


class Schools(BaseModel):
    total: int
    primary: int
    secondary: int
    private: int


class MunicipalityProfileOutput(BaseModel):
    code: str
    name: str
    county_code: str
    resolved_from: str | None = Field(
        description="The code or name asked for, when it was not today's code."
    )
    population: Population | None
    companies_registered: int | None = Field(description="Active units in the business register.")
    largest_employers: list[Employer]
    schools: Schools | None
    traffic_points: int | None = Field(description="Operational traffic counting points.")
    warnings: list[Warning]
    follow_up: list[NextCall]


def _pick(matches: list[dict[str, Any]], asked: str) -> tuple[str, str] | ToolError:
    """Today's (code, name) for what was asked, following reforms through Klass."""

    exact = [m for m in matches if asked in (m["code"], m["name"].lower())] or matches
    current = {(m["code"], m["name"]) for m in exact if m["status"] == "current"}
    later = {
        (r["code"], r["name"])
        for m in exact
        if m["status"] == "ended" and m["today_exact"]
        for r in m["today"]
    }
    options = current or later
    if len(options) == 1:
        return options.pop()
    if not options:
        return ToolError(
            ErrorCode.NOT_FOUND,
            f"'{asked}' is no municipality today, or was split between several.",
            next_call=NextCall(tool="regions_resolve", arguments={"query": asked}),
        )
    return ToolError(
        ErrorCode.AMBIGUOUS,
        f"'{asked}' fits several municipalities: "
        + ", ".join(f"{c} {n}" for c, n in sorted(options))
        + ". Give the code.",
        next_call=NextCall(
            tool="municipality_profile", arguments={"municipality": min(options)[0]}
        ),
    )


async def _population_part(ctx: Context, code: str) -> dict[str, Any] | ToolError:
    """Population for the last 11 years under today's borders.

    SSB's `agg_KommSummer` codelist sums older municipalities into today's ('K-4601'), so the
    series does not start at the latest reform. A municipality missing from it falls back to
    the plain code.
    """

    select = {"ContentsCode": ["Personer1"], "Tid": {"latest": 11}}
    summed = await _part(
        ctx,
        "statistics_get_data",
        {
            "table_id": "07459",
            "codelists": {"Region": "agg_KommSummer"},
            "select": {"Region": [f"K-{code}"], **select},
        },
    )
    if isinstance(summed, dict) and summed["data"]["rows"]:
        return summed
    return await _part(
        ctx, "statistics_get_data", {"table_id": "07459", "select": {"Region": [code], **select}}
    )


def _population(rows: list[dict[str, Any]]) -> Population | None:
    # Years before a municipality existed come back as 0 from SSB; they are not data.
    rows = [r for r in rows if isinstance(r.get("value"), int) and r["value"] > 0]
    if not rows:
        return None
    rows.sort(key=lambda r: r["Tid"])
    latest, first = rows[-1], rows[0]

    def pct(old: int, new: int) -> float:
        return round((new - old) / old * 100, 2)

    return Population(
        latest=latest["value"],
        year=latest["Tid"],
        change_1y_pct=pct(rows[-2]["value"], latest["value"]) if len(rows) > 1 else None,
        change_since=first["Tid"] if len(rows) > 1 else None,
        change_since_pct=pct(first["value"], latest["value"]) if len(rows) > 1 else None,
    )


async def municipality_profile(
    ctx: Context, args: MunicipalityProfileInput
) -> Result[MunicipalityProfileOutput]:
    asked = args.municipality.strip().lower()
    resolved = await _part(
        ctx, "regions_resolve", {"query": asked, "level": "municipality", "limit": 20}
    )
    if isinstance(resolved, ToolError):
        raise resolved
    picked = _pick(resolved["data"]["matches"], asked)
    if isinstance(picked, ToolError):
        raise picked
    code, name = picked

    # The school searches differ only in filters applied here, so they share one upstream call.
    school_query = {"municipality": code, "limit": 1}
    (
        population,
        companies,
        schools,
        primary,
        secondary,
        private,
        traffic,
        hazards,
        weather,
    ) = await asyncio.gather(
        _population_part(ctx, code),
        _part(
            ctx, "companies_search", {"municipality": [code], "sort": "most_employees", "limit": 5}
        ),
        _part(ctx, "schools_search", school_query),
        _part(ctx, "schools_search", {**school_query, "level": "primary"}),
        _part(ctx, "schools_search", {**school_query, "level": "secondary"}),
        _part(ctx, "schools_search", {**school_query, "ownership": "private"}),
        _part(ctx, "traffic_find_points", {"municipality": code, "limit": 50}),
        _part(ctx, "hazards_flood_landslide", {"municipality": code}),
        _part(ctx, "weather_warnings", {"county": code[:2]}),
    )
    parts = {
        "region": resolved,
        "population": population,
        "companies": companies,
        "schools": schools,
        "traffic points": traffic,
        "flood and landslide warnings": hazards,
        "weather warnings": weather,
    }
    provenance: list[Provenance] = []
    notes: list[str] = []
    for label, part in parts.items():
        if isinstance(part, ToolError):
            notes.append(f"No {label}: {part.body.message}")
        else:
            provenance.extend(Provenance.model_validate(p) for p in part["provenance"])

    people = _population(population["data"]["rows"]) if isinstance(population, dict) else None
    if people and people.change_since and int(people.year) - int(people.change_since) < 10:
        notes.append(
            f"Population change is from {people.change_since}, the first year SSB has figures for "
            f"{code}."
        )
    employers = (
        [
            Employer(
                org_number=c["org_number"],
                name=c["name"],
                employees=c.get("employees"),
                industry=(c.get("industry") or {}).get("description")
                if isinstance(c.get("industry"), dict)
                else c.get("industry"),
            )
            for c in companies["data"]["companies"]
        ]
        if isinstance(companies, dict)
        else []
    )
    school_counts = None
    counts = [schools, primary, secondary, private]
    if all(isinstance(c, dict) for c in counts):
        total, n_primary, n_secondary, n_private = (c["data"]["total_matches"] for c in counts)  # type: ignore[index]
        school_counts = Schools(
            total=total, primary=n_primary, secondary=n_secondary, private=n_private
        )
        notes.append(
            "School counts include every active unit the register calls a school, such as "
            "adult education and culture schools."
        )
    warnings: list[Warning] = []
    if isinstance(weather, dict):
        warnings += [
            Warning(
                kind="weather",
                level=w["level_name"],
                title=w["event"],
                valid_to=_time(w["valid_to"]),
            )
            for w in weather["data"]["warnings"]
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
    if warnings and any(w.kind == "weather" for w in warnings):
        notes.append("Weather warnings are for the whole county; check each warning's area.")

    return Result(
        data=MunicipalityProfileOutput(
            code=code,
            name=name,
            county_code=code[:2],
            resolved_from=args.municipality if args.municipality != code else None,
            population=people,
            companies_registered=companies["data"].get("total_matches")
            if isinstance(companies, dict)
            else None,
            largest_employers=employers,
            schools=school_counts,
            traffic_points=traffic["data"]["total_matches"] if isinstance(traffic, dict) else None,
            warnings=warnings,
            follow_up=[
                NextCall(tool="statistics_search_tables", arguments={"query": f"{name} kommune"}),
                NextCall(tool="schools_search", arguments={"municipality": code}),
                NextCall(tool="traffic_find_points", arguments={"municipality": code}),
                NextCall(tool="addresses_search", arguments={"municipality": code, "limit": 5}),
            ],
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
    Operation(
        name="municipality_profile",
        title="Profile of a municipality",
        description=(
            "One Norwegian municipality from several sources at once: population and how it "
            "changed (SSB), registered companies and the largest employers (Brønnøysund), "
            "schools by level and ownership (Udir), traffic counting points (Statens vegvesen), "
            "and weather, flood and landslide warnings in force. Accepts today's code, a code "
            "from before the 2020 or 2024 reforms, or a name."
        ),
        input_model=MunicipalityProfileInput,
        output_model=MunicipalityProfileOutput,
        handler=municipality_profile,
        source_ids=(
            "ssb_klass",
            "ssb_statbank",
            "brreg",
            "udir_nsr",
            "vegvesen_traffic",
            "nve_varsom",
            "met_metalerts",
        ),
        http_method="GET",
        http_path="/v1/municipalities/{municipality}/profile",
        examples=({"municipality": "4601"}, {"municipality": "1201"}, {"municipality": "Tromsø"}),
    ),
)
