"""Journeys from A to B with Entur, against recordings."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.entur.journeys import JourneysInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["transit_journeys"].invoke(ctx, arguments)


async def test_between_two_stops_by_name(ctx):
    result = await call(ctx, origin="Oslo S", destination="Bergen stasjon", limit=2)
    data = result["data"]
    assert data["origin"]["stop_id"].startswith("NSR:StopPlace:")
    assert data["destination"]["name"].startswith("Bergen")
    journeys = data["journeys"]
    assert len(journeys) == 2
    for j in journeys:
        legs = j["legs"]
        assert legs[0]["origin"] == "Oslo S" and legs[-1]["destination"].startswith("Bergen")
        assert j["changes"] == len([leg for leg in legs if leg["mode"] != "foot"]) - 1
        start, end = (dt.datetime.fromisoformat(j[k]) for k in ("departs", "arrives"))
        assert abs((end - start).total_seconds() / 60 - j["duration_minutes"]) <= 1
        assert all(
            legs[i]["arrives"] <= legs[i + 1]["departs"] or legs[i + 1]["mode"] == "foot"
            for i in range(len(legs) - 1)
        )
    sources = {p["source_id"] for p in result["provenance"]}
    assert sources == {"entur_geocoder", "entur_journeyplanner"}


async def test_between_two_points_walking_included(ctx):
    data = (
        await call(
            ctx,
            origin_lat=59.9139,
            origin_lon=10.7522,
            destination_lat=59.95,
            destination_lon=10.73,
        )
    )["data"]
    assert data["origin"]["stop_id"] is None and data["origin"]["lat"] == 59.9139
    first = data["journeys"][0]
    assert first["legs"][0]["mode"] == "foot" and first["walk_m"] > 0


async def test_arrive_by_a_time(ctx):
    result = await call(
        ctx,
        origin="Tromsø lufthavn",
        destination="Prostneset",
        time="2026-11-02T09:00",
        arrive_by=True,
        limit=1,
    )
    journeys = result["data"]["journeys"]
    assert len(journeys) == 1
    assert dt.datetime.fromisoformat(journeys[0]["arrives"]) <= dt.datetime.fromisoformat(
        "2026-11-02T09:00+01:00"
    )


async def test_an_unknown_stop_name(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, origin="Xyzzyville", destination="Oslo S")
    error = caught.value.envelope()["error"]
    assert error["code"] == "NOT_FOUND" and error["next_call"]["tool"] == "transit_find_stops"


def test_each_end_needs_one_form():
    with pytest.raises(ValidationError):
        JourneysInput(origin="Oslo S")
    with pytest.raises(ValidationError):
        JourneysInput(origin="Oslo S", origin_lat=59.9, origin_lon=10.7, destination="Bergen")
    with pytest.raises(ValidationError):
        JourneysInput(origin="Oslo S", destination_lat=60.0)
