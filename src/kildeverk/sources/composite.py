"""Tools that answer one question from several sources at once.

They call the other tools through the registry, so every part keeps its own provenance,
budget and cache. A part that fails becomes a note; the rest of the answer still comes back.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Literal, NamedTuple

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
    raining_now: bool | None = Field(default=None, description="From the radar nowcast.")
    rain_starts_at: dt.datetime | None = Field(
        default=None, description="Within the next two hours, from the radar nowcast."
    )
    rain_stops_at: dt.datetime | None = None


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
    region, height, forecast, radar, alerts, stops, places = await asyncio.gather(
        _part(ctx, "regions_at_point", point),
        _part(ctx, "terrain_elevation", {"points": [point]}),
        _part(ctx, "weather_forecast", {**point, "hours": 6}),
        _part(ctx, "weather_nowcast", point),
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
        "rain nowcast": radar,
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
        if isinstance(radar, dict):
            r = radar["data"]
            weather.raining_now = r["raining_now"]
            weather.rain_starts_at = _time(r["rain_starts_at"])
            weather.rain_stops_at = _time(r["rain_stops_at"])

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
    employer_accounts: bool = Field(
        default=True,
        description="Give the largest employers' latest revenue and result (one call each).",
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
    accounts_year: int | None = None
    revenue: float | None = Field(default=None, description="From its own latest accounts.")
    net_result: float | None = None
    currency: str | None = None


class Schools(BaseModel):
    total: int
    primary: int
    secondary: int
    private: int


class Electricity(BaseModel):
    from_date: dt.date
    to_date: dt.date
    average_mwh_per_day: float | None
    private_share_pct: float | None = Field(description="Homes and cabins, share of all use.")
    kwh_per_inhabitant_per_day: float | None = Field(
        description="All use, business and industry included, per inhabitant."
    )
    private_kwh_per_inhabitant_per_day: float | None = Field(
        description="Homes and cabins only, per inhabitant."
    )
    installed_capacity_mw: float = Field(description="Production capacity in the municipality.")
    largest_capacity_kind: str | None


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
    electricity: Electricity | None = Field(description="The last seven full days, from Elhub.")
    warnings: list[Warning]
    follow_up: list[NextCall]


def _pick(matches: list[dict[str, Any]], asked: str) -> tuple[str, str] | ToolError:
    """Today's (code, name) for what was asked, following reforms through Klass."""

    if not matches:
        return ToolError(
            ErrorCode.NOT_FOUND,
            f"No municipality, past or present, is called or numbered '{asked}'.",
            next_call=NextCall(tool="regions_resolve", arguments={"query": asked[:3]}),
        )
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
        electricity,
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
        _part(ctx, "electricity_municipality", {"municipality": code}),
    )
    parts = {
        "region": resolved,
        "population": population,
        "companies": companies,
        "schools": schools,
        "traffic points": traffic,
        "flood and landslide warnings": hazards,
        "weather warnings": weather,
        "electricity": electricity,
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
    if args.employer_accounts and employers:
        filed = await asyncio.gather(
            *(
                _part(ctx, "companies_accounts", {"org_number": e.org_number, "kind": "company"})
                for e in employers
            )
        )
        for employer, part in zip(employers, filed, strict=True):
            if isinstance(part, ToolError) or not part["data"]["accounts"]:
                continue
            latest = part["data"]["accounts"][0]
            employer.accounts_year = latest["year"]
            employer.revenue = latest["revenue"]
            employer.net_result = latest["net_result"]
            employer.currency = latest["currency"]
            provenance.extend(Provenance.model_validate(p) for p in part["provenance"])
        if any(e.revenue is None for e in employers):
            notes.append(
                "Employers without revenue file no open accounts: public bodies, sole "
                "proprietorships and the like."
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
    power = _electricity(electricity, people)
    if power:
        notes.append(
            "Electricity is the last seven full days, so it follows the season and the weather. "
            "Use per inhabitant includes business and industry; the private figure is homes and "
            "cabins only."
        )

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
            electricity=power,
            warnings=warnings,
            follow_up=[
                NextCall(tool="statistics_search_tables", arguments={"query": f"{name} kommune"}),
                NextCall(tool="schools_search", arguments={"municipality": code}),
                NextCall(tool="traffic_find_points", arguments={"municipality": code}),
                NextCall(tool="addresses_search", arguments={"municipality": code, "limit": 5}),
                NextCall(tool="electricity_municipality", arguments={"municipality": code}),
            ],
        ),
        provenance=provenance,
        notes=notes,
    )


