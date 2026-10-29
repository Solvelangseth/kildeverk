"""Official weather warnings from MET Norway's MetAlerts."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.operation import Operation
from kildeverk.sources.met.spec import METALERTS, METALERTS_URL
from kildeverk.sources.ssb_klass.names import COUNTY_PATTERN, with_region_names

LEVEL_NAMES = {1: "green", 2: "yellow", 3: "orange", 4: "red"}

Month = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class WarningsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float | None = Field(
        default=None, ge=-90, le=90, description="Warnings covering this point."
    )
    lon: float | None = Field(default=None, ge=-180, le=180)
    county: str | None = Field(
        default=None,
        pattern=COUNTY_PATTERN,
        description="County number as it was when the warning was issued, or a county name "
        "(resolved to today's number).",
    )
    domain: Literal["land", "marine"] | None = Field(default=None, description="Land or sea.")
    month: Month | None = Field(
        default=None,
        description="A past month ('2023-08') from the archive. Leave out for warnings in force "
        "or announced now.",
    )
    min_level: int = Field(
        default=2,
        ge=1,
        le=4,
        description="1 green, 2 yellow, 3 orange, 4 red; compared with the highest level a "
        "warning reached.",
    )
    limit: int = Field(default=20, ge=1, le=200)
    language: Literal["en", "nb"] = Field(
        default="en", description="'nb' for MET's Norwegian (bokmål) texts."
    )

    @model_validator(mode="after")
    def _rules(self) -> WarningsInput:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if self.lat is not None and self.county:
            raise ValueError("give lat and lon, or county, not both")
        return self


class WeatherWarning(BaseModel):
    id: str
    event: str = Field(description="e.g. 'Gale', 'Rain', 'Forest fire danger'.")
    level: int = Field(description="Level in the latest revision.")
    level_name: str
    highest_level: int = Field(description="Highest level any revision reached.")
    area: str | None
    counties: list[str]
    domain: str | None
    valid_from: dt.datetime | None
    valid_to: dt.datetime | None
    title: str | None
    description: str | None
    consequences: str | None
    instruction: str | None
    certainty: str | None
    revision: str | None = Field(
        description="'Alert' for the first issue, 'Update' after a revision."
    )
    web: str | None = Field(description="The warning on MET's website.")


class WarningsOutput(BaseModel):
    total_matches: int
    warnings: list[WeatherWarning] = Field(
        description="Highest level reached first, then soonest. Each is the latest revision."
    )


def _number(value: Any) -> int:
    try:
        return int(str(value).split(";", 1)[0])
    except ValueError:
        return 0


def _time(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return " ".join(value.split()) or None if isinstance(value, str) else None


def _warning(feature: dict[str, Any]) -> WeatherWarning:
    p = feature.get("properties") or {}
    interval = (feature.get("when") or {}).get("interval") or [None, None]
    level = _number(p.get("awareness_level"))
    return WeatherWarning(
        id=p.get("id") or "",
        event=p.get("eventAwarenessName") or p.get("event") or "",
        level=level,
        level_name=LEVEL_NAMES.get(level, str(level)),
        highest_level=level,
        area=p.get("area"),
        counties=p.get("county") or [],
        domain=p.get("geographicDomain"),
        valid_from=_time(interval[0]),
        valid_to=_time(interval[-1]) or _time(p.get("eventEndingTime")),
        title=_text(p.get("title")),
        description=_text(p.get("description")),
        consequences=_text(p.get("consequences")),
        instruction=_text(p.get("instruction")),
        certainty=p.get("certainty"),
        revision=p.get("type"),
        web=p.get("web"),
    )


async def warnings(ctx: Context, args: WarningsInput) -> Result[WarningsOutput]:
    up = ctx.upstream(METALERTS.id)
    # MetAlerts calls Norwegian 'no'.
    params: dict[str, Any] = {"lang": "no" if args.language == "nb" else "en"}
    if args.lat is not None and args.lon is not None:
        params["lat"], params["lon"] = round(args.lat, 3), round(args.lon, 3)
    if args.county:
        params["county"] = args.county
    if args.domain:
        params["geographicDomain"] = args.domain
    if args.month:
        params["period"] = args.month
        fetched = await up.get_json(f"{METALERTS_URL}/archive.json", params=params, ttl="archive")
    else:
        fetched = await up.get_json(f"{METALERTS_URL}/current.json", params=params, ttl="current")

    # The archive keeps every revision of a warning, and a revision may move its end or raise
    # its level. Ids end in a timestamp, so the highest id for the same kind of event, area
    # and start is the latest revision.
    features = fetched.json.get("features") or []
    latest: dict[tuple, WeatherWarning] = {}
    for feature in sorted(features, key=lambda f: (f.get("properties") or {}).get("id", "")):
        w = _warning(feature)
        key = ((feature.get("properties") or {}).get("event"), w.area, w.valid_from)
        if key in latest:
            w.highest_level = max(w.level, latest[key].highest_level)
        latest[key] = w
    revisions = len(features) - len(latest)
    cancelled = sum(w.revision == "Cancel" for w in latest.values())
    found = [
        w for w in latest.values() if w.highest_level >= args.min_level and w.revision != "Cancel"
    ]
    far_future = dt.datetime.max.replace(tzinfo=dt.UTC)
    found.sort(key=lambda w: (-w.highest_level, w.valid_from or far_future))
    notes = list(fetched.notes)
    if not found:
        notes.append(
            f"No weather warning at level {LEVEL_NAMES[args.min_level]} or above"
            + (f" in {args.month}." if args.month else " is in force or announced.")
        )
    elif len(found) > args.limit:
        notes.append(f"{len(found)} warnings matched; the first {args.limit} are included.")
    if revisions:
        notes.append(f"{revisions} earlier revisions of the same warnings are left out.")
    if cancelled:
        notes.append(f"{cancelled} cancelled warnings are left out.")
    if args.month and args.month < "2024-01":
        notes.append("Warnings before 2024 use the county numbers of 2020-2023.")
    return Result(
        data=WarningsOutput(total_matches=len(found), warnings=found[: args.limit]),
        provenance=[up.provenance(fetched, title=f"MetAlerts, {args.month or 'current warnings'}")],
        notes=notes,
        truncated=len(found) > args.limit,
    )


OPERATIONS = (
    Operation(
        name="weather_warnings",
        title="Official weather warnings",
        description=(
            "MET Norway's official weather warnings for land and sea: wind, gale, rain, snow, "
            "ice, storm surge, forest fire danger and more, with level (yellow, orange, red), "
            "area, period, consequences and advice. Filter by point, county or land/sea; give a "
            "month for past warnings. For flood, landslide and avalanche warnings use the "
            "hazards_ tools."
        ),
        input_model=WarningsInput,
        output_model=WarningsOutput,
        handler=with_region_names({"county": "county"})(warnings),
        source_ids=(METALERTS.id,),
        http_method="GET",
        http_path="/v1/weather/warnings",
        examples=(
            {},
            {"lat": 69.3, "lon": 16.1},
            {"month": "2023-08", "county": "03", "min_level": 3},
        ),
    ),
)
