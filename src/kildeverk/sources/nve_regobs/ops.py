"""Field observations of avalanches, landslides, floods and ice from Regobs."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.operation import Operation
from kildeverk.sources.met.models import Latitude, Longitude
from kildeverk.sources.nve_regobs.spec import BASE_URL, REGISTRATION_PAGE, SPEC

Hazard = Literal["snow", "landslide", "flood", "ice"]
# Regobs's geo hazard ids: "Snow = 10, dirt = 20, water = 60, ice = 70".
HAZARDS: dict[str, int] = {"snow": 10, "landslide": 20, "flood": 60, "ice": 70}
HAZARD_NAMES = {v: k for k, v in HAZARDS.items()}
MAX_TEXT = 600
EMAIL = re.compile(r"^([^@\s]+)@([^@\s]+)\.[A-Za-z]{2,}$")


def credit_name(nickname: str | None) -> str | None:
    """The username to credit, with an e-mail address cut so that it no longer is one.

    Some observers use their e-mail address as their username ('ola@nve.no'); it becomes
    'ola@nve', which still credits them without publishing a way to reach them.
    """

    if not nickname:
        return nickname
    match = EMAIL.match(nickname.strip())
    if not match:
        return nickname
    return f"{match.group(1)}@{match.group(2).split('.')[0]}"


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


class ObservationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: Latitude
    lon: Longitude
    radius_km: float = Field(default=20, gt=0, le=100)
    hazards: list[Hazard] = Field(
        default=["snow", "landslide", "flood", "ice"],
        min_length=1,
        description="'snow' covers snow and avalanches; also 'landslide', 'flood', 'ice'.",
    )
    start: dt.date | None = Field(default=None, description="First day; default two weeks ago.")
    end: dt.date | None = Field(default=None, description="Last day, inclusive; default today.")
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _dates(self) -> ObservationsInput:
        if self.start and self.end and self.end < self.start:
            raise ValueError("end must not be before start")
        return self


class Finding(BaseModel):
    kind: str = Field(description="The kind of observation, e.g. 'Avalanche activity'.")
    text: str = Field(description="Regobs's summary of it, in the observer's language.")


class FieldObservation(BaseModel):
    id: int
    hazard: str
    time: dt.datetime
    place: str | None
    municipality: str | None
    municipality_code: str | None
    forecast_region: str | None
    lat: float | None
    lon: float | None
    height_m: int | None
    observer: str | None = Field(
        description="The observer's username, which Regobs asks to credit."
    )
    observer_competence: int | None = Field(description="Regobs's competence level, 0-5 stars.")
    findings: list[Finding]
    pictures: int
    url: str


class ObservationsOutput(BaseModel):
    start: dt.date
    end: dt.date
    total_matches: int | None
    observations: list[FieldObservation] = Field(description="Newest first.")


def _findings(item: dict[str, Any]) -> list[Finding]:
    out = []
    for block in item.get("Summaries") or []:
        parts = [
            f"{s.get('Header')}: {s.get('Value')}" if s.get("Header") else str(s.get("Value"))
            for s in block.get("Summaries") or []
            if s.get("Value") not in (None, "")
        ]
        text = " · ".join(" ".join(str(p).split()) for p in parts)
        if len(text) > MAX_TEXT:
            text = text[: MAX_TEXT - 1].rstrip() + "…"
        if text:
            out.append(Finding(kind=block.get("RegistrationName") or "Observation", text=text))
    return out


def _observation(item: dict[str, Any]) -> FieldObservation:
    where = item.get("ObsLocation") or {}
    who = item.get("Observer") or {}
    competence = who.get("CompetenceLevelName")
    return FieldObservation(
        id=item["RegId"],
        hazard=HAZARD_NAMES.get(item.get("GeoHazardTID"), str(item.get("GeoHazardName"))),
        time=dt.datetime.fromisoformat(item["DtObsTime"]),
        place=where.get("Title") or where.get("LocationName"),
        municipality=where.get("MunicipalName"),
        municipality_code=where.get("MunicipalNo"),
        forecast_region=where.get("ForecastRegionName"),
        lat=where.get("Latitude"),
        lon=where.get("Longitude"),
        height_m=where.get("Height"),
        observer=credit_name(who.get("NickName")),
        observer_competence=competence.count("*")
        if isinstance(competence, str) and set(competence) <= {"*"}
        else None,
        findings=_findings(item),
        pictures=len(item.get("Attachments") or []),
        url=REGISTRATION_PAGE.format(reg_id=item["RegId"]),
    )


async def observations(ctx: Context, args: ObservationsInput) -> Result[ObservationsOutput]:
    end = args.end or _today()
    start = args.start or end - dt.timedelta(days=14)
    criteria = {
        "LangKey": 2,
        "FromDtObsTime": start.isoformat(),
        "ToDtObsTime": f"{end.isoformat()}T23:59:59",
        "SelectedGeoHazards": sorted(HAZARDS[h] for h in dict.fromkeys(args.hazards)),
        "Radius": {
            "Position": {"Latitude": round(args.lat, 4), "Longitude": round(args.lon, 4)},
            "Radius": int(args.radius_km * 1000),
        },
    }
    ttl = "recent" if end >= _today() - dt.timedelta(days=7) else "past"
    up = ctx.upstream(SPEC.id)
    found, counted = await asyncio.gather(
        up.post_json(
            f"{BASE_URL}/Search", body={**criteria, "NumberOfRecords": args.limit}, ttl=ttl
        ),
        up.post_json(f"{BASE_URL}/Search/Count", body=criteria, ttl=ttl),
    )
    items = found.json if isinstance(found.json, list) else []
    rows = [_observation(item) for item in items if item.get("RegId") and item.get("DtObsTime")]
    rows.sort(key=lambda o: o.time, reverse=True)
    total = (counted.json or {}).get("TotalMatches") if isinstance(counted.json, dict) else None
    notes = list(found.notes)
    if total is not None and total > len(rows):
        notes.append(f"Showing the newest {len(rows)} of {total}; raise limit (up to 50) for more.")
    if not rows:
        notes.append(
            f"No observations within {args.radius_km:g} km from {start} to {end}. Try a wider "
            "radius or a longer period."
        )
    notes.append(
        "Credit Regobs.no and each observer's username when you use these observations. Texts "
        "are in the observer's language and shortened past 600 characters; the url has the rest."
    )
    return Result(
        data=ObservationsOutput(start=start, end=end, total_matches=total, observations=rows),
        provenance=[
            up.provenance(found, title=f"Regobs observations within {args.radius_km:g} km"),
            up.provenance(counted, title="Regobs observation count"),
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="hazards_field_observations",
        title="Field observations of avalanches, landslides, floods and ice",
        description=(
            "What people have observed on the ground near a point, from Regobs, the system behind "
            "varsom.no: avalanche activity, danger signs, snow cover, landslides, flooding, water "
            "levels and ice thickness, each with its place, municipality, time, the observer's "
            "username and competence, a short text and a link. Newest first, by default the "
            "last two weeks within 20 km. Pairs with hazards_avalanche and "
            "hazards_flood_landslide, which give the official warnings."
        ),
        input_model=ObservationsInput,
        output_model=ObservationsOutput,
        handler=observations,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/hazards/observations",
        examples=(
            {"lat": 69.65, "lon": 18.95},
            {
                "lat": 69.65,
                "lon": 18.95,
                "radius_km": 30,
                "hazards": ["snow"],
                "start": "2026-03-01",
                "end": "2026-03-31",
                "limit": 5,
            },
        ),
    ),
)
