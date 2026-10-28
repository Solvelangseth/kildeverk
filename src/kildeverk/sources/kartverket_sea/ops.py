"""Water level and tides from Kartverket's tide API (XML)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.core.operation import Operation
from kildeverk.sources.kartverket_sea.spec import SPEC, TIDE_URL

OSLO = ZoneInfo("Europe/Oslo")
UTC_PLUS_1 = dt.timezone(dt.timedelta(hours=1))
REFERENCES = {"chart_datum": "cd", "mean_sea_level": "msl", "nn2000": "nn2000"}
MAX_DAYS = {"water_level": 31, "tide_table": 366}
SERIES = ("observation", "prediction", "forecast", "weathereffect")


class SeaLevelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float | None = Field(default=None, ge=57, le=82, description="A point on the coast.")
    lon: float | None = Field(default=None, ge=-11, le=35)
    station: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
        description="Tide gauge code, e.g. 'BGO' (Bergen). Results for a point name the "
        "gauge they are based on.",
    )
    kind: Literal["water_level", "tide_table"] = Field(
        default="water_level",
        description="'water_level': observed, predicted and forecast series. "
        "'tide_table': times and heights of high and low water.",
    )
    start: dt.datetime | None = Field(
        default=None,
        description="Norwegian local time unless an offset is given. Defaults to 6 hours ago "
        "(water_level) or now (tide_table).",
    )
    end: dt.datetime | None = Field(
        default=None, description="Defaults to 24 hours (water_level) or 3 days (tide_table) on."
    )
    interval_minutes: Literal[10, 60] = 60
    reference: Literal["chart_datum", "mean_sea_level", "nn2000"] = Field(
        default="chart_datum",
        description="Zero level. Chart datum is what tide tables and sea charts use; mean sea "
        "level shows the water above or below normal.",
    )

    @model_validator(mode="after")
    def _rules(self) -> SeaLevelInput:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if (self.lat is None) == (self.station is None):
            raise ValueError("give lat and lon, or station")
        if self.end is not None and self.start is None:
            raise ValueError("give start with end")
        if self.start and self.end:
            if _local(self.end) <= _local(self.start):
                raise ValueError("end must be after start")
            if (_local(self.end) - _local(self.start)).days > MAX_DAYS[self.kind]:
                raise ValueError(f"a {self.kind} period can be at most {MAX_DAYS[self.kind]} days")
        return self


class Location(BaseModel):
    name: str | None
    gauge: str | None = Field(description="The tide gauge the values are based on.")
    lat: float | None
    lon: float | None
    description: str | None


class Point(BaseModel):
    time: dt.datetime
    cm: float


class Series(BaseModel):
    type: Literal["observation", "prediction", "forecast", "weathereffect"] = Field(
        description="'weathereffect' is how much wind and air pressure add to or take from "
        "the tide."
    )
    quality: str | None
    points: list[Point]


class Tide(BaseModel):
    time: dt.datetime
    cm: float
    kind: Literal["high", "low"]


class SeaLevelOutput(BaseModel):
    location: Location
    reference: str
    unit: Literal["cm"] = "cm"
    series: list[Series] = Field(description="For kind 'water_level'.")
    tides: list[Tide] = Field(description="For kind 'tide_table'.")


def _local(value: dt.datetime) -> dt.datetime:
    return value.astimezone(OSLO) if value.tzinfo else value.replace(tzinfo=OSLO)


def _period(args: SeaLevelInput) -> tuple[dt.datetime, dt.datetime]:
    if args.start is not None:
        start = _local(args.start)
        default = dt.timedelta(hours=24) if args.kind == "water_level" else dt.timedelta(days=3)
        return start, _local(args.end) if args.end else start + default
    # Rounded to the hour, so calls within the same hour share a cached response.
    now = dt.datetime.now(OSLO).replace(minute=0, second=0, microsecond=0)
    if args.kind == "tide_table":
        return now, now + dt.timedelta(days=3)
    return now - dt.timedelta(hours=6), now + dt.timedelta(hours=24)


def _float(element: Element, name: str) -> float | None:
    try:
        return float(element.get(name, ""))
    except ValueError:
        return None


async def sea_level(ctx: Context, args: SeaLevelInput) -> Result[SeaLevelOutput]:
    up = ctx.upstream(SPEC.id)
    start, end = _period(args)
    # The API reads fromtime and totime as UTC+1 all year, even when it answers in summer time.
    params: dict[str, Any] = {
        "fromtime": f"{start.astimezone(UTC_PLUS_1):%Y-%m-%dT%H:%M}",
        "totime": f"{end.astimezone(UTC_PLUS_1):%Y-%m-%dT%H:%M}",
        "datatype": "tab" if args.kind == "tide_table" else "all",
        "refcode": REFERENCES[args.reference],
        "interval": args.interval_minutes,
        "lang": "en",
        # Norwegian local time, summer time included, matching how the times are sent.
        "tzone": 1,
        "dst": 1,
    }
    if args.station:
        params |= {"tide_request": "stationdata", "stationcode": args.station}
    else:
        params |= {
            "tide_request": "locationdata",
            "lat": round(args.lat, 4),  # type: ignore[arg-type]
            "lon": round(args.lon, 4),  # type: ignore[arg-type]
        }
    recent = end > dt.datetime.now(OSLO) - dt.timedelta(days=1)
    fetched = await up.get_xml(TIDE_URL, params=params, ttl="recent" if recent else "historic")

    root: Element = fetched.json
    body = root.find("locationdata")
    if body is None:
        body = root.find("stationdata")
    nodata = body.find("nodata") if body is not None else None
    location = body.find("location") if body is not None else None
    if body is None or nodata is not None or location is None:
        info = nodata.get("info") if nodata is not None else "no data was returned"
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Kartverket has no water level here: {info}"
            if args.lat is not None
            else f"There is no public tide gauge '{args.station}'.",
            source_id=SPEC.id,
        )

    series: list[Series] = []
    tides: list[Tide] = []
    # Location data lists its series beside the location; station data nests them inside it.
    for data in location.findall("data") or body.findall("data"):
        kind = data.get("type")
        points = data.findall("waterlevel")
        if args.kind == "tide_table":
            tides.extend(
                Tide(time=dt.datetime.fromisoformat(w.get("time", "")), cm=v, kind=w.get("flag"))  # type: ignore[arg-type]
                for w in points
                if (v := _float(w, "value")) is not None and w.get("flag") in ("high", "low")
            )
        elif kind in SERIES:
            series.append(
                Series(
                    type=kind,  # type: ignore[arg-type]
                    quality=data.get("qualityClass") or None,
                    points=[
                        Point(time=dt.datetime.fromisoformat(w.get("time", "")), cm=v)
                        for w in points
                        if (v := _float(w, "value")) is not None
                    ],
                )
            )
    tides.sort(key=lambda t: t.time)

    notes = list(fetched.notes)
    gauge = location.get("obscode") or location.get("code")
    observed = any(s.type == "observation" for s in series)
    if args.lat is not None and args.kind == "water_level" and not observed:
        notes.append("No observations here: the values are modelled from the nearest gauge.")
    notes.append(f"Heights in cm above {args.reference.replace('_', ' ')}.")
    if args.kind == "water_level" and not series:
        notes.append("No water level series covers this period.")
    return Result(
        data=SeaLevelOutput(
            location=Location(
                name=location.get("name"),
                gauge=gauge,
                lat=_float(location, "latitude"),
                lon=_float(location, "longitude"),
                description=location.get("descr"),
            ),
            reference=args.reference,
            series=series,
            tides=tides,
        ),
        provenance=[
            up.provenance(fetched, title=f"Kartverket water level, {location.get('name')}")
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="sea_level",
        title="Water level and tides",
        description=(
            "Sea level on the Norwegian coast from Kartverket: observed at tide gauges, the tidal "
            "prediction, the effect of wind and air pressure, and a forecast for the next days; "
            "or a tide table of high and low water. Ask by coastal point or tide gauge code."
        ),
        input_model=SeaLevelInput,
        output_model=SeaLevelOutput,
        handler=sea_level,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/sea/level",
        examples=(
            {"lat": 60.396, "lon": 5.32},
            {"station": "BGO", "kind": "tide_table"},
            {
                "lat": 59.91,
                "lon": 10.73,
                "reference": "mean_sea_level",
                "start": "2026-10-01T00:00",
                "end": "2026-10-02T00:00",
            },
        ),
    ),
)
