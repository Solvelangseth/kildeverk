"""Hydrology tools backed by NVE's HydAPI."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import Upstream, UpstreamClientError
from kildeverk.sources.nve_hydapi.models import (
    PARAMETER_ALIASES,
    RESOLUTIONS,
    FindStationsInput,
    FindStationsOutput,
    FloodStatistics,
    ObservationsInput,
    ObservationsOutput,
    Reading,
    Series,
    Station,
    as_utc,
)
from kildeverk.sources.nve_hydapi.spec import BASE_URL, KEY_URL, SPEC

QUALITY = {0: "unknown", 1: "uncontrolled", 2: "primary_controlled", 3: "secondary_controlled"}
RESOLUTION_NAMES = {minutes: name for name, minutes in RESOLUTIONS.items()}
ALIAS_OF = {number: name for name, number in PARAMETER_ALIASES.items()}
RECENT = dt.timedelta(days=2)


def _upstream(ctx: Context) -> Upstream:
    up = ctx.upstream(SPEC.id)
    if up.auth is None:
        raise ToolError(
            ErrorCode.NOT_CONFIGURED,
            f"Hydrology data needs a HydAPI key, and none is configured here. Get one free at "
            f"{KEY_URL} and set KILDEVERK_NVE_API_KEY.",
            source_id=SPEC.id,
        )
    return up


def _parameter(name: str) -> int:
    return int(name) if name.isdigit() else PARAMETER_ALIASES.get(name, -1)


def _date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _square(lat: float, lon: float, radius_km: float) -> str:
    """A WKT square around the point. HydAPI reads its coordinates as (latitude longitude)."""

    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)))
    s, n, w, e = (round(v, 4) for v in (lat - dlat, lat + dlat, lon - dlon, lon + dlon))
    return f"POLYGON(({s} {w},{s} {e},{n} {e},{n} {w},{s} {w}))"


def _series(item: dict[str, Any]) -> Series:
    resolutions = sorted(
        {
            RESOLUTION_NAMES[r["resTime"]]
            for r in item.get("resolutionList") or []
            if r.get("resTime") in RESOLUTION_NAMES
        },
        key=list(RESOLUTIONS).index,
    )
    starts = [_date(r.get("dataFromTime")) for r in item.get("resolutionList") or []]
    ends = [_date(r.get("dataToTime")) for r in item.get("resolutionList") or []]
    return Series(
        parameter=item["parameter"],
        alias=ALIAS_OF.get(item["parameter"]),
        name=item.get("parameterName") or str(item["parameter"]),
        unit=item.get("unit"),
        resolutions=resolutions,  # type: ignore[arg-type]
        data_from=min((d for d in starts if d), default=None),
        data_to=max((d for d in ends if d), default=None),
    )


def _station(item: dict[str, Any], origin: tuple[float, float] | None) -> Station:
    lat, lon = item.get("latitude"), item.get("longitude")
    floods = [item.get(k) for k in ("culQm", "culQ5", "culQ10", "culQ20", "culQ50")]
    return Station(
        id=item["stationId"],
        name=item.get("stationName") or item["stationId"],
        river=item.get("riverName") or None,
        lake=item.get("lakeName") or None,
        municipality_code=item.get("councilNumber"),
        municipality=item.get("councilName"),
        county=item.get("countyName"),
        lat=lat,
        lon=lon,
        elevation_m=item.get("masl"),
        distance_km=round(_distance_km(*origin, lat, lon), 2)
        if origin and lat is not None and lon is not None
        else None,
        catchment_km2=item.get("drainageBasinArea"),
        regulation=item.get("catchmentRegTypeName"),
        active=item.get("stationStatusName") == "Aktiv",
        series=[_series(s) for s in item.get("seriesList") or []],
        flood_statistics=FloodStatistics(
            mean_annual=floods[0],
            return_5y=floods[1],
            return_10y=floods[2],
            return_20y=floods[3],
            return_50y=floods[4],
        )
        if any(v is not None for v in floods)
        else None,
    )


# --- water_find_stations -----------------------------------------------------------


async def find_stations(ctx: Context, args: FindStationsInput) -> Result[FindStationsOutput]:
    up = _upstream(ctx)
    # HydAPI's Active flag reads backwards: 0 returns active stations only, 1 returns all.
    params: dict[str, Any] = {"Active": 1 if args.include_closed else 0}
    if args.station:
        params["StationId"] = args.station
    if args.name:
        params["StationName"] = args.name
    if args.municipality:
        params["CouncilNumber"] = args.municipality
    if args.county:
        params["CountyName"] = args.county
    origin = None
    if args.lat is not None and args.lon is not None:
        origin = (args.lat, args.lon)
        params["Polygon"] = _square(args.lat, args.lon, args.radius_km)
    try:
        fetched = await up.get_json(f"{BASE_URL}/Stations", params=params, ttl="stations")
    except UpstreamClientError as exc:
        if exc.status != 404:
            raise
        return Result(
            data=FindStationsOutput(total_matches=0, stations=[]),
            provenance=[],
            notes=["No station matched."],
        )

    stations = [_station(item, origin) for item in fetched.json.get("data") or []]
    if args.parameter:
        wanted = _parameter(args.parameter)
        stations = [s for s in stations if any(series.parameter == wanted for series in s.series)]
    if origin:
        stations = [
            s for s in stations if s.distance_km is not None and s.distance_km <= args.radius_km
        ]
        stations.sort(key=lambda s: s.distance_km or 0)
    notes = list(fetched.notes)
    if args.parameter and _parameter(args.parameter) < 0:
        notes.append(
            f"'{args.parameter}' is not a known parameter name; use a number or one of {', '.join(PARAMETER_ALIASES)}."
        )
    return Result(
        data=FindStationsOutput(total_matches=len(stations), stations=stations[: args.limit]),
        provenance=[up.provenance(fetched, title="HydAPI stations")],
        notes=notes,
    )


# --- water_observations ------------------------------------------------------------


async def observations(ctx: Context, args: ObservationsInput) -> Result[ObservationsOutput]:
    up = _upstream(ctx)
    parameter = _parameter(args.parameter)
    if parameter < 0:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"'{args.parameter}' is not a known parameter. Use one of {', '.join(PARAMETER_ALIASES)}, "
            "or a HydAPI parameter number.",
            next_call=NextCall(tool="water_find_stations", arguments={"station": args.station}),
            source_id=SPEC.id,
        )
    params: dict[str, Any] = {
        "StationId": args.station,
        "Parameter": parameter,
        "ResolutionTime": RESOLUTIONS[args.resolution],
    }
    ttl = "recent"
    if args.start is not None and args.end is not None:
        start, end = as_utc(args.start), as_utc(args.end)
        params["ReferenceTime"] = f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}"
        if end < dt.datetime.now(dt.UTC) - RECENT:
            ttl = "historic"
    try:
        fetched = await up.get_json(f"{BASE_URL}/Observations", params=params, ttl=ttl)
    except UpstreamClientError as exc:
        if exc.status == 404:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"Station {args.station} has no {args.resolution} series for {args.parameter}. "
                "Its series and their resolutions are listed by water_find_stations.",
                next_call=NextCall(tool="water_find_stations", arguments={"station": args.station}),
                source_id=SPEC.id,
                upstream_status=404,
            ) from None
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"HydAPI rejected the request: {exc.detail}. A long period at a fine resolution can "
            "exceed its limit on data points; try a shorter period or a coarser resolution.",
            source_id=SPEC.id,
            upstream_status=exc.status,
        ) from None

    series = (fetched.json.get("data") or [{}])[0]
    rows: list[Reading] = []
    truncated = False
    for obs in series.get("observations") or []:
        if obs.get("value") is None:
            continue
        if len(rows) >= args.max_rows:
            truncated = True
            break
        rows.append(
            Reading(
                time=dt.datetime.fromisoformat(obs["time"]),
                value=obs["value"],
                quality=QUALITY.get(obs.get("quality"), "unknown"),  # type: ignore[arg-type]
                corrected=bool(obs.get("correction")),
            )
        )
    notes = list(fetched.notes)
    if any(r.quality == "uncontrolled" for r in rows):
        notes.append(
            "Some values are uncontrolled: NVE has not checked them yet, and they can change."
        )
    if truncated:
        notes.append(f"Only the first {args.max_rows} values are included.")
    if args.start is None:
        notes.append("No period was given, so only the latest value is returned.")
    return Result(
        data=ObservationsOutput(
            station=args.station,
            station_name=series.get("stationName"),
            parameter=parameter,
            parameter_name=series.get("parameterNameEng") or series.get("parameterName"),
            unit=series.get("unit"),
            method=series.get("method"),
            row_count=len(rows),
            rows=rows,
        ),
        provenance=[up.provenance(fetched, title=f"HydAPI observations, station {args.station}")],
        notes=notes,
        truncated=truncated,
    )


OPERATIONS = (
    Operation(
        name="water_find_stations",
        title="Find hydrological stations",
        description=(
            "Find NVE's river, lake, snow and groundwater stations by name, municipality code, "
            "county, or distance from a point, optionally only those measuring a given parameter "
            "(e.g. 'discharge'). Each station lists its series with available resolutions and "
            "years, plus catchment size and flood statistics (mean annual and 5- to 50-year floods)."
        ),
        input_model=FindStationsInput,
        output_model=FindStationsOutput,
        handler=find_stations,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/water/stations",
        examples=(
            {"name": "Bulken"},
            {"lat": 60.63, "lon": 6.42, "radius_km": 15, "parameter": "discharge"},
        ),
    ),
    Operation(
        name="water_observations",
        title="Observed river and lake data",
        description=(
            "Measured hydrology at an NVE station: discharge, water level, water temperature, "
            "snow, groundwater and more, as daily or hourly means or raw readings. Leave out "
            "start and end for the latest value. Each value says whether NVE has quality-checked it."
        ),
        input_model=ObservationsInput,
        output_model=ObservationsOutput,
        handler=observations,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/water/observations",
        examples=(
            {
                "station": "62.5.0",
                "parameter": "discharge",
                "start": "2026-10-01",
                "end": "2026-10-08",
            },
            {"station": "62.5.0", "parameter": "water_level", "resolution": "hourly"},
        ),
    ),
)
