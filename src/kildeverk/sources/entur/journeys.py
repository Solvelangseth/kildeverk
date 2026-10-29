"""Journeys from A to B on public transport, from Entur's journey planner."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.entur.ops import _start, _text
from kildeverk.sources.entur.spec import JOURNEY_PLANNER, JOURNEY_PLANNER_URL

_PLACE = "name quay { id publicCode stopPlace { id name } }"
TRIP_QUERY = f"""query($from: Location!, $to: Location!, $dateTime: DateTime, $arriveBy: Boolean,
  $n: Int) {{
  trip(from: $from, to: $to, dateTime: $dateTime, arriveBy: $arriveBy, numTripPatterns: $n) {{
    tripPatterns {{ expectedStartTime expectedEndTime duration walkDistance
      legs {{ mode distance aimedStartTime expectedStartTime aimedEndTime expectedEndTime realtime
        fromPlace {{ {_PLACE} }} toPlace {{ {_PLACE} }}
        line {{ publicCode name authority {{ name }} }}
        fromEstimatedCall {{ destinationDisplay {{ frontText }} cancellation }}
        situations {{ summary {{ value language }} }} }} }} }} }}"""


class JourneysInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: str | None = Field(
        default=None,
        max_length=80,
        description="A stop place id ('NSR:StopPlace:337') or a stop's name ('Oslo S').",
    )
    origin_lat: float | None = Field(default=None, ge=57, le=82)
    origin_lon: float | None = Field(default=None, ge=-11, le=35)
    destination: str | None = Field(default=None, max_length=80)
    destination_lat: float | None = Field(default=None, ge=57, le=82)
    destination_lon: float | None = Field(default=None, ge=-11, le=35)
    time: dt.datetime | None = Field(
        default=None, description="Norwegian local time unless an offset is given; default now."
    )
    arrive_by: bool = Field(default=False, description="Treat time as the latest arrival.")
    limit: int = Field(default=3, ge=1, le=6)

    @model_validator(mode="after")
    def _ends(self) -> JourneysInput:
        for end in ("origin", "destination"):
            name = getattr(self, end)
            lat, lon = getattr(self, f"{end}_lat"), getattr(self, f"{end}_lon")
            if (lat is None) != (lon is None):
                raise ValueError(f"give both {end}_lat and {end}_lon")
            if (name is None) == (lat is None):
                raise ValueError(f"give {end} (a stop id or name) or {end}_lat and {end}_lon")
        return self


class Leg(BaseModel):
    mode: str = Field(description="foot, bus, tram, metro, rail, water, air, coach …")
    line: str | None = Field(description="The line's public code, e.g. 'FLY2' or '5'.")
    line_name: str | None
    operator: str | None
    towards: str | None = Field(description="The destination shown on the vehicle.")
    origin: str | None
    origin_platform: str | None
    destination: str | None
    destination_platform: str | None
    departs: dt.datetime
    arrives: dt.datetime
    scheduled_departure: dt.datetime | None
    realtime: bool
    cancelled: bool
    distance_m: int | None
    notices: list[str]


class Journey(BaseModel):
    departs: dt.datetime
    arrives: dt.datetime
    duration_minutes: int
    changes: int = Field(description="Changes between vehicles; walking legs do not count.")
    walk_m: int
    legs: list[Leg]


class End(BaseModel):
    name: str | None
    stop_id: str | None
    lat: float | None
    lon: float | None


class JourneysOutput(BaseModel):
    origin: End
    destination: End
    journeys: list[Journey]


async def _location(
    ctx: Context,
    name: str | None,
    lat: float | None,
    lon: float | None,
    notes: list[str],
    provenance: list[Provenance],
) -> tuple[dict[str, Any], End]:
    if lat is not None and lon is not None:
        return {"coordinates": {"latitude": lat, "longitude": lon}}, End(
            name=None, stop_id=None, lat=lat, lon=lon
        )
    assert name is not None
    if name.startswith("NSR:"):
        return {"place": name}, End(name=None, stop_id=name, lat=None, lon=None)
    from kildeverk.sources import composite  # late: composite reaches tools through the registry

    found = await composite._part(ctx, "transit_find_stops", {"query": name, "limit": 1})
    if isinstance(found, ToolError):
        raise found
    stops = found["data"]["stops"]
    if not stops:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"No stop is called '{name}'. Look it up, or give coordinates.",
            next_call=NextCall(tool="transit_find_stops", arguments={"query": name}),
            source_id=JOURNEY_PLANNER.id,
        )
    stop = stops[0]
    provenance.extend(Provenance.model_validate(p) for p in found["provenance"])
    if stop["name"].casefold() != name.casefold():
        notes.append(f"'{name}' was read as {stop['name']} ({stop['id']}).")
    return {"place": stop["id"], "name": stop["name"]}, End(
        name=stop["name"], stop_id=stop["id"], lat=stop.get("lat"), lon=stop.get("lon")
    )


def _time(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def _leg(leg: dict[str, Any]) -> Leg:
    origin, destination = leg.get("fromPlace") or {}, leg.get("toPlace") or {}
    line = leg.get("line") or {}
    call = leg.get("fromEstimatedCall") or {}

    def stop_name(place: dict[str, Any]) -> str | None:
        quay = place.get("quay") or {}
        return (quay.get("stopPlace") or {}).get("name") or place.get("name")

    return Leg(
        mode=leg.get("mode") or "unknown",
        line=line.get("publicCode") or None,
        line_name=line.get("name"),
        operator=(line.get("authority") or {}).get("name"),
        towards=(call.get("destinationDisplay") or {}).get("frontText"),
        origin=stop_name(origin),
        origin_platform=(origin.get("quay") or {}).get("publicCode") or None,
        destination=stop_name(destination),
        destination_platform=(destination.get("quay") or {}).get("publicCode") or None,
        departs=_time(leg.get("expectedStartTime")),  # type: ignore[arg-type]
        arrives=_time(leg.get("expectedEndTime")),  # type: ignore[arg-type]
        scheduled_departure=_time(leg.get("aimedStartTime")),
        realtime=bool(leg.get("realtime")),
        cancelled=bool(call.get("cancellation")),
        distance_m=round(leg["distance"]) if leg.get("distance") is not None else None,
        notices=[
            t for t in (_text((s or {}).get("summary")) for s in leg.get("situations") or []) if t
        ],
    )


async def journeys(ctx: Context, args: JourneysInput) -> Result[JourneysOutput]:
    notes: list[str] = []
    provenance: list[Provenance] = []
    origin, origin_end = await _location(
        ctx, args.origin, args.origin_lat, args.origin_lon, notes, provenance
    )
    destination, destination_end = await _location(
        ctx, args.destination, args.destination_lat, args.destination_lon, notes, provenance
    )
    variables: dict[str, Any] = {
        "from": origin,
        "to": destination,
        "n": args.limit,
        "arriveBy": args.arrive_by,
    }
    # Without a time the planner plans from now, and the request stays the same between calls.
    if args.time is not None:
        variables["dateTime"] = _start(args.time)
    up = ctx.upstream(JOURNEY_PLANNER.id)
    try:
        fetched = await up.post_json(
            JOURNEY_PLANNER_URL, body={"query": TRIP_QUERY, "variables": variables}, ttl="journeys"
        )
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Entur's journey planner rejected the request: {exc.detail}",
            source_id=JOURNEY_PLANNER.id,
            upstream_status=exc.status,
        ) from None
    errors = fetched.json.get("errors") or []
    if errors:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Entur's journey planner rejected the request: {str(errors[0].get('message'))[:200]}",
            source_id=JOURNEY_PLANNER.id,
        )
    patterns = (((fetched.json.get("data") or {}).get("trip")) or {}).get("tripPatterns") or []
    result: list[Journey] = []
    for p in patterns:
        legs = [_leg(leg) for leg in p.get("legs") or [] if leg.get("expectedStartTime")]
        if not legs:
            continue
        rides = [leg for leg in legs if leg.mode != "foot"]
        result.append(
            Journey(
                departs=_time(p.get("expectedStartTime")) or legs[0].departs,
                arrives=_time(p.get("expectedEndTime")) or legs[-1].arrives,
                duration_minutes=round((p.get("duration") or 0) / 60),
                changes=max(len(rides) - 1, 0),
                walk_m=round(p.get("walkDistance") or 0),
                legs=legs,
            )
        )
    notes.extend(fetched.notes)
    if not result:
        notes.append("No journeys found; try another time, or points nearer a stop.")
    if any(leg.cancelled for j in result for leg in j.legs):
        notes.append("Some legs are cancelled; check before travelling.")
    notes.append(
        "Times are expected times, real-time where the leg says so; scheduled_departure is the "
        "timetable."
    )
    provenance.append(up.provenance(fetched, title="Entur journey planner trip"))
    return Result(
        data=JourneysOutput(origin=origin_end, destination=destination_end, journeys=result),
        provenance=provenance,
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="transit_journeys",
        title="Journeys from A to B",
        description=(
            "Plan a public transport journey anywhere in Norway with Entur, for every operator: "
            "the next journeys (or those arriving by a time), each with departure and arrival, "
            "duration, changes and walking distance, and every leg's mode, line, direction, "
            "stops, platforms, real-time times, cancellations and notices. Give each end as a "
            "stop id, a stop name or coordinates."
        ),
        input_model=JourneysInput,
        output_model=JourneysOutput,
        handler=journeys,
        source_ids=(JOURNEY_PLANNER.id, "entur_geocoder"),
        http_method="GET",
        http_path="/v1/transit/journeys",
        examples=(
            {"origin": "Oslo S", "destination": "Bergen stasjon", "limit": 2},
            {
                "origin_lat": 59.9139,
                "origin_lon": 10.7522,
                "destination_lat": 59.95,
                "destination_lon": 10.73,
            },
        ),
    ),
)