def _electricity(part: dict[str, Any] | ToolError, people: Population | None) -> Electricity | None:
    if not isinstance(part, dict):
        return None
    d = part["data"]
    per_day = d["average_mwh_per_day"]
    private = next((g for g in d["by_group"] if g["group"] == "private"), None)
    inhabitants = people.latest if people else None

    def per_person(mwh_per_day: float | None) -> float | None:
        if mwh_per_day is None or not inhabitants:
            return None
        return round(mwh_per_day * 1000 / inhabitants, 1)

    private_per_day = (
        private["mwh"] / d["days_with_figures"] if private and d["days_with_figures"] else None
    )
    return Electricity(
        from_date=d["from_date"],
        to_date=d["to_date"],
        average_mwh_per_day=per_day,
        private_share_pct=private["share_pct"] if private else None,
        kwh_per_inhabitant_per_day=per_person(per_day),
        private_kwh_per_inhabitant_per_day=per_person(private_per_day),
        installed_capacity_mw=d["capacity_mw"],
        largest_capacity_kind=d["capacity"][0]["kind"] if d["capacity"] else None,
    )


# --- compare_municipalities --------------------------------------------------------


class CompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    municipalities: list[str] = Field(
        min_length=2,
        max_length=5,
        description="Two to five codes (old or current) or names, e.g. ['Bergen', '0301'].",
    )


class ComparedRow(BaseModel):
    code: str
    name: str
    population: int | None
    population_change_1y_pct: float | None
    population_change_since_pct: float | None
    population_change_since: str | None
    companies_registered: int | None
    companies_per_1000: float | None
    schools: int | None
    traffic_points: int | None
    electricity_kwh_per_inhabitant_per_day: float | None = Field(
        description="All use over the last seven full days, business and industry included."
    )
    private_electricity_kwh_per_inhabitant_per_day: float | None = Field(
        description="Homes and cabins only."
    )
    installed_capacity_mw: float | None
    warnings_in_force: int


class CompareOutput(BaseModel):
    rows: list[ComparedRow] = Field(description="Largest population first.")
    failed: list[str] = Field(description="Municipalities that could not be profiled; see notes.")


async def compare_municipalities(ctx: Context, args: CompareInput) -> Result[CompareOutput]:
    asked = list(dict.fromkeys(m.strip() for m in args.municipalities))
    profiles = await asyncio.gather(
        *(
            _part(ctx, "municipality_profile", {"municipality": m, "employer_accounts": False})
            for m in asked
        )
    )
    rows: list[ComparedRow] = []
    failed: list[str] = []
    notes: list[str] = []
    provenance: list[Provenance] = []
    seen: set[str] = set()
    for name, profile in zip(asked, profiles, strict=True):
        if isinstance(profile, ToolError):
            failed.append(name)
            notes.append(f"{name}: {profile.body.message}")
            continue
        d = profile["data"]
        if d["code"] in seen:
            notes.append(f"{name} is {d['code']} {d['name']}, already in the comparison.")
            continue
        seen.add(d["code"])
        provenance.extend(Provenance.model_validate(p) for p in profile["provenance"])
        notes.extend(
            f"{d['name']}: {n}"
            for n in profile["notes"]
            if not n.startswith(("School counts", "Electricity is the last", "Employers without"))
        )
        people = d["population"] or {}
        companies = d["companies_registered"]
        power = d.get("electricity") or {}
        rows.append(
            ComparedRow(
                code=d["code"],
                name=d["name"],
                population=people.get("latest"),
                population_change_1y_pct=people.get("change_1y_pct"),
                population_change_since_pct=people.get("change_since_pct"),
                population_change_since=people.get("change_since"),
                companies_registered=companies,
                companies_per_1000=round(companies / people["latest"] * 1000, 1)
                if companies and people.get("latest")
                else None,
                schools=(d["schools"] or {}).get("total"),
                traffic_points=d["traffic_points"],
                electricity_kwh_per_inhabitant_per_day=power.get("kwh_per_inhabitant_per_day"),
                private_electricity_kwh_per_inhabitant_per_day=power.get(
                    "private_kwh_per_inhabitant_per_day"
                ),
                installed_capacity_mw=power.get("installed_capacity_mw"),
                warnings_in_force=len(d["warnings"]),
            )
        )
    if len(rows) < 2 and not failed:
        notes.append("Fewer than two distinct municipalities to compare.")
    rows.sort(key=lambda r: r.population or 0, reverse=True)
    notes.append("School counts include every unit the register calls a school.")
    if any(r.electricity_kwh_per_inhabitant_per_day is not None for r in rows):
        notes.append(
            "Electricity per inhabitant is the last seven full days. The total includes business "
            "and industry, so it reflects the local economy as much as homes."
        )
    return Result(
        data=CompareOutput(rows=rows, failed=failed),
        provenance=provenance,
        notes=notes,
    )


