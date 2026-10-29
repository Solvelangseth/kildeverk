"""Climate normals from Frost, and how a year's months compared with them."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.met.models import StationId
from kildeverk.sources.met.ops import _frost, _licence
from kildeverk.sources.met.spec import FROST, FROST_URL

TEMPERATURE = "mean(air_temperature P1M)"
PRECIPITATION = "sum(precipitation_amount P1M)"
YEAR_TEMPERATURE = "mean(air_temperature P1Y)"
YEAR_PRECIPITATION = "sum(precipitation_amount P1Y)"


class NormalsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station: StationId
    period: Literal["1991/2020", "1961/1990", "1931/1960"] = Field(
        default="1991/2020", description="The 30-year normal period; 1991-2020 is the current one."
    )
    year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Compare this year's months with the normal: observed mean temperature and "
        "precipitation, the temperature difference and precipitation as per cent of normal.",
    )


class Month(BaseModel):
    month: int
    normal_temperature_c: float | None
    normal_precipitation_mm: float | None
    observed_temperature_c: float | None = None
    temperature_anomaly_c: float | None = Field(
        default=None, description="Observed minus normal; positive is warmer than normal."
    )
    observed_precipitation_mm: float | None = None
    precipitation_pct_of_normal: float | None = None
    complete: bool | None = Field(default=None, description="False for the month still under way.")


class NormalsOutput(BaseModel):
    station: str
    period: str
    year: int | None
    year_normal_temperature_c: float | None
    year_normal_precipitation_mm: float | None
    months: list[Month]


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


async def normals(ctx: Context, args: NormalsInput) -> Result[NormalsOutput]:
    up = _frost(ctx)
    station = args.station.split(":")[0]
    try:
        fetched = await up.get_json(
            f"{FROST_URL}/climatenormals/v0.jsonld",
            params={
                "sources": station,
                "elements": f"{TEMPERATURE},{PRECIPITATION},{YEAR_TEMPERATURE},{YEAR_PRECIPITATION}",
                "period": args.period,
            },
            ttl="stations",
        )
    except UpstreamClientError as exc:
        if exc.status not in (400, 404, 412):
            raise
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Frost has no {args.period} normals for {station}. Normals exist only for stations "
            "with long records; find one nearby that has them.",
            next_call=NextCall(tool="weather_find_stations", arguments={"name": "Blindern"}),
            source_id=FROST.id,
            upstream_status=exc.status,
        ) from None

    by_month: dict[int, dict[str, float]] = {}
    year_values: dict[str, float] = {}
    for item in fetched.json.get("data") or []:
        element, value = item.get("elementId"), item.get("normal")
        if item.get("month"):
            by_month.setdefault(int(item["month"]), {})[element] = value
        else:
            year_values[element] = value
    if not by_month and not year_values:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Frost has no {args.period} temperature or precipitation normals for {station}.",
            next_call=NextCall(tool="weather_station_elements", arguments={"station": station}),
            source_id=FROST.id,
        )
    months = [
        Month(
            month=m,
            normal_temperature_c=by_month.get(m, {}).get(TEMPERATURE),
            normal_precipitation_mm=by_month.get(m, {}).get(PRECIPITATION),
        )
        for m in range(1, 13)
    ]
    provenance = [
        up.provenance(
            fetched,
            title=f"Frost climate normals {args.period} for {station}",
            licence=_licence(fetched),
        )
    ]
    notes = list(fetched.notes)

    if args.year is not None:
        today = _today()
        if args.year > today.year:
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"{args.year} has not begun.",
                next_call=NextCall(tool="weather_normals", arguments={"station": station}),
            )
        try:
            observed = await up.get_json(
                f"{FROST_URL}/observations/v0.jsonld",
                params={
                    "sources": station,
                    "elements": f"{TEMPERATURE},{PRECIPITATION}",
                    "referencetime": f"{args.year}-01-01/{args.year + 1}-01-01",
                    "timeoffsets": "default",
                    "levels": "default",
                },
                ttl="recent" if args.year >= today.year - 1 else "historic",
            )
        except UpstreamClientError as exc:
            # 404 (no data that year) and 412 (no such monthly series) leave the normals alone.
            if exc.status not in (404, 412):
                raise
            observed = None
        values: dict[int, dict[str, float]] = {}
        for item in ((observed.json or {}) if observed else {}).get("data") or []:
            month = int(item["referenceTime"][5:7])
            for o in item.get("observations") or []:
                values.setdefault(month, {})[o["elementId"]] = o.get("value")
        for row in months:
            seen = values.get(row.month, {})
            row.observed_temperature_c = seen.get(TEMPERATURE)
            row.observed_precipitation_mm = seen.get(PRECIPITATION)
            if row.observed_temperature_c is not None and row.normal_temperature_c is not None:
                row.temperature_anomaly_c = round(
                    row.observed_temperature_c - row.normal_temperature_c, 1
                )
            if row.observed_precipitation_mm is not None and row.normal_precipitation_mm:
                row.precipitation_pct_of_normal = round(
                    row.observed_precipitation_mm / row.normal_precipitation_mm * 100
                )
            if seen:
                row.complete = (args.year, row.month) < (today.year, today.month)
        if observed:
            provenance.append(
                up.provenance(
                    observed,
                    title=f"Frost monthly observations {args.year} for {station}",
                    licence=_licence(observed),
                )
            )
            notes.extend(observed.notes)
        if not values:
            notes.append(
                f"Frost has no monthly temperature or precipitation for {station} in {args.year}."
            )
        if any(row.complete is False for row in months):
            notes.append("The current month is not over, so its observed values are partial.")
    notes.append(
        "Normals are 30-year averages of monthly mean temperature and monthly precipitation."
    )
    return Result(
        data=NormalsOutput(
            station=station,
            period=args.period,
            year=args.year,
            year_normal_temperature_c=year_values.get(YEAR_TEMPERATURE),
            year_normal_precipitation_mm=year_values.get(YEAR_PRECIPITATION),
            months=months,
        ),
        provenance=provenance,
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="weather_normals",
        title="Climate normals at a weather station",
        description=(
            "The 30-year climate normals at a MET Norway weather station from Frost: monthly and "
            "yearly mean temperature and precipitation for 1991-2020 (or 1961-1990, 1931-1960). "
            "Give a year to compare its months with the normal, to answer whether a month was "
            "warmer or wetter than usual. Normals exist only for stations with long records; "
            "find station ids with weather_find_stations."
        ),
        input_model=NormalsInput,
        output_model=NormalsOutput,
        handler=normals,
        source_ids=(FROST.id,),
        http_method="GET",
        http_path="/v1/weather/stations/{station}/normals",
        examples=(
            {"station": "SN18700"},
            {"station": "SN50540", "year": 2025},
        ),
    ),
)
