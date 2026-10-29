"""Earthquakes near a point, from USGS's FDSN event service."""

from __future__ import annotations

import datetime as dt
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.met.models import Latitude, Longitude
from kildeverk.sources.usgs.spec import EVENTS_URL, SPEC


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


class QuakesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: Latitude
    lon: Longitude
    radius_km: float = Field(default=500, gt=0, le=2000)
    start: dt.date | None = Field(default=None, description="First day (UTC); default a year ago.")
    end: dt.date | None = Field(
        default=None, description="Last day (UTC), inclusive; default today."
    )
    min_magnitude: float = Field(default=2.5, ge=0, le=10)
    order: Literal["time", "magnitude"] = Field(
        default="time", description="'time' for the newest first, 'magnitude' for the largest."
    )
    limit: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="after")
    def _dates(self) -> QuakesInput:
        if self.start and self.end and self.end < self.start:
            raise ValueError("end must not be before start")
        return self


class Quake(BaseModel):
    id: str
    time: dt.datetime
    magnitude: float | None
    magnitude_type: str | None
    place: str | None
    lat: float
    lon: float
    depth_km: float | None
    distance_km: float = Field(description="From the point asked about.")
    reviewed: bool = Field(description="False while it is still USGS's automatic estimate.")
    felt_reports: int | None = Field(description="People who reported feeling it to USGS.")
    url: str | None


class QuakesOutput(BaseModel):
    start: dt.date
    end: dt.date
    quakes: list[Quake]
    more: bool = Field(description="True when more events match than the limit.")


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(6371.0 * 2 * math.asin(math.sqrt(a)), 1)


async def earthquakes(ctx: Context, args: QuakesInput) -> Result[QuakesOutput]:
    end = args.end or _today()
    start = args.start or end - dt.timedelta(days=365)
    up = ctx.upstream(SPEC.id)
    try:
        fetched = await up.get_json(
            EVENTS_URL,
            params={
                "format": "geojson",
                "latitude": round(args.lat, 3),
                "longitude": round(args.lon, 3),
                "maxradiuskm": args.radius_km,
                "starttime": start.isoformat(),
                "endtime": (end + dt.timedelta(days=1)).isoformat(),
                "minmagnitude": args.min_magnitude,
                "orderby": "time" if args.order == "time" else "magnitude",
                # One more than asked for says whether there are more.
                "limit": args.limit + 1,
            },
            ttl="recent" if end >= _today() - dt.timedelta(days=30) else "past",
        )
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"USGS refused the search: {exc.detail}",
            source_id=SPEC.id,
            upstream_status=exc.status,
        ) from None

    features = fetched.json.get("features") or []
    quakes = []
    for feature in features[: args.limit]:
        p = feature.get("properties") or {}
        lon, lat, *depth = (feature.get("geometry") or {}).get("coordinates") or [0, 0]
        quakes.append(
            Quake(
                id=str(feature.get("id")),
                time=dt.datetime.fromtimestamp(p["time"] / 1000, tz=dt.UTC),
                magnitude=p.get("mag"),
                magnitude_type=p.get("magType"),
                place=p.get("place"),
                lat=lat,
                lon=lon,
                depth_km=depth[0] if depth else None,
                distance_km=_distance_km(args.lat, args.lon, lat, lon),
                reviewed=p.get("status") == "reviewed",
                felt_reports=p.get("felt"),
                url=p.get("url"),
            )
        )
    notes = list(fetched.notes)
    if not quakes:
        notes.append(
            f"No earthquakes of magnitude {args.min_magnitude} or more within {args.radius_km:g} "
            f"km from {start} to {end}. Try a lower magnitude, a wider radius or a longer period."
        )
    notes.append(
        "Outside the United States USGS's catalogue misses many earthquakes below about "
        "magnitude 4."
    )
    return Result(
        data=QuakesOutput(start=start, end=end, quakes=quakes, more=len(features) > args.limit),
        provenance=[
            up.provenance(
                fetched,
                title=f"USGS earthquakes within {args.radius_km:g} km of {args.lat}, {args.lon}",
            )
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="hazards_earthquakes",
        title="Earthquakes near a point",
        description=(
            "Earthquakes near a point from the U.S. Geological Survey's worldwide catalogue: "
            "time, magnitude, depth, place, distance from the point, whether USGS has reviewed "
            "it and how many people reported feeling it. By default the last year within 500 km "
            "and magnitude 2.5 and up, newest first; order by magnitude for the largest."
        ),
        input_model=QuakesInput,
        output_model=QuakesOutput,
        handler=earthquakes,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/hazards/earthquakes",
        examples=(
            {"lat": 66.9, "lon": 13.6},
            {
                "lat": 60.4,
                "lon": 5.3,
                "radius_km": 300,
                "start": "2000-01-01",
                "end": "2025-12-31",
                "min_magnitude": 4,
                "order": "magnitude",
                "limit": 5,
            },
        ),
    ),
)
