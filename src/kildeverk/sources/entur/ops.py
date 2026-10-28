"""Public transport tools backed by Entur's geocoder and journey planner."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any
from zoneinfo import ZoneInfo

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.entur.models import (
    Departure,
    DeparturesInput,
    DeparturesOutput,
    FindStopsInput,
    FindStopsOutput,
    Situation,
    Stop,
)
from kildeverk.sources.entur.spec import (
    GEOCODER,
    GEOCODER_URL,
    JOURNEY_PLANNER,
    JOURNEY_PLANNER_URL,
)

OSLO = ZoneInfo("Europe/Oslo")


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _stop(feature: dict[str, Any], origin: tuple[float, float] | None) -> Stop:
    props = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"][:2]
    address = props.get("address") or {}
    names = props.get("names") or {}
    locality_id = address.get("localityId") or ""
    distance = props.get("distance")
    if distance is None and origin:
        distance = _distance_km(*origin, lat, lon)
    modes: list[str] = []
    for m in props.get("transportModes") or []:
        if m.get("mode") and m["mode"] not in modes:
            modes.append(m["mode"])
    return Stop(
        id=props["id"],
        name=names.get("default") or props["id"],
        label=names.get("display") or names.get("default") or props["id"],
        municipality_code=locality_id.rsplit(":", 1)[-1] or None,
        municipality=address.get("locality"),
        county=address.get("county"),
        lat=lat,
        lon=lon,
        distance_km=round(distance, 3) if distance is not None else None,
        modes=modes,
        stop_types=props.get("stopPlaceTypes") or [],
        fare_zones=props.get("fareZones") or [],
    )


# --- transit_find_stops ------------------------------------------------------------


async def find_stops(ctx: Context, args: FindStopsInput) -> Result[FindStopsOutput]:
    up = ctx.upstream(GEOCODER.id)
    # Only stop places from the national stop register; never addresses or OSM places.
    params: dict[str, Any] = {"layers": "stopPlace", "limit": args.limit}
    if args.municipality:
        params["localities"] = f"KVE:TopographicPlace:{args.municipality}"
    if args.stop_types:
        params["stopPlaceTypes"] = ",".join(args.stop_types)
    origin = (args.lat, args.lon) if args.lat is not None and args.lon is not None else None
    if origin:
        params["lat"], params["lon"] = round(origin[0], 4), round(origin[1], 4)
    if args.query:
        params["q"] = args.query
        path = "autocomplete"
    elif origin:
        params["radius"] = args.radius_km
        path = "reverse"
    else:
        path = "autocomplete"
    try:
        fetched = await up.get_json(f"{GEOCODER_URL}/{path}", params=params, ttl="stops")
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Entur's geocoder rejected the search: {exc.detail}",
            source_id=GEOCODER.id,
            upstream_status=exc.status,
        ) from None

    stops = [
        _stop(f, origin)
        for f in fetched.json.get("features") or []
        if (f.get("properties") or {}).get("id", "").startswith("NSR:StopPlace:")
    ]
    notes = list(fetched.notes)
    if not stops:
        notes.append(
            "No stop matched. Try a shorter name, a larger radius_km, or fewer filters."
            if args.query or origin
            else "No stop matched these filters."
        )
    elif args.query and origin:
        notes.append("Stops near lat/lon rank higher; the radius only applies without a query.")
    return Result(
        data=FindStopsOutput(stops=stops),
        provenance=[up.provenance(fetched, title="Entur stop place search")],
        notes=notes,
    )


# --- transit_departures ------------------------------------------------------------

_CALL_FIELDS = """
  aimedDepartureTime expectedDepartureTime realtime cancellation
  quay { id publicCode }
  destinationDisplay { frontText via }
  serviceJourney { id journeyPattern { line {
    publicCode name transportMode authority { name } operator { name } } } }
  situations { id severity summary { value language } description { value language } }