# --- statistics_series -------------------------------------------------------------

# SSB's codelists that sum older regions into today's, and the prefix their codes carry.
SUMMED_CODELISTS = {
    "municipality": {"agg_KommSummer": "K-", "agg_KommSummerHist": "K_"},
    "county": {"agg_KommFylker": "F-", "agg_KommFylkerHist": "F_"},
}


def _summed_codelist(level: str, available: set[str]) -> tuple[str, str] | None:
    """The table's codelist summed to today's borders for `level`, and its code prefix."""

    for name, prefix in SUMMED_CODELISTS.get(level, {}).items():
        if name in available:
            return name, prefix
    return None


class SeriesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str = Field(pattern=r"^\d{5}$", description="SSB table, e.g. '07459'.")
    region: str = Field(
        min_length=1,
        max_length=60,
        description="'0' for Norway, a county or municipality code (old or current), or a name.",
    )
    measure: str | None = Field(
        default=None,
        description="The ContentsCode value, when the table has more than one measure.",
    )
    filters: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Codes for the table's other dimensions, e.g. {'Kjonn': ['2']}. Dimensions "
        "left out are summed where SSB allows it.",
    )
    from_year: int | None = Field(default=None, ge=1800, le=2100)
    to_year: int | None = Field(default=None, ge=1800, le=2100)
    measure_kind: Literal["additive", "non_additive"] | None = Field(
        default=None,
        description="When SSB has no series for today's borders: 'additive' (counts, totals) lets "
        "Kildeverk rebuild earlier years by summing the regions that became this one; "
        "'non_additive' (rates, shares) follows renumberings only. Leave out to get the "
        "region's own series as published.",
    )


class SeriesPoint(BaseModel):
    period: str
    value: float | int | None
    status: str | None = None


class SeriesOutput(BaseModel):
    table_id: str
    title: str
    region_code: str
    region_name: str | None
    measure: str | None
    method: str = Field(
        description="'summed_to_todays_borders' (SSB's series for today's region, older "
        "regions included), 'harmonised' (rebuilt here from the regions that became this one) "
        "or 'as_published' (the code's own series)."
    )
    points: list[SeriesPoint]


async def _region_for_series(ctx: Context, value: str) -> tuple[str, str, str | None]:
    """(code, level, note) for '0', a code, or a name tried as municipality then county."""

    from kildeverk.sources.ssb_klass.names import resolve_region

    value = value.strip()
    if value == "0":
        return "0", "country", None
    if value.isdigit():
        level = "municipality" if len(value) == 4 else "county"
        resolved = await _part(ctx, "regions_resolve", {"query": value, "level": level, "limit": 5})
        if isinstance(resolved, dict):
            picked = _pick(resolved["data"]["matches"], value)
            if not isinstance(picked, ToolError) and picked[0] != value:
                return picked[0], level, f"{value} is today {picked[0]} {picked[1]}."
        return value, level, None
    for level in ("municipality", "county"):
        try:
            resolved = await resolve_region(ctx, value, level)  # type: ignore[arg-type]
        except ToolError as exc:
            if exc.body.code == "AMBIGUOUS":
                raise
            continue
        return resolved.code, level, resolved.note
    raise ToolError(
        ErrorCode.NOT_FOUND,
        f"No municipality or county is called '{value}'.",
        next_call=NextCall(tool="regions_resolve", arguments={"query": value}),
    )


