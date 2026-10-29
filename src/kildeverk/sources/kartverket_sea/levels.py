"""Storm-surge return levels, record levels and tidal levels on the coast, from Kartverket."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.core.operation import Operation
from kildeverk.sources.kartverket_sea.ops import REFERENCES
from kildeverk.sources.kartverket_sea.spec import SPEC, TIDE_URL

RETURN = re.compile(r"^(\d+)Y(MAX|MIN)$")


class LevelsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float | None = Field(default=None, ge=57, le=82, description="A point on the coast.")
    lon: float | None = Field(default=None, ge=-11, le=35)
    station: str | None = Field(
        default=None, pattern=r"^[A-Z]{3}$", description="Tide gauge code, e.g. 'BGO' (Bergen)."
    )
    reference: Literal["nn2000", "mean_sea_level", "chart_datum"] = Field(
        default="nn2000",
        description="Zero level. NN2000 is the height system of maps and buildings on land, so "
        "levels can be compared with terrain heights; chart datum is what sea charts use.",
    )

    @model_validator(mode="after")
    def _rules(self) -> LevelsInput:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if (self.lat is None) == (self.station is None):
            raise ValueError("give lat and lon, or station")
        return self


class ReturnLevel(BaseModel):
    years: int = Field(description="Return period: the level is reached on average once in it.")
    level_cm: float


class Record(BaseModel):
    level_cm: float
    date: dt.date | None = Field(description="When a full date is given.")
    when: str | None = Field(description="Kartverket's note as written: a date, a year, a storm.")


class TidalLevel(BaseModel):
    code: str
    name: str
    level_cm: float


class LevelsOutput(BaseModel):
    place: str | None
    place_code: str | None
    lat: float | None
    lon: float | None
    gauge: str | None = Field(description="The tide gauge the levels are based on.")
    reference: str
    high_water_return_levels: list[ReturnLevel] = Field(description="Storm surge, shortest first.")
    low_water_return_levels: list[ReturnLevel]
    highest_observed: Record | None
    lowest_observed: Record | None
    high_end_level_cm: float | None = Field(
        description="What Kartverket labels 'High-end water level'; the API gives no further "
        "definition."
    )
    tidal_levels: list[TidalLevel] = Field(description="Highest first.")
    land_uplift_cm_per_year: float | None


DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def _date(value: str | None) -> dt.date | None:
    """The date in a note like '26.11.2011 under stormen Berit', if it has one."""

    match = DATE.search(value or "")
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def extremes(ctx: Context, args: LevelsInput) -> Result[LevelsOutput]:
    params: dict[str, Any] = {"refcode": REFERENCES[args.reference], "lang": "en"}
    if args.station:
        params |= {"tide_request": "stationlevels", "stationcode": args.station}
    else:
        params |= {"tide_request": "locationlevels", "lat": args.lat, "lon": args.lon}
    up = ctx.upstream(SPEC.id)
    fetched = await up.get_xml(TIDE_URL, params=params, ttl="historic")
    block = fetched.json.find("locationlevel")
    nodata = block.find("nodata") if block is not None else None
    if block is None or nodata is not None or block.find("location") is None:
        reason = nodata.get("info") if nodata is not None else "no levels came back"
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Kartverket has no sea levels for that place: {reason}",
            source_id=SPEC.id,
        )
    where = block.find("location")
    highs: list[ReturnLevel] = []
    lows: list[ReturnLevel] = []
    tidal: list[TidalLevel] = []
    observed: dict[str, Record] = {}
    high_end = None
    for level in block.findall("reflevel"):
        code, value = level.get("code") or "", _float(level.get("value"))
        if value is None:
            continue
        if match := RETURN.match(code):
            target = highs if match.group(2) == "MAX" else lows
            target.append(ReturnLevel(years=int(match.group(1)), level_cm=value))
        elif code in ("HOWL", "LOWL"):
            observed[code] = Record(
                level_cm=value, date=_date(level.get("info")), when=level.get("info") or None
            )
        elif code == "HIGHENDWL":
            high_end = value
        elif level.get("type") in ("ASTRO", "ASTROREF", "REF"):
            tidal.append(TidalLevel(code=code, name=level.get("name") or code, level_cm=value))
    highs.sort(key=lambda r: r.years)
    lows.sort(key=lambda r: r.years)
    tidal.sort(key=lambda t: t.level_cm, reverse=True)
    place = where.get("place") or where.get("name")
    notes = list(fetched.notes)
    notes.append(
        f"Levels are in cm above {block.get('reflevel') or args.reference}. A 200-year level is "
        "reached on average once in 200 years: about a 0.5 % chance in any year. Sea level rise "
        "is not included."
    )
    return Result(
        data=LevelsOutput(
            place=place,
            place_code=where.get("code"),
            lat=_float(where.get("latitude")),
            lon=_float(where.get("longitude")),
            gauge=where.get("obsname"),
            reference=block.get("reflevel") or args.reference,
            high_water_return_levels=highs,
            low_water_return_levels=lows,
            highest_observed=observed.get("HOWL"),
            lowest_observed=observed.get("LOWL"),
            high_end_level_cm=high_end,
            tidal_levels=tidal,
            land_uplift_cm_per_year=_float(where.get("landlift")),
        ),
        provenance=[
            up.provenance(fetched, title=f"Kartverket sea levels for {place or 'a point'}")
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="sea_level_extremes",
        title="Storm surge and record sea levels",
        description=(
            "How high and low the sea gets at a place on the Norwegian coast, from Kartverket: "
            "storm-surge levels reached on average once in 1, 5, 10, 20, 50, 100, 200 and 1000 "
            "years, the highest and lowest levels ever observed with their dates, and the tidal "
            "levels (highest astronomical tide, mean high water and so on). In NN2000 by default, "
            "so the levels compare with heights on land. For the water level now and tide "
            "tables, use sea_level."
        ),
        input_model=LevelsInput,
        output_model=LevelsOutput,
        handler=extremes,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/sea/extremes",
        examples=({"lat": 60.398, "lon": 5.32}, {"station": "OSL", "reference": "chart_datum"}),
    ),
)
