"""Avinor flight data, against recordings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.avinor.ops import FlightsInput
from kildeverk.sources.avinor.spec import CREDIT
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["flights_airport"].invoke(ctx, arguments)


async def test_departures_with_names_times_and_the_credit(ctx):
    result = await call(ctx, airport="BGO", direction="departures")
    data = result["data"]
    assert (data["airport_code"], data["airport"]) == ("BGO", "Bergen")
    flights = data["flights"]
    assert flights and {f["direction"] for f in flights} == {"departure"}
    assert [f["scheduled"] for f in flights] == sorted(f["scheduled"] for f in flights)
    assert any(f["airline"] == "Widerøe" for f in flights)  # names read from ISO-8859-1
    assert all(f["scope"] in {"domestic", "Schengen", "international"} for f in flights)
    timed = [f for f in flights if f["delay_minutes"] is not None]
    assert timed and all(f["status"] in {"New time", "Departed", "Arrived"} for f in timed)
    assert data["credit"] == CREDIT and any(CREDIT in n for n in result["notes"])
    request = result["provenance"][0]["request"]["url"]
    assert "direction=D" in request and "TimeFrom=1" in request and "TimeTo=7" in request


async def test_a_name_and_a_route(ctx):
    data = (await call(ctx, airport="Tromsø", other_airport="OSL", hours_ahead=12))["data"]
    assert data["airport_code"] == "TOS"
    assert data["flights"] and {f["other_airport_code"] for f in data["flights"]} == {"OSL"}
    assert {f["direction"] for f in data["flights"]} == {"departure", "arrival"}


async def test_an_unknown_airport(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, airport="Narnia")
    assert caught.value.envelope()["error"]["code"] == "NOT_FOUND"


def test_input_rules():
    with pytest.raises(ValidationError):
        FlightsInput(airport="BG")
    with pytest.raises(ValidationError):
        FlightsInput(airport="BGO", hours_ahead=48)
