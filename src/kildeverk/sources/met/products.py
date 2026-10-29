"""MET Norway's nowcast, ocean forecast and air quality forecast for a point."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.met.models import Latitude, Location, Longitude
from kildeverk.sources.met.ops import _coordinate, _parse_time
from kildeverk.sources.met.spec import (
    AIRQUALITY,
    AIRQUALITY_URL,
    COORDINATE_DECIMALS,
    NOWCAST,
    NOWCAST_URL,
    OCEANFORECAST,
    OCEANFORECAST_URL,
)


class PointInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: Latitude
    lon: Longitude


def _point(geometry: Any) -> Location:
    lon, lat, *altitude = (geometry or {}).get("coordinates") or [None, None]
    return Location(lat=lat, lon=lon, altitude_m=altitude[0] if altitude else None)


# --- weather_nowcast ---------------------------------------------------------------


class NowcastStep(BaseModel):
    time: dt.datetime
    precipitation_mm_per_h: float | None


class Now(BaseModel):
    temperature_c: float | None
    feels_like_c: float | None
    wind_speed_ms: float | None
    wind_gust_ms: float | None
    wind_from_deg: float | None
    humidity_pct: float | None
    symbol: str | None


class NowcastOutput(BaseModel):
    location: Location
    updated_at: dt.datetime | None
    radar_coverage: str | None = Field(
        description="'ok', or MET's word for reduced or no coverage, which makes the "
        "precipitation less reliable."
    )
    now: Now
    raining_now: bool
    rain_starts_at: dt.datetime | None = Field(
        description="When it is dry now: the first wet step."
    )
    rain_stops_at: dt.datetime | None = Field(description="When it is wet now: the first dry step.")
    max_mm_per_h: float | None
    next_hour_mm: float | None
    steps: list[NowcastStep] = Field(description="Every five minutes for about two hours.")


WET_MM_PER_H = 0.1


async def nowcast(ctx: Context, args: PointInput) -> Result[NowcastOutput]:
    up = ctx.upstream(NOWCAST.id)
    try:
        fetched = await up.get_json(
            NOWCAST_URL,
            params={"lat": _coordinate(args.lat), "lon": _coordinate(args.lon)},
            ttl="nowcast",
        )
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            "MET's nowcast covers only the Nordic area, and this point is outside it."
            if exc.status == 422
            else f"MET could not make a nowcast for that point: {exc.detail}",
            next_call=NextCall(
                tool="weather_forecast", arguments={"lat": args.lat, "lon": args.lon}
            ),
            source_id=NOWCAST.id,
            upstream_status=exc.status,
        ) from None

    properties = fetched.json["properties"]
    series = properties.get("timeseries") or []
    first = (series[0].get("data") or {}) if series else {}
    instant = (first.get("instant") or {}).get("details") or {}
    hour = first.get("next_1_hours") or {}
    steps = [
        NowcastStep(
            time=_parse_time(step["time"]),  # type: ignore[arg-type]
            precipitation_mm_per_h=((step.get("data") or {}).get("instant") or {})
            .get("details", {})
            .get("precipitation_rate"),
        )
        for step in series
    ]
    rates = [s.precipitation_mm_per_h or 0.0 for s in steps]
    raining = bool(rates) and rates[0] >= WET_MM_PER_H
    change = next(
        (s.time for s, r in zip(steps, rates, strict=True) if (r >= WET_MM_PER_H) != raining), None
    )
    coverage = (properties.get("meta") or {}).get("radar_coverage")
    notes = list(fetched.notes)
    notes.append(
        f"Coordinates were rounded to {COORDINATE_DECIMALS} decimals. Rates are mm per hour at "
        f"each step; a step counts as wet from {WET_MM_PER_H} mm/h."
    )
    if coverage and coverage != "ok":
        notes.append(f"Radar coverage is '{coverage}', so the precipitation is less reliable.")
    return Result(
        data=NowcastOutput(
            location=_point(fetched.json.get("geometry")),
            updated_at=_parse_time((properties.get("meta") or {}).get("updated_at")),
            radar_coverage=coverage,
            now=Now(
                temperature_c=instant.get("air_temperature"),
                feels_like_c=instant.get("apparent_air_temperature"),
                wind_speed_ms=instant.get("wind_speed"),
                wind_gust_ms=instant.get("wind_speed_of_gust"),
                wind_from_deg=instant.get("wind_from_direction"),
                humidity_pct=instant.get("relative_humidity"),
                symbol=(hour.get("summary") or {}).get("symbol_code"),
            ),
            raining_now=raining,
            rain_starts_at=None if raining else change,
            rain_stops_at=change if raining else None,
            max_mm_per_h=max(rates) if rates else None,
            next_hour_mm=(hour.get("details") or {}).get("precipitation_amount"),
            steps=steps,
        ),
        provenance=[
            up.provenance(
                fetched, title=f"Nowcast 2.0 for {_coordinate(args.lat)}, {_coordinate(args.lon)}"
            )
        ],
        notes=notes,
    )


# --- sea_forecast ------------------------------------------------------------------


class SeaInput(PointInput):
    hours: int = Field(default=48, ge=1, le=200, description="How far ahead, from the first step.")


class SeaStep(BaseModel):
    time: dt.datetime
    wave_height_m: float | None
    wave_from_deg: float | None = Field(description="Direction the waves come from, 0 = north.")
    sea_temperature_c: float | None
    current_speed_ms: float | None
    current_to_deg: float | None = Field(description="Direction the current flows towards.")


class SeaOutput(BaseModel):
    grid_point: Location = Field(description="The sea point the forecast is for.")
    updated_at: dt.datetime | None
    highest_waves_m: float | None
    highest_waves_at: dt.datetime | None
    steps: list[SeaStep] = Field(description="Hourly.")


async def sea_forecast(ctx: Context, args: SeaInput) -> Result[SeaOutput]:
    up = ctx.upstream(OCEANFORECAST.id)
    try:
        fetched = await up.get_json(
            OCEANFORECAST_URL,
            params={"lat": _coordinate(args.lat), "lon": _coordinate(args.lon)},
            ttl="ocean",
        )
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"MET could not make an ocean forecast for that point: {exc.detail}",
            source_id=OCEANFORECAST.id,
            upstream_status=exc.status,
        ) from None
    properties = fetched.json.get("properties") or {}
    meta = properties.get("meta") or {}
    series = properties.get("timeseries") or []
    if not series:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            "MET has no ocean forecast at this point: it is on land or too far into a fjord. "
            "Try a point further out at sea.",
            source_id=OCEANFORECAST.id,
        )
    start = _parse_time(series[0]["time"])
    steps = []
    for step in series:
        time = _parse_time(step["time"])
        if time is None or start is None or time > start + dt.timedelta(hours=args.hours):
            break
        d = ((step.get("data") or {}).get("instant") or {}).get("details") or {}
        steps.append(
            SeaStep(
                time=time,
                wave_height_m=d.get("sea_surface_wave_height"),
                wave_from_deg=d.get("sea_surface_wave_from_direction"),
                sea_temperature_c=d.get("sea_water_temperature"),
                current_speed_ms=d.get("sea_water_speed"),
                current_to_deg=d.get("sea_water_to_direction"),
            )
        )
    waves = [s for s in steps if s.wave_height_m is not None]
    highest = max(waves, key=lambda s: s.wave_height_m or 0.0, default=None)
    grid = _point(fetched.json.get("geometry"))
    notes = list(fetched.notes)
    notes.append(
        "Wave height is the significant wave height: the average of the highest third of the "
        "waves. Single waves can be about twice as high."
    )
    return Result(
        data=SeaOutput(
            grid_point=grid,
            updated_at=_parse_time(meta.get("updated_at")),
            highest_waves_m=highest.wave_height_m if highest else None,
            highest_waves_at=highest.time if highest else None,
            steps=steps,
        ),
        provenance=[up.provenance(fetched, title=f"Oceanforecast 2.0 for {grid.lat}, {grid.lon}")],
        notes=notes,
    )


# --- air_quality_forecast ----------------------------------------------------------

POLLUTANTS = {"no2": "NO2", "pm10": "PM10", "pm25": "PM2.5", "o3": "O3"}
# MET's own classes, from its /aqi_description.
LEVELS = (
    (2.0, "low", "little health risk"),
    (3.0, "moderate", "moderate health risk"),
    (
        4.0,
        "high",
        (
            "high health risk: children, pregnant, sick and older people should limit "
            "outdoor activities"
        ),
    ),
    (float("inf"), "very high", "serious health risk: try not to stay outside for longer periods"),
)
SOURCES = {
    "local_fraction_traffic_exhaust": "traffic_exhaust",
    "local_fraction_traffic_nonexhaust": "road_dust_and_wear",
    "local_fraction_heating": "heating",
    "local_fraction_shipping": "shipping",
    "local_fraction_industry": "industry",
    "nonlocal_fraction": "from_elsewhere",
    "nonlocal_fraction_seasalt": "sea_salt",
}


class AirInput(PointInput):
    area: Literal["grunnkrets", "delomrade", "kommune"] = Field(
        default="grunnkrets",
        description="The area the forecast is for: 'grunnkrets' (the smallest statistical area, "
        "a few streets), 'delomrade' (part of a municipality) or 'kommune' (the municipality).",
    )


class AirArea(BaseModel):
    name: str | None
    area_class: str | None
    area_code: str | None
    path: str | None = Field(description="County/municipality/... down to the area.")


class AirHour(BaseModel):
    time: dt.datetime
    aqi: float | None = Field(description="Air quality index, 1 (clean) to 5.")
    level: str | None = Field(description="low, moderate, high or very high.")
    dominant: str | None = Field(description="The pollutant behind the index this hour.")
    no2_ugm3: float | None
    pm10_ugm3: float | None
    pm25_ugm3: float | None
    o3_ugm3: float | None


class Worst(BaseModel):
    time: dt.datetime
    aqi: float
    level: str
    advice: str
    dominant: str | None
    sources_pct: dict[str, float] = Field(
        description="Where the dominant pollutant comes from, per cent: traffic_exhaust, "
        "road_dust_and_wear, heating (mostly wood burning), shipping, industry, from_elsewhere, "
        "sea_salt."
    )


class AirOutput(BaseModel):
    area: AirArea
    reference_time: dt.datetime | None
    worst: Worst | None
    hours: list[AirHour] = Field(description="Hourly, from the current hour.")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _level(aqi: float) -> tuple[str, str]:
    return next((name, advice) for top, name, advice in LEVELS if aqi < top)


def _value(variables: dict[str, Any], key: str) -> float | None:
    value = (variables.get(key) or {}).get("value")
    return round(value, 2) if isinstance(value, (int, float)) else None


async def air_quality(ctx: Context, args: AirInput) -> Result[AirOutput]:
    up = ctx.upstream(AIRQUALITY.id)
    try:
        fetched = await up.get_json(
            AIRQUALITY_URL,
            params={
                "lat": _coordinate(args.lat),
                "lon": _coordinate(args.lon),
                "areaclass": args.area,
            },
            ttl="air",
        )
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            "MET's air quality forecast covers Norway only, and this point is outside it."
            if exc.status == 400
            else f"MET could not make an air quality forecast for that point: {exc.detail}",
            source_id=AIRQUALITY.id,
            upstream_status=exc.status,
        ) from None

    body = fetched.json
    location = (body.get("meta") or {}).get("location") or {}
    # The list can repeat an hour and is not in order; the last copy of an hour wins.
    by_time: dict[dt.datetime, dict[str, Any]] = {}
    for item in (body.get("data") or {}).get("time") or []:
        time = _parse_time(item.get("from"))
        if time is not None:
            by_time[time] = item.get("variables") or {}
    now = _now().replace(minute=0, second=0, microsecond=0)
    hours: list[AirHour] = []
    worst_vars: tuple[dt.datetime, dict[str, Any]] | None = None
    for time in sorted(t for t in by_time if t >= now):
        variables = by_time[time]
        aqi = _value(variables, "AQI")
        sub = {name: _value(variables, f"AQI_{name}") for name in POLLUTANTS}
        dominant = max(
            (n for n in sub if sub[n] is not None), key=lambda n: sub[n] or 0.0, default=None
        )
        hours.append(
            AirHour(
                time=time,
                aqi=aqi,
                level=_level(aqi)[0] if aqi is not None else None,
                dominant=POLLUTANTS[dominant] if dominant else None,
                no2_ugm3=_value(variables, "no2_concentration"),
                pm10_ugm3=_value(variables, "pm10_concentration"),
                pm25_ugm3=_value(variables, "pm25_concentration"),
                o3_ugm3=_value(variables, "o3_concentration"),
            )
        )
        if aqi is not None and (worst_vars is None or aqi > (_value(worst_vars[1], "AQI") or 0)):
            worst_vars = (time, variables)

    worst = None
    if worst_vars:
        time, variables = worst_vars
        hour = next(h for h in hours if h.time == time)
        key = next((k for k, v in POLLUTANTS.items() if v == hour.dominant), None)
        sources = {
            label: value
            for suffix, label in SOURCES.items()
            if key and (value := _value(variables, f"{key}_{suffix}")) is not None and value > 0
        }
        level, advice = _level(hour.aqi or 1.0)
        worst = Worst(
            time=time,
            aqi=hour.aqi or 1.0,
            level=level,
            advice=advice,
            dominant=hour.dominant,
            sources_pct=dict(sorted(sources.items(), key=lambda x: -x[1])),
        )

    notes = list(fetched.notes)
    notes.append(
        "The index runs from 1 to 5: below 2 is low, 2-3 moderate, 3-4 high and 4 or more very "
        "high, as MET classes it. Concentrations are in µg/m³."
    )
    if not hours:
        notes.append("The forecast has no hours from now on; MET may not have published a new run.")
    return Result(
        data=AirOutput(
            area=AirArea(
                name=location.get("name"),
                area_class=location.get("areaclass"),
                area_code=location.get("areacode"),
                path=location.get("path"),
            ),
            reference_time=_parse_time((body.get("meta") or {}).get("reftime")),
            worst=worst,
            hours=hours,
        ),
        provenance=[
            up.provenance(
                fetched, title=f"Airqualityforecast 0.1 for {location.get('name') or 'a point'}"
            )
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="weather_nowcast",
        title="Rain in the next two hours",
        description=(
            "MET Norway's radar nowcast for a point in the Nordic area: precipitation every five "
            "minutes for the next two hours, whether it is raining now and when rain starts or "
            "stops, plus the temperature and wind now. Use weather_forecast for anything beyond "
            "two hours."
        ),
        input_model=PointInput,
        output_model=NowcastOutput,
        handler=nowcast,
        source_ids=(NOWCAST.id,),
        http_method="GET",
        http_path="/v1/weather/nowcast",
        examples=({"lat": 59.9139, "lon": 10.7522}, {"lat": 60.3913, "lon": 5.3221}),
    ),
    Operation(
        name="sea_forecast",
        title="Waves and sea temperature",
        description=(
            "MET Norway's ocean forecast for a point at sea along the Norwegian coast: wave "
            "height and direction, sea temperature, and current speed and direction, hourly for "
            "up to about eight days, with the highest waves ahead. The forecast is for the "
            "nearest sea grid point, which the result gives. For water level and tides, use "
            "sea_level."
        ),
        input_model=SeaInput,
        output_model=SeaOutput,
        handler=sea_forecast,
        source_ids=(OCEANFORECAST.id,),
        http_method="GET",
        http_path="/v1/sea/forecast",
        examples=({"lat": 60.1, "lon": 4.9}, {"lat": 69.7, "lon": 18.6, "hours": 24}),
    ),
    Operation(
        name="air_quality_forecast",
        title="Air quality forecast",
        description=(
            "MET Norway's air quality forecast for a place in Norway, hour by hour for about two "
            "days: the air quality index (low, moderate, high, very high), the pollutant behind "
            "it and the NO2, PM10, PM2.5 and ozone concentrations, plus where the worst hour's "
            "pollution comes from (traffic, road dust, wood burning, shipping, industry or "
            "elsewhere). For the street area, part of the municipality or the municipality at a "
            "point."
        ),
        input_model=AirInput,
        output_model=AirOutput,
        handler=air_quality,
        source_ids=(AIRQUALITY.id,),
        http_method="GET",
        http_path="/v1/air/forecast",
        examples=(
            {"lat": 59.9139, "lon": 10.7522},
            {"lat": 63.4305, "lon": 10.3951, "area": "kommune"},
        ),
    ),
)
