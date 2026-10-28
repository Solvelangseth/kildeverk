"""Weather tools: MET Norway's Locationforecast for forecasts, Frost for stations and observations."""

from __future__ import annotations

import datetime as dt
from typing import Any

from kildeverk.context import Context
from kildeverk.core.envelope import Licence, Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import Fetched, Upstream, UpstreamClientError
from kildeverk.sources.met.models import (
    ELEMENT_ALIASES,
    ElementSeries,
    FindStationsInput,
    FindStationsOutput,
    ForecastInput,
    ForecastOutput,
    ForecastPoint,
    Location,
    Observation,
    ObservationsInput,
    ObservationsOutput,
    Station,
    StationElementsInput,
    StationElementsOutput,
    as_utc,
)
from kildeverk.sources.met.spec import (
    COORDINATE_DECIMALS,
    FORECAST_URL,
    FROST,
    FROST_CC_BY_3_NO,
    FROST_CREDENTIALS_URL,
    FROST_URL,
    LOCATIONFORECAST,
)

# Observations ending later than this are still changing upstream, so they are cached briefly.
RECENT = dt.timedelta(days=2)


def _parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(value: Any) -> dt.date | None:
    parsed = _parse_time(value)
    return parsed.date() if parsed else None


def _coordinate(value: float) -> str:
    return f"{round(value, COORDINATE_DECIMALS):.{COORDINATE_DECIMALS}f}".rstrip("0").rstrip(".")


# --- weather_forecast -------------------------------------------------------------


async def forecast(ctx: Context, args: ForecastInput) -> Result[ForecastOutput]:
    up = ctx.upstream(LOCATIONFORECAST.id)
    params: dict[str, Any] = {"lat": _coordinate(args.lat), "lon": _coordinate(args.lon)}
    if args.altitude_m is not None:
        params["altitude"] = args.altitude_m
    try:
        fetched = await up.get_json(FORECAST_URL, params=params, ttl="forecast")
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"MET could not make a forecast for that point: {exc.detail}",
            source_id=LOCATIONFORECAST.id,
            upstream_status=exc.status,
        ) from None

    body = fetched.json
    properties = body["properties"]
    steps = properties.get("timeseries") or []
    first = _parse_time(steps[0]["time"]) if steps else None
    points = []
    for step in steps:
        time = _parse_time(step["time"])
        if time is None or first is None or time > first + dt.timedelta(hours=args.hours):
            break
        data = step.get("data") or {}
        instant = (data.get("instant") or {}).get("details") or {}
        precipitation, period, symbol = None, None, None
        for key, hours in (("next_1_hours", 1), ("next_6_hours", 6), ("next_12_hours", 12)):
            block = data.get(key)
            if not block:
                continue
            amount = (block.get("details") or {}).get("precipitation_amount")
            if precipitation is None and amount is not None:
                precipitation, period = amount, hours
            symbol = symbol or (block.get("summary") or {}).get("symbol_code")
        points.append(
            ForecastPoint(
                time=time,
                temperature_c=instant.get("air_temperature"),
                wind_speed_ms=instant.get("wind_speed"),
                wind_from_deg=instant.get("wind_from_direction"),
                humidity_pct=instant.get("relative_humidity"),
                cloud_pct=instant.get("cloud_area_fraction"),
                pressure_hpa=instant.get("air_pressure_at_sea_level"),
                precipitation_mm=precipitation,
                precipitation_hours=period,
                symbol=symbol,
            )
        )

    lon, lat, *altitude = (body.get("geometry") or {}).get("coordinates") or [None, None]
    notes = list(fetched.notes)
    notes.append(
        f"Coordinates were rounded to {COORDINATE_DECIMALS} decimals. Steps are hourly at first "
        "and 6-hourly later; each precipitation value covers its own precipitation_hours, so "
        "add up only non-overlapping periods."
    )
    return Result(
        data=ForecastOutput(
            location=Location(lat=lat, lon=lon, altitude_m=altitude[0] if altitude else None),
            updated_at=_parse_time((properties.get("meta") or {}).get("updated_at")),
            points=points,
        ),
        provenance=[up.provenance(fetched, title=f"Locationforecast 2.0 for {lat}, {lon}")],
        notes=notes,
    )


# --- Frost helpers ------------------------------------------------------------------


def _frost(ctx: Context) -> Upstream:
    up = ctx.upstream(FROST.id)
    if up.auth is None:
        raise ToolError(
            ErrorCode.NOT_CONFIGURED,
            "Station data needs a Frost client id, and none is configured here. Get one free "
            f"at {FROST_CREDENTIALS_URL} and set KILDEVERK_FROST_CLIENT_ID. "
            "weather_forecast works without it.",
            source_id=FROST.id,
        )
    return up


def _licence(fetched: Fetched) -> Licence:
    stated = fetched.json.get("license") if isinstance(fetched.json, dict) else None
    if not stated or stated == FROST_CC_BY_3_NO.url:
        return FROST_CC_BY_3_NO
    return Licence(id="as-stated", name=f"As stated by Frost: {stated}", url=stated)


