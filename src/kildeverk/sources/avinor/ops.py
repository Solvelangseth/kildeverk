"""Departures and arrivals at Norwegian airports, from Avinor's flight data feed."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.core.operation import Operation
from kildeverk.sources.avinor.spec import BASE_URL, CREDIT, SPEC

SCOPE = {"D": "domestic", "S": "Schengen", "I": "international"}


class FlightsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    airport: str = Field(
        min_length=3,
        max_length=40,
        description="IATA code ('BGO') or the airport's name in Avinor's list ('Bergen').",
    )
    direction: Literal["departures", "arrivals", "both"] = "both"
    hours_back: int = Field(default=1, ge=0, le=24)
    hours_ahead: int = Field(default=7, ge=0, le=24)
    other_airport: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Only flights to or from this IATA code, e.g. 'OSL'.",
    )
    flight: str | None = Field(
        default=None, max_length=8, description="Only this flight number, e.g. 'SK274'."
    )


class Flight(BaseModel):
    flight: str
    airline_code: str | None
    airline: str | None
    direction: Literal["departure", "arrival"]
    other_airport_code: str | None
    other_airport: str | None
    via: list[str] = Field(description="Stops on the way, as airport names.")
    scope: str | None = Field(description="domestic, Schengen or international.")
    scheduled: dt.datetime
    status: str | None = Field(description="New info, New time, Departed, Arrived or Cancelled.")
    status_time: dt.datetime | None = Field(
        description="The new time, or when it departed or arrived."
    )
    delay_minutes: int | None
    delayed: bool
    cancelled: bool
    gate: str | None
    check_in: str | None
    belt: str | None


class FlightsOutput(BaseModel):
    airport_code: str
    airport: str | None
    updated_at: dt.datetime | None
    flights: list[Flight] = Field(description="By scheduled time.")
    credit: str = Field(description="The label Avinor requires next to its flight data.")


def _time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _names(root: Any, tag: str) -> dict[str, str]:
    return {e.get("code"): e.get("name") for e in root.iter(tag) if e.get("code")}


async def flights(ctx: Context, args: FlightsInput) -> Result[FlightsOutput]:
    up = ctx.upstream(SPEC.id)
    airports_f, airlines_f, statuses_f = await asyncio.gather(
        up.get_xml(f"{BASE_URL}/airportNames/v1.0", ttl="names"),
        up.get_xml(f"{BASE_URL}/airlineNames/v1.0", ttl="names"),
        up.get_xml(f"{BASE_URL}/flightStatuses/v1.0", ttl="names"),
    )
    airports = _names(airports_f.json, "airportName")
    airlines = _names(airlines_f.json, "airlineName")
    statuses = {e.get("code"): e.get("statusTextEn") for e in statuses_f.json.iter("flightStatus")}

    asked = args.airport.strip()
    code = asked.upper()
    if not (len(code) == 3 and code.isalpha() and code in airports):
        matches = sorted(c for c, n in airports.items() if n and n.casefold() == asked.casefold())
        if len(matches) != 1:
            starts = sorted(
                f"{c} {n}"
                for c, n in airports.items()
                if n and n.casefold().startswith(asked.casefold())
            )[:8]
            raise ToolError(
                ErrorCode.NOT_FOUND if not matches else ErrorCode.AMBIGUOUS,
                f"No single airport is called '{asked}'. Give its three-letter IATA code"
                + (f"; names starting so: {', '.join(starts)}." if starts else "."),
                source_id=SPEC.id,
            )
        code = matches[0]

    params: dict[str, Any] = {
        "airport": code,
        "TimeFrom": args.hours_back,
        "TimeTo": args.hours_ahead,
    }
    if args.direction != "both":
        params["direction"] = "D" if args.direction == "departures" else "A"
    fetched = await up.get_xml(f"{BASE_URL}/XmlFeed/v1.0", params=params, ttl="flights")
    root = fetched.json
    block = root.find("flights")
    rows: list[Flight] = []
    for f in block.findall("flight") if block is not None else []:
        number = (f.findtext("flight_id") or "").strip()
        other = (f.findtext("airport") or "").strip() or None
        if args.flight and number.replace(" ", "").upper() != args.flight.replace(" ", "").upper():
            continue
        if args.other_airport and (other or "").upper() != args.other_airport.upper():
            continue
        status = f.find("status")
        status_code = status.get("code") if status is not None else None
        status_time = _time(status.get("time")) if status is not None else None
        scheduled = _time(f.findtext("schedule_time"))
        if scheduled is None:
            continue
        delay = None
        if status_time is not None and status_code in ("E", "D", "A"):
            delay = round((status_time - scheduled).total_seconds() / 60)
        via = [v.strip() for v in (f.findtext("via_airport") or "").split(",") if v.strip()]
        airline = (f.findtext("airline") or "").strip() or None
        rows.append(
            Flight(
                flight=number,
                airline_code=airline,
                airline=airlines.get(airline or ""),
                direction="arrival" if f.findtext("arr_dep") == "A" else "departure",
                other_airport_code=other,
                other_airport=airports.get(other or ""),
                via=[airports.get(v, v) for v in via],
                scope=SCOPE.get(f.findtext("dom_int") or ""),
                scheduled=scheduled,
                status=statuses.get(status_code) if status_code else None,
                status_time=status_time,
                delay_minutes=delay,
                delayed=f.findtext("delayed") == "Y",
                cancelled=status_code == "C",
                gate=f.findtext("gate"),
                check_in=f.findtext("check_in"),
                belt=f.findtext("belt"),
            )
        )
    rows.sort(key=lambda r: (r.scheduled, r.flight))
    notes = list(fetched.notes)
    if not rows:
        notes.append(
            f"No flights at {code} in this window. Avinor's feed covers Norwegian airports; widen "
            "hours_back or hours_ahead, or check the filters."
        )
    notes.append(
        f"Show '{CREDIT}' next to these times. delay_minutes is the new or actual time minus the "
        "scheduled one. Times are UTC."
    )
    updated = _time(block.get("lastUpdate")) if block is not None else None
    return Result(
        data=FlightsOutput(
            airport_code=code,
            airport=airports.get(code),
            updated_at=updated,
            flights=rows,
            credit=CREDIT,
        ),
        provenance=[
            up.provenance(fetched, title=f"Avinor flight data for {code}"),
            up.provenance(airports_f, title="Avinor airport names"),
            up.provenance(airlines_f, title="Avinor airline names"),
            up.provenance(statuses_f, title="Avinor flight statuses"),
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="flights_airport",
        title="Departures and arrivals at an airport",
        description=(
            "Departures and arrivals at a Norwegian airport from Avinor, from an hour ago to "
            "seven hours ahead by default: flight number, airline, the other airport and any "
            "stops, domestic, Schengen or international, scheduled and new or actual times with "
            "the delay in minutes, gate, check-in and baggage belt, and whether it is delayed or "
            "cancelled. Filter by direction, the other airport or a flight number. Times are at "
            "most three minutes old."
        ),
        input_model=FlightsInput,
        output_model=FlightsOutput,
        handler=flights,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/flights/{airport}",
        examples=(
            {"airport": "BGO", "direction": "departures"},
            {"airport": "Tromsø", "other_airport": "OSL", "hours_ahead": 12},
        ),
    ),
)