class _Prepared(NamedTuple):
    table: dict[str, Any]
    dims: dict[str, dict[str, Any]]
    region_dim: str
    time_dim: str
    measure_dim: dict[str, Any] | None
    select: dict[str, Any]
    provenance: list[Provenance]


async def _prepare_table(
    ctx: Context,
    table_id: str,
    measure: str | None,
    filters: dict[str, list[str]],
    *,
    retry: tuple[str, dict[str, Any]],
) -> _Prepared:
    """Describe a table and build the selection every region tool needs, or say what is missing."""

    described = await _part(
        ctx, "statistics_describe_table", {"table_id": table_id, "values_limit": 50}
    )
    if isinstance(described, ToolError):
        raise described
    table = described["data"]
    dims = {d["role"]: d for d in table["dimensions"] if d["role"] in ("region", "time", "measure")}
    if "region" not in dims or "time" not in dims:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Table {table_id} has no region or no time dimension, so it cannot be read by region.",
            next_call=NextCall(
                tool="statistics_search_tables", arguments={"query": table["title"][:40]}
            ),
        )
    region_dim, time_dim = dims["region"]["code"], dims["time"]["code"]
    select: dict[str, Any] = dict(filters)
    measure_dim = dims.get("measure")
    if measure_dim:
        measures = [v["code"] for v in measure_dim["values"]]
        if measure:
            select[measure_dim["code"]] = [measure]
        elif len(measures) == 1:
            select[measure_dim["code"]] = measures
        else:
            options = ", ".join(f"{v['code']} ({v['label']})" for v in measure_dim["values"][:12])
            tool, arguments = retry
            raise ToolError(
                ErrorCode.AMBIGUOUS,
                f"Table {table_id} has several measures; choose one with `measure`: {options}.",
                next_call=NextCall(tool=tool, arguments={**arguments, "measure": measures[0]}),
            )
    for d in table["dimensions"]:
        if (
            d["code"] not in select
            and d["code"] not in (region_dim, time_dim)
            and not d["can_omit"]
        ):
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"Table {table_id} needs a value for {d['code']} ({d['label']}); pass it in "
                f"`filters`, e.g. {{'{d['code']}': ['{d['values'][0]['code']}']}}.",
                next_call=NextCall(
                    tool="statistics_describe_table", arguments={"table_id": table_id}
                ),
            )
    return _Prepared(
        table=table,
        dims=dims,
        region_dim=region_dim,
        time_dim=time_dim,
        measure_dim=measure_dim,
        select=select,
        provenance=[Provenance.model_validate(p) for p in described["provenance"]],
    )