def _station(item: dict[str, Any]) -> Station:
    coordinates = (item.get("geometry") or {}).get("coordinates") or [None, None]
    municipality_id = item.get("municipalityId")
    return Station(
        id=item["id"],
        name=item.get("name") or item["id"],
        municipality=item.get("municipality"),
        municipality_code=f"{municipality_id:04d}" if isinstance(municipality_id, int) else None,
        county=item.get("county"),
        lat=coordinates[1],
        lon=coordinates[0],
        elevation_m=item.get("masl"),
        distance_km=round(item["distance"], 2)
        if isinstance(item.get("distance"), float | int)
        else None,
        valid_from=_parse_date(item.get("validFrom")),
        valid_to=_parse_date(item.get("validTo")),
        operators=item.get("stationHolders") or [],
    )


# --- weather_find_stations --------------------------------------------------------


async def find_stations(ctx: Context, args: FindStationsInput) -> Result[FindStationsOutput]:
    up = _frost(ctx)
    params: dict[str, Any] = {"types": "SensorSystem"}
    # Closed stations are filtered out here, so ask for more than needed.
    wanted = args.limit if args.include_closed else min(100, args.limit * 4)
    if args.name is not None:
        params["name"] = f"*{args.name}*"
        title = f'Frost stations named like "{args.name}"'
    else:
        params["geometry"] = f"nearest(POINT({_coordinate(args.lon)} {_coordinate(args.lat)}))"
        params["nearestmaxcount"] = wanted
        title = f"Frost stations nearest {_coordinate(args.lat)}, {_coordinate(args.lon)}"
    try:
        fetched = await up.get_json(f"{FROST_URL}/sources/v0.jsonld", params=params, ttl="stations")
    except UpstreamClientError as exc:
        if exc.status != 404:
            raise
        return Result(
            data=FindStationsOutput(stations=[]),
            provenance=[],
            notes=["Frost found no station matching that search."],
        )
    stations = [_station(item) for item in fetched.json.get("data") or []]
    if not args.include_closed:
        stations = [s for s in stations if s.valid_to is None]
    return Result(
        data=FindStationsOutput(stations=stations[: args.limit]),
        provenance=[up.provenance(fetched, title=title, licence=_licence(fetched))],
        notes=list(fetched.notes),
    )


# --- weather_station_elements -----------------------------------------------------


async def station_elements(
    ctx: Context, args: StationElementsInput
) -> Result[StationElementsOutput]:
    up = _frost(ctx)
    try:
        fetched = await up.get_json(
            f"{FROST_URL}/observations/availableTimeSeries/v0.jsonld",
            params={"sources": args.station},
            ttl="series",
        )
    except UpstreamClientError as exc:
        if exc.status not in (404, 412):
            raise
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Frost has no open time series for station {args.station}. Check the id with "
            "weather_find_stations.",
            source_id=FROST.id,
            upstream_status=exc.status,
        ) from None

    grouped: dict[str, dict[str, Any]] = {}
    for series in fetched.json.get("data") or []:
        element = series.get("elementId")
        if not element:
            continue
        if args.element_search and args.element_search.casefold() not in element.casefold():
            continue
        entry = grouped.setdefault(
            element,
            {
                "unit": series.get("unit"),
                "resolutions": set(),
                "from": None,
                "to": None,
                "open": False,
            },
        )
        if series.get("timeResolution"):
            entry["resolutions"].add(series["timeResolution"])
        start, end = _parse_date(series.get("validFrom")), _parse_date(series.get("validTo"))
        if start and (entry["from"] is None or start < entry["from"]):
            entry["from"] = start
        if end is None:
            entry["open"] = True
        elif entry["to"] is None or end > entry["to"]:
            entry["to"] = end

    elements = [
        ElementSeries(
            element=element,
            unit=entry["unit"],
            resolutions=sorted(entry["resolutions"]),
            available_from=entry["from"],
            available_to=None if entry["open"] else entry["to"],
        )
        for element, entry in sorted(grouped.items())
    ]
    return Result(
        data=StationElementsOutput(station=args.station, elements=elements),
        provenance=[
            up.provenance(
                fetched, title=f"Frost time series for {args.station}", licence=_licence(fetched)
            )
        ],
        notes=list(fetched.notes),
    )


# --- weather_observations ---------------------------------------------------------