"""
_CALLS_ARGS = (
    "numberOfDepartures: $n, startTime: $start, timeRange: $range, "
    "whiteListedModes: $modes, includeCancelledTrips: $cancelled, arrivalDeparture: departures"
)
_VARS = "$id: String!, $n: Int!, $start: DateTime, $range: Int!, $modes: [TransportMode], $cancelled: Boolean"
STOP_PLACE_QUERY = (
    f"query({_VARS}) {{ place: stopPlace(id: $id) {{ id name "
    f"estimatedCalls({_CALLS_ARGS}) {{ {_CALL_FIELDS} }} }} }}"
)
QUAY_QUERY = (
    f"query({_VARS}) {{ place: quay(id: $id) {{ id name publicCode "
    f"estimatedCalls({_CALLS_ARGS}) {{ {_CALL_FIELDS} }} }} }}"
)


def _start(value: dt.datetime) -> str:
    # A naive time is read as Norwegian local time, summer time included.
    if value.tzinfo is None:
        value = value.replace(tzinfo=OSLO)
    return value.isoformat(timespec="seconds")


def _text(values: list[dict[str, Any]] | None) -> str | None:
    if not values:
        return None
    by_language = {v.get("language"): v.get("value") for v in values if v.get("value")}
    for language in ("en", "no", "nob", "nb", None):
        if by_language.get(language):
            return by_language[language]
    return next(iter(by_language.values()), None)


async def departures(ctx: Context, args: DeparturesInput) -> Result[DeparturesOutput]:
    up = ctx.upstream(JOURNEY_PLANNER.id)
    is_quay = args.stop.startswith("NSR:Quay:")
    variables: dict[str, Any] = {
        "id": args.stop,
        "n": args.limit,
        "range": args.within_minutes * 60,
        "cancelled": args.include_cancelled,
    }
    # Without a start the journey planner looks from now, and the request stays the same
    # from call to call, so the short cache can absorb bursts.
    if args.start is not None:
        variables["start"] = _start(args.start)
    if args.modes:
        variables["modes"] = args.modes
    body = {"query": QUAY_QUERY if is_quay else STOP_PLACE_QUERY, "variables": variables}
    try:
        fetched = await up.post_json(JOURNEY_PLANNER_URL, body=body, ttl="departures")
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Entur's journey planner rejected the request: {exc.detail}",
            source_id=JOURNEY_PLANNER.id,
            upstream_status=exc.status,
        ) from None

    errors = fetched.json.get("errors") or []
    if errors:
        message = str(errors[0].get("message") or "unknown error")[:200]
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Entur's journey planner rejected the request: {message}",
            source_id=JOURNEY_PLANNER.id,
        )
    place = (fetched.json.get("data") or {}).get("place")
    if place is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"No stop {args.stop} exists in the national stop register. Stop ids come from "
            "transit_find_stops.",
            next_call=NextCall(tool="transit_find_stops", arguments={"query": "Oslo S"}),
            source_id=JOURNEY_PLANNER.id,
        )

    rows: list[Departure] = []
    situations: dict[str, Situation] = {}
    for call in place.get("estimatedCalls") or []:
        journey = call.get("serviceJourney") or {}
        line = (journey.get("journeyPattern") or {}).get("line") or {}
        quay = call.get("quay") or {}
        destination = call.get("destinationDisplay") or {}
        aimed = dt.datetime.fromisoformat(call["aimedDepartureTime"])
        expected = dt.datetime.fromisoformat(
            call.get("expectedDepartureTime") or call["aimedDepartureTime"]
        )
        ids = []
        for s in call.get("situations") or []:
            ids.append(s["id"])
            situations.setdefault(
                s["id"],
                Situation(
                    id=s["id"],
                    severity=s.get("severity"),
                    summary=_text(s.get("summary")),
                    description=_text(s.get("description")),
                ),
            )
        rows.append(
            Departure(
                aimed=aimed,
                expected=expected,
                delay_s=int((expected - aimed).total_seconds()),
                realtime=bool(call.get("realtime")),
                cancelled=bool(call.get("cancellation")),
                platform=quay.get("publicCode") or None,
                quay_id=quay.get("id"),
                line=line.get("publicCode") or None,
                line_name=line.get("name"),
                mode=line.get("transportMode"),
                destination=destination.get("frontText"),
                via=destination.get("via") or [],
                operator=(line.get("operator") or {}).get("name"),
                authority=(line.get("authority") or {}).get("name"),
                service_journey_id=journey.get("id") or "",
                situation_ids=ids,
            )
        )

    notes = list(fetched.notes)
    notes.append("Times are Norwegian local time with their UTC offset.")
    if not rows:
        notes.append(
            f"No departures within {args.within_minutes} minutes"
            + (" for these modes" if args.modes else "")
            + ". Try a larger within_minutes."
        )
    if any(r.cancelled for r in rows):
        notes.append("Some departures are cancelled; they are listed with cancelled=true.")
    if fetched.cache.hit:
        notes.append("Served from a cache that is at most 30 seconds old.")
    name = place.get("name") or args.stop
    if is_quay and place.get("publicCode"):
        name = f"{name}, platform {place['publicCode']}"
    return Result(
        data=DeparturesOutput(
            stop_id=place.get("id") or args.stop,
            stop_name=name,
            departures=rows,
            situations=list(situations.values()),
        ),
        provenance=[up.provenance(fetched, title=f"Entur departures, {name}")],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="transit_find_stops",
        title="Find public transport stops",
        description=(
            "Find bus, tram, metro, train, ferry and airport stops anywhere in Norway, from the "
            "national stop register. Search by name, near a point, or by municipality code, "
            "optionally only some kinds of stop (e.g. 'railStation'). Returns stop ids for "
            "transit_departures, with the modes served, location and fare zones."
        ),
        input_model=FindStopsInput,
        output_model=FindStopsOutput,
        handler=find_stops,
        source_ids=(GEOCODER.id,),
        http_method="GET",
        http_path="/v1/transit/stops",
        examples=(
            {"query": "Oslo S", "limit": 3},
            {"lat": 60.3913, "lon": 5.3221, "radius_km": 0.5},
            {"municipality": "4601", "stop_types": ["railStation"]},
        ),
    ),
    Operation(
        name="transit_departures",
        title="Upcoming departures",
        description=(
            "Next departures from a stop (all its platforms) or from one quay, for every operator "
            "in Norway: scheduled and real-time times, delay, platform, line, destination and "
            "cancellations, plus any disruption notices. Optionally only some modes, or from a "
            "later start time."
        ),
        input_model=DeparturesInput,
        output_model=DeparturesOutput,
        handler=departures,
        source_ids=(JOURNEY_PLANNER.id,),
        http_method="GET",
        http_path="/v1/transit/departures",
        examples=(
            {"stop": "NSR:StopPlace:59872", "limit": 5},
            {"stop": "NSR:StopPlace:59872", "modes": ["rail"], "within_minutes": 60},
        ),
    ),
)