async def _harmonised_series(
    ctx: Context,
    args: SeriesInput,
    code: str,
    level: str,
    region_dim: str,
    time_dim: str,
    select: dict[str, Any],
    first_year: int | None,
) -> tuple[list[SeriesPoint], list[Provenance], list[str]] | None:
    """Rebuild a series under today's borders from the regions that became `code`."""

    from kildeverk.sources.ssb_klass.ops import _history, _today

    history, klass_provenance, _ = await _history(ctx, level)
    today = _today()
    sources = {code}
    for units in history.units.values():
        for unit in units:
            # SSB refuses a whole request naming a code its table does not have, so only codes
            # still in use when the table starts are asked for.
            if unit.valid_to is None or (first_year and unit.valid_to.year <= first_year):
                continue
            if code in {t.code for t in history.map_to(unit, today).targets}:
                sources.add(unit.code)
    if len(sources) == 1:
        return None
    fetched = await _part(
        ctx,
        "statistics_get_data",
        {
            "table_id": args.table_id,
            "select": {**select, region_dim: sorted(sources)},
            "max_rows": 10000,
        },
    )
    if isinstance(fetched, ToolError):
        return None
    rows = [
        {"region": r[region_dim], "period": str(r[time_dim]), "value": r["value"]}
        for r in fetched["data"]["rows"]
        if isinstance(r.get("value"), int | float)
    ]
    if not rows:
        return None
    # A rate cannot be summed over merged regions, so for non-additive measures each source
    # is harmonised alone and only its one-to-one renumberings are kept. Both run locally on
    # the cached Klass history, with no extra upstream calls.
    batches = (
        [rows]
        if args.measure_kind == "additive"
        else [[r for r in rows if r["region"] == source] for source in sorted(sources)]
    )
    converted: dict[str, float] = {}
    gaps: set[str] = set()
    harmonise_provenance: list[dict[str, Any]] = []
    for batch in batches:
        if not batch:
            continue
        harmonised = await _part(
            ctx,
            "regions_harmonise",
            {"level": level, "target": "latest", "measure": args.measure_kind, "rows": batch},
        )
        if isinstance(harmonised, ToolError):
            continue
        harmonise_provenance = harmonised["provenance"]
        for r in harmonised["data"]["rows"]:
            if r["region"] == code:
                converted.setdefault(r["period"], r["value"])
        gaps |= {u["period"] for u in harmonised["data"]["unconverted"]}
    if not converted:
        return None
    points = [
        SeriesPoint(period=period, value=value)
        for period, value in sorted(converted.items())
        if not (args.to_year and period[:4].isdigit() and int(period[:4]) > args.to_year)
    ]
    gaps -= set(converted)
    notes = [
        (
            f"Rebuilt under today's borders from {len(sources)} codes ({', '.join(sorted(sources))}) "
            f"with regions_harmonise ({args.measure_kind})."
        )
    ]
    if gaps:
        notes.append(
            f"{len(gaps)} periods could not be converted exactly (a region was divided) and are "
            "left out."
        )
    provenance = [
        *klass_provenance,
        *(Provenance.model_validate(p) for p in fetched["provenance"]),
        *(Provenance.model_validate(p) for p in harmonise_provenance),
    ]
    return points, provenance, notes


async def statistics_series(ctx: Context, args: SeriesInput) -> Result[SeriesOutput]:
    code, level, region_note = await _region_for_series(ctx, args.region)
    prepared = await _prepare_table(
        ctx,
        args.table_id,
        args.measure,
        args.filters,
        retry=("statistics_series", {"table_id": args.table_id, "region": args.region}),
    )
    table, dims, region_dim, time_dim, measure_dim, select, described_provenance = prepared
    if args.from_year:
        select[time_dim] = {"from": str(args.from_year)}
    else:
        select[time_dim] = "*"

    notes = [region_note] if region_note else []
    provenance = list(described_provenance)
    method = "as_published"
    fetched: dict[str, Any] | ToolError | None = None
    summed = _summed_codelist(level, {c["id"] for c in dims["region"].get("codelists") or []})
    if summed:
        fetched = await _part(
            ctx,
            "statistics_get_data",
            {
                "table_id": args.table_id,
                "codelists": {region_dim: summed[0]},
                "select": {**select, region_dim: [summed[1] + code]},
                "max_rows": 10000,
            },
        )
        if isinstance(fetched, dict) and fetched["data"]["rows"]:
            method = "summed_to_todays_borders"
        else:
            fetched = None
    if fetched is None:
        fetched = await _part(
            ctx,
            "statistics_get_data",
            {
                "table_id": args.table_id,
                "select": {**select, region_dim: [code]},
                "max_rows": 10000,
            },
        )
    if isinstance(fetched, ToolError):
        raise fetched
    provenance.extend(Provenance.model_validate(p) for p in fetched["provenance"])
    notes.extend(fetched["notes"])

    rows = fetched["data"]["rows"]
    periods: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        periods.setdefault(str(row[time_dim]), []).append(row)
    if any(len(r) > 1 for r in periods.values()):
        notes.append(
            "Several rows per period: a dimension in `filters` has more than one value. Values "
            "are summed per period; ask for one value per dimension for a single series."
        )
    points = []
    for period in sorted(periods):
        group = periods[period]
        values = [r.get("value") for r in group if isinstance(r.get("value"), int | float)]
        status = next((r.get("status") for r in group if r.get("status")), None)
        if args.to_year and period[:4].isdigit() and int(period[:4]) > args.to_year:
            continue
        points.append(
            SeriesPoint(period=period, value=sum(values) if values else None, status=status)
        )
    if method == "as_published" and args.measure_kind and level in SUMMED_CODELISTS:
        first = str(table.get("first_period") or "")[:4]
        rebuilt = await _harmonised_series(
            ctx,
            args,
            code,
            level,
            region_dim,
            time_dim,
            select,
            int(first) if first.isdigit() else None,
        )
        if rebuilt is not None:
            rebuilt_points, rebuilt_provenance, rebuilt_notes = rebuilt
            if len(rebuilt_points) > len([p for p in points if p.value]):
                points, method = rebuilt_points, "harmonised"
                provenance.extend(rebuilt_provenance)
                notes.extend(rebuilt_notes)
    if method == "as_published":
        # SSB fills years before a region existed with zeros; they are not data.
        while points and points[0].value == 0:
            points.pop(0)
        if level in SUMMED_CODELISTS and points:
            notes.append(
                f"SSB has no series summed to today's borders for this table, so the series is "
                f"{code}'s own and starts at {points[0].period}."
                + (
                    ""
                    if args.measure_kind
                    else " Give measure_kind to rebuild earlier years from the regions that "
                    "became this one."
                )
            )
    first = rows[0] if rows else {}
    return Result(
        data=SeriesOutput(
            table_id=args.table_id,
            title=table["title"],
            region_code=code,
            region_name=first.get(f"{region_dim}_label"),
            measure=first.get(f"{measure_dim['code']}_label") if measure_dim else None,
            method=method,
            points=points,
        ),
        provenance=provenance,
        notes=notes,
    )