async def observations(ctx: Context, args: ObservationsInput) -> Result[ObservationsOutput]:
    up = _frost(ctx)
    requested = {name: ELEMENT_ALIASES.get(name, name) for name in args.elements}
    by_id = {element_id: name for name, element_id in requested.items()}
    start, end = as_utc(args.start), as_utc(args.end)
    period = f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}"
    recent = end > dt.datetime.now(dt.UTC) - RECENT
    try:
        fetched = await up.get_json(
            f"{FROST_URL}/observations/v0.jsonld",
            params={
                "sources": args.station,
                "elements": ",".join(requested.values()),
                "referencetime": period,
                # One standard series per element. Without these Frost also returns
                # alternatives, such as precipitation summed from 18 UTC as well as 06 UTC.
                "timeoffsets": "default",
                "levels": "default",
            },
            ttl="recent" if recent else "historic",
        )
    except UpstreamClientError as exc:
        lookup = NextCall(tool="weather_station_elements", arguments={"station": args.station})
        if exc.status == 412:
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"Station {args.station} has no series for {', '.join(requested.values())}. "
                "See which elements it measures.",
                next_call=lookup,
                source_id=FROST.id,
                upstream_status=412,
            ) from None
        if exc.status == 404:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"No observations from {args.station} in that period: {exc.detail}",
                next_call=lookup,
                source_id=FROST.id,
                upstream_status=404,
            ) from None
        raise

    rows: list[Observation] = []
    truncated = False
    for item in fetched.json.get("data") or []:
        time = _parse_time(item.get("referenceTime"))
        for obs in item.get("observations") or []:
            if time is None or obs.get("value") is None:
                continue
            if len(rows) >= args.max_rows:
                truncated = True
                break
            level = obs.get("level") or {}
            rows.append(
                Observation(
                    time=time,
                    element=by_id.get(obs.get("elementId"), obs.get("elementId", "")),
                    value=obs["value"],
                    unit=obs.get("unit"),
                    resolution=obs.get("timeResolution"),
                    time_offset=obs.get("timeOffset"),
                    level_m=level.get("value")
                    if level.get("levelType") == "height_above_ground"
                    else None,
                    quality_code=obs.get("qualityCode"),
                )
            )
        if truncated:
            break

    notes = list(fetched.notes)
    if truncated:
        notes.append(
            f"Only the first {args.max_rows} observations are included; shorten the period for the rest."
        )
    notes.append(
        "Each element is MET's default series. A period starts at time + time_offset, so daily "
        "precipitation with offset PT6H runs 06 UTC to 06 UTC. quality_code 0 means checked "
        "and OK; see https://frost.met.no/dataclarifications.html."
    )
    return Result(
        data=ObservationsOutput(
            station=args.station, elements=requested, row_count=len(rows), rows=rows
        ),
        provenance=[
            up.provenance(
                fetched,
                title=f"Frost observations from {args.station}, {period}",
                licence=_licence(fetched),
            )
        ],
        notes=notes,
        truncated=truncated,
    )


OPERATIONS = (
    Operation(
        name="weather_forecast",
        title="Weather forecast for a point",
        description=(
            "Forecast from MET Norway for any latitude and longitude: temperature, precipitation, "
            "wind, cloud, humidity, pressure and a weather symbol. Hourly for about the first 2.5 "
            "days, then 6-hourly up to 10 days. Needs no configuration."
        ),
        input_model=ForecastInput,
        output_model=ForecastOutput,
        handler=forecast,
        source_ids=(LOCATIONFORECAST.id,),
        http_method="GET",
        http_path="/v1/weather/forecast",
        examples=(
            {"lat": 60.3913, "lon": 5.3221, "hours": 24},
            {"lat": 69.6496, "lon": 18.956, "altitude_m": 10},
        ),
    ),
    Operation(
        name="weather_find_stations",
        title="Find weather stations",
        description=(
            "Find MET Norway weather stations nearest a point, or by name. Returns station ids "
            "for weather_station_elements and weather_observations, with location, elevation and "
            "operator. Closed stations are left out unless asked for."
        ),
        input_model=FindStationsInput,
        output_model=FindStationsOutput,
        handler=find_stations,
        source_ids=(FROST.id,),
        http_method="GET",
        http_path="/v1/weather/stations",
        examples=({"lat": 60.3913, "lon": 5.3221, "limit": 3}, {"name": "Blindern"}),
    ),
    Operation(
        name="weather_station_elements",
        title="What a weather station measures",
        description=(
            "List what a MET Norway station measures (temperature, precipitation, snow depth and "
            "so on), at which time resolutions, and over which years. Use the element ids it "
            "returns in weather_observations."
        ),
        input_model=StationElementsInput,
        output_model=StationElementsOutput,
        handler=station_elements,
        source_ids=(FROST.id,),
        http_method="GET",
        http_path="/v1/weather/stations/{station}/elements",
        examples=({"station": "SN50540", "element_search": "precipitation"},),
    ),
    Operation(
        name="weather_observations",
        title="Observed weather at a station",
        description=(
            "Measured weather from a MET Norway station over a period: hourly readings or daily "
            "and monthly aggregates, back to when the station opened. Use friendly element names "
            "like 'daily_mean_temperature' or 'daily_precipitation', or any Frost element id."
        ),
        input_model=ObservationsInput,
        output_model=ObservationsOutput,
        handler=observations,
        source_ids=(FROST.id,),
        http_method="GET",
        http_path="/v1/weather/observations",
        examples=(
            {
                "station": "SN50540",
                "elements": ["daily_mean_temperature", "daily_precipitation"],
                "start": "2026-10-01",
                "end": "2026-10-08",
            },
        ),
    ),
)