# --- statistics_rank ---------------------------------------------------------------


class RankInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str = Field(pattern=r"^\d{5}$", description="SSB table, e.g. '07459'.")
    level: Literal["municipality", "county"] = "municipality"
    measure: str | None = Field(default=None, description="ContentsCode, when there are several.")
    filters: dict[str, list[str]] = Field(
        default_factory=dict, description="Codes for the table's other dimensions."
    )
    period: str | None = Field(
        default=None, max_length=10, description="e.g. '2025'. Defaults to the latest."
    )
    compare_to: str | None = Field(
        default=None,
        max_length=10,
        description="An earlier period. Adds the change to each row and ranks by it.",
    )
    order: Literal["highest", "lowest"] = "highest"
    min_value: float | None = Field(
        default=None,
        description="Leave out regions whose value is below this, e.g. 1000 when ranking change, "
        "so that tiny municipalities with large swings don't top the list.",
    )
    limit: int = Field(default=10, ge=1, le=400)


class RankedRow(BaseModel):
    rank: int
    code: str
    name: str | None
    value: float | int | None
    earlier: float | int | None = Field(description="The value in `compare_to`, if given.")
    change: float | int | None
    change_pct: float | None


class RankOutput(BaseModel):
    table_id: str
    title: str
    measure: str | None
    level: str
    period: str
    compare_to: str | None
    ranked_by: str = Field(description="'value' or 'change_pct'.")
    method: str = Field(
        description="'summed_to_todays_borders', or 'current_codes' (today's codes as published)."
    )
    country: RankedRow | None = Field(description="Norway as a whole, for reference.")
    total_regions: int
    rows: list[RankedRow]


async def statistics_rank(ctx: Context, args: RankInput) -> Result[RankOutput]:
    from kildeverk.sources.ssb_klass.ops import _history, _today

    table, dims, region_dim, time_dim, measure_dim, select, provenance = await _prepare_table(
        ctx,
        args.table_id,
        args.measure,
        args.filters,
        retry=("statistics_rank", {"table_id": args.table_id, "level": args.level}),
    )
    provenance = list(provenance)
    last = str(table["last_period"])
    if args.period:
        candidates = [args.period]
    elif last.isdigit():
        # The newest year is sometimes listed before its figures exist ('..'), so the last
        # three are fetched and the newest with data is used.
        candidates = [str(int(last) - n) for n in range(3)]
    else:
        candidates = [last]
    select[time_dim] = sorted(set(candidates + ([args.compare_to] if args.compare_to else [])))
    notes: list[str] = []

    summed = _summed_codelist(args.level, {c["id"] for c in dims["region"].get("codelists") or []})
    codelist, prefix = summed or ("", "")
    method = "current_codes"
    fetched: dict[str, Any] | ToolError | None = None
    if summed:
        fetched = await _part(
            ctx,
            "statistics_get_data",
            {
                "table_id": args.table_id,
                "codelists": {region_dim: codelist},
                "select": {**select, region_dim: "*"},
                "max_rows": 10000,
            },
        )
        if isinstance(fetched, dict) and fetched["data"]["rows"]:
            method = "summed_to_todays_borders"
        else:
            fetched = None
    if fetched is None:
        history, klass_provenance, _ = await _history(ctx, args.level)
        current = [u.code for u in history.units_at(_today())]
        fetched = await _part(
            ctx,
            "statistics_get_data",
            {
                "table_id": args.table_id,
                "select": {**select, region_dim: current},
                "max_rows": 10000,
            },
        )
        provenance.extend(klass_provenance)
        if args.compare_to:
            notes.append(
                "SSB has no series for today's borders in this table: regions created by a "
                "reform after the earlier period have no value for it."
            )
    if isinstance(fetched, ToolError):
        raise fetched
    provenance.extend(Provenance.model_validate(p) for p in fetched["provenance"])
    notes.extend(fetched["notes"])

    values: dict[str, dict[str, Any]] = {}
    names: dict[str, str | None] = {}
    for row in fetched["data"]["rows"]:
        code = str(row[region_dim]).removeprefix(prefix)
        names[code] = row.get(f"{region_dim}_label")
        if isinstance(row.get("value"), int | float):
            values.setdefault(code, {})[str(row[time_dim])] = row["value"]

    # A period counts as having data only with real values: SSB's placeholder zeros don't.
    with_data = [p for p in candidates if any(v.get(p) for v in values.values())]
    period = with_data[0] if with_data else candidates[0]
    if not args.period and period != last:
        notes.append(f"{last} has no figures yet, so {period} is ranked.")

    def build(code: str) -> RankedRow:
        now = values.get(code, {}).get(period)
        before = values.get(code, {}).get(args.compare_to) if args.compare_to else None
        change = now - before if now is not None and before is not None else None
        return RankedRow(
            rank=0,
            code=code,
            name=names.get(code),
            value=now,
            earlier=before,
            change=round(change, 4) if isinstance(change, float) else change,
            change_pct=round(change / before * 100, 2) if change is not None and before else None,
        )

    rows = [build(code) for code in values if code not in ("0", "Rest")]
    # SSB's placeholder zeros (a region that did not exist yet) are not values to rank.
    rows = [r for r in rows if r.value not in (None, 0) or (r.value == 0 and r.earlier)]
    if args.min_value is not None:
        small = [r for r in rows if r.value is None or r.value < args.min_value]
        rows = [r for r in rows if r not in small]
        if small:
            notes.append(f"{len(small)} regions below {args.min_value:g} are left out.")
    key = "change_pct" if args.compare_to else "value"
    ranked = [r for r in rows if getattr(r, key) is not None]
    ranked.sort(key=lambda r: getattr(r, key), reverse=args.order == "highest")
    for n, r in enumerate(ranked, 1):
        r.rank = n
    if key == "change_pct" and args.min_value is None and ranked:
        notes.append(
            "Small regions can top a ranking by change with tiny numbers; set min_value to leave "
            "them out."
        )
    if len(ranked) < len(rows):
        notes.append(
            f"{len(rows) - len(ranked)} regions have no {key.replace('_', ' ')} and are left out."
        )

    country = None
    national = await _part(
        ctx,
        "statistics_get_data",
        {"table_id": args.table_id, "select": {**select, region_dim: ["0"]}},
    )
    if isinstance(national, dict) and national["data"]["rows"]:
        for row in national["data"]["rows"]:
            if isinstance(row.get("value"), int | float):
                values.setdefault("0", {})[str(row[time_dim])] = row["value"]
        names["0"] = national["data"]["rows"][0].get(f"{region_dim}_label")
        country = build("0")
        provenance.extend(Provenance.model_validate(p) for p in national["provenance"])

    first = fetched["data"]["rows"][0] if fetched["data"]["rows"] else {}
    return Result(
        data=RankOutput(
            table_id=args.table_id,
            title=table["title"],
            measure=first.get(f"{measure_dim['code']}_label") if measure_dim else None,
            level=args.level,
            period=period,
            compare_to=args.compare_to,
            ranked_by=key,
            method=method,
            country=country,
            total_regions=len(ranked),
            rows=ranked[: args.limit],
        ),
        provenance=provenance,
        notes=notes,
        truncated=len(ranked) > args.limit,
    )


OPERATIONS = (
    Operation(
        name="place_overview",
        title="Overview of a place",
        description=(
            "Everything Kildeverk knows about a point in Norway in one call: its municipality "
            "and county, elevation, the weather now and over the next 6 hours, when rain starts "
            "or stops in the next two hours (radar nowcast), weather, flood "
            "and landslide warnings in force, the nearest public transport stops and named "
            "places nearby, plus ready-made follow-up calls. Parts that fail become notes."
        ),
        input_model=PlaceOverviewInput,
        output_model=PlaceOverviewOutput,
        handler=place_overview,
        source_ids=(
            "kartverket",
            "met_locationforecast",
            "met_nowcast",
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
            "with their latest revenue and result (Regnskapsregisteret), schools by level and "
            "ownership (Udir), traffic counting points (Statens vegvesen), electricity use per "
            "inhabitant and installed production capacity over the last week "
            "(Elhub), and weather, flood and landslide warnings in force. Accepts today's code, a "
            "code from before the 2020 or 2024 reforms, or a name."
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
            "elhub",
            "brreg_accounts",
        ),
        http_method="GET",
        http_path="/v1/municipalities/{municipality}/profile",
        examples=({"municipality": "4601"}, {"municipality": "1201"}, {"municipality": "Tromsø"}),
    ),
    Operation(
        name="compare_municipalities",
        title="Compare municipalities",
        description=(
            "Two to five Norwegian municipalities side by side: population and its change, "
            "registered companies (also per 1,000 inhabitants), schools, traffic counting points, "
            "electricity use per inhabitant and warnings in force. Accepts codes, old or current, "
            "and names. Built on "
            "municipality_profile, which gives each one in full."
        ),
        input_model=CompareInput,
        output_model=CompareOutput,
        handler=compare_municipalities,
        source_ids=(
            "ssb_klass",
            "ssb_statbank",
            "brreg",
            "udir_nsr",
            "vegvesen_traffic",
            "nve_varsom",
            "met_metalerts",
            "elhub",
        ),
        http_method="POST",
        http_path="/v1/municipalities/compare",
        examples=({"municipalities": ["Bergen", "Trondheim", "Stavanger"]},),
    ),
    Operation(
        name="statistics_series",
        title="A statistic over time for one region",
        description=(
            "One SSB statistic for Norway, a county or a municipality over every year, in one "
            "call. Uses SSB's series summed to today's borders where the table has one, so the "
            "series does not stop at the 2020 or 2024 reforms. Accepts codes, old or current, "
            "and names. Find tables with statistics_search_tables."
        ),
        input_model=SeriesInput,
        output_model=SeriesOutput,
        handler=statistics_series,
        source_ids=("ssb_statbank", "ssb_klass"),
        http_method="POST",
        http_path="/v1/statistics/series",
        examples=(
            {"table_id": "07459", "region": "Tromsø", "from_year": 2010},
            {"table_id": "07459", "region": "46", "filters": {"Kjonn": ["2"]}},
        ),
    ),
    Operation(
        name="statistics_rank",
        title="Rank municipalities or counties on a statistic",
        description=(
            "Every municipality or county ranked on one SSB statistic for one period, highest or "
            "lowest first, with Norway's figure for reference. Give compare_to for an earlier "
            "period to rank by change instead ('which municipalities grew fastest since 2015?'). "
            "Uses SSB's figures for today's borders where the table has them."
        ),
        input_model=RankInput,
        output_model=RankOutput,
        handler=statistics_rank,
        source_ids=("ssb_statbank", "ssb_klass"),
        http_method="POST",
        http_path="/v1/statistics/rank",
        examples=(
            {"table_id": "07459", "limit": 5},
            {"table_id": "07459", "compare_to": "2015", "limit": 5},
            {"table_id": "07459", "level": "county", "order": "lowest"},
        ),
    ),
)
