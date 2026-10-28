"""Public transport tools against recorded Entur responses."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.settings import Settings
from kildeverk.sources.entur.models import DeparturesInput, FindStopsInput
from kildeverk.sources.entur.ops import _start
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


async def test_stop_search_by_name_returns_nsr_stop_places(ctx, replay):
    result = await call(ctx, "transit_find_stops", query="Oslo S", limit=3)
    first = result["data"]["stops"][0]
    assert first["id"] == "NSR:StopPlace:59872" and first["name"] == "Oslo S"
    assert first["municipality_code"] == "0301" and "rail" in first["modes"]
    assert all(s["id"].startswith("NSR:StopPlace:") for s in result["data"]["stops"])
    [prov] = result["provenance"]
    assert prov["licence"]["id"] == "NLOD-2.0" and prov["source_id"] == "entur_geocoder"
    assert "layers=stopPlace" in prov["request"]["url"]
    assert replay.requests[-1].headers["et-client-name"] == "kildeverk-local"


async def test_stops_near_a_point_carry_distance(ctx):
    result = await call(ctx, "transit_find_stops", lat=60.3913, lon=5.3221, radius_km=0.5)
    stops = result["data"]["stops"]
    distances = [s["distance_km"] for s in stops]
    assert stops and distances == sorted(distances) and distances[-1] <= 0.5
    assert "/reverse?" in result["provenance"][0]["request"]["url"]


async def test_stops_by_municipality_and_type(ctx):
    result = await call(ctx, "transit_find_stops", municipality="4601", stop_types=["railStation"])
    stops = result["data"]["stops"]
    assert {s["municipality_code"] for s in stops} == {"4601"}
    assert all("railStation" in s["stop_types"] for s in stops)
    assert "Bergen stasjon" in {s["name"] for s in stops}


async def test_query_with_a_point_ranks_nearby_and_says_so(ctx):
    result = await call(
        ctx, "transit_find_stops", query="Bergen stasjon", lat=60.39, lon=5.33, limit=3
    )
    assert result["data"]["stops"][0]["distance_km"] < 1
    assert any("rank higher" in n for n in result["notes"])


async def test_no_stop_found_is_an_empty_result_with_a_hint(ctx):
    result = await call(ctx, "transit_find_stops", query="qqxxzzvv")
    assert result["data"]["stops"] == []
    assert any("No stop matched" in n for n in result["notes"])


def test_stop_search_needs_a_filter():
    with pytest.raises(ValidationError):
        FindStopsInput()
    with pytest.raises(ValidationError):
        FindStopsInput(lat=60.0)


async def test_departures_from_a_stop_place(ctx, replay):
    result = await call(ctx, "transit_departures", stop="NSR:StopPlace:59872", limit=5)
    data = result["data"]
    assert data["stop_name"] == "Oslo S" and len(data["departures"]) == 5
    first = data["departures"][0]
    assert first["line"] and first["destination"] and first["platform"]
    assert first["delay_s"] == int((_iso(first["expected"]) - _iso(first["aimed"])).total_seconds())
    times = [_iso(d["expected"]) for d in data["departures"]]
    assert times == sorted(times)
    sent = json.loads(replay.requests[-1].content)
    assert sent["variables"] == {
        "id": "NSR:StopPlace:59872",
        "n": 5,
        "range": 7200,
        "cancelled": True,
    }
    assert "stopPlace(id: $id)" in sent["query"]
    assert result["provenance"][0]["request"]["body"] == sent


async def test_mode_filter_and_situations_are_collected_once(ctx):
    result = await call(
        ctx, "transit_departures", stop="NSR:StopPlace:59872", modes=["rail"], within_minutes=60
    )
    data = result["data"]
    assert {d["mode"] for d in data["departures"]} == {"rail"}
    known = {s["id"] for s in data["situations"]}
    referenced = {i for d in data["departures"] for i in d["situation_ids"]}
    assert referenced == known and len(known) == len(data["situations"])
    assert all(s["summary"] for s in data["situations"])


async def test_departures_from_one_quay(ctx, replay):
    result = await call(ctx, "transit_departures", stop="NSR:Quay:571", limit=3)
    data = result["data"]
    assert data["stop_name"] == "Oslo S, platform 11"
    assert {d["platform"] for d in data["departures"]} == {"11"}
    assert "quay(id: $id)" in json.loads(replay.requests[-1].content)["query"]


async def test_a_later_start_is_sent_in_norwegian_time(ctx, replay):
    result = await call(
        ctx, "transit_departures", stop="NSR:StopPlace:58366", start="2026-10-29T08:00:00", limit=3
    )
    assert (
        json.loads(replay.requests[-1].content)["variables"]["start"] == "2026-10-29T08:00:00+01:00"
    )
    assert all(d["aimed"] >= "2026-10-29T08:00" for d in result["data"]["departures"])
    assert {d["mode"] for d in result["data"]["departures"]} <= {"tram", "metro", "bus"}


def test_naive_start_follows_summer_time():
    import datetime as dt

    assert _start(dt.datetime(2026, 7, 1, 8)) == "2026-07-01T08:00:00+02:00"
    assert _start(dt.datetime(2026, 7, 1, 8, tzinfo=dt.UTC)) == "2026-07-01T08:00:00+00:00"


async def test_unknown_stop_is_not_found_with_a_next_call(ctx):
    error = await fails(ctx, "transit_departures", stop="NSR:StopPlace:999999999")
    assert error["code"] == "NOT_FOUND"
    assert error["next_call"]["tool"] == "transit_find_stops"


def test_stop_ids_must_be_nsr_stop_places_or_quays():
    with pytest.raises(ValidationError):
        DeparturesInput(stop="Oslo S")
    with pytest.raises(ValidationError):
        DeparturesInput(stop="NSR:GroupOfStopPlaces:1")
    DeparturesInput(stop="NSR:Quay:571")


def test_client_name_can_be_set():
    assert Settings(_env_file=None).et_client_name == "kildeverk-local"
    assert Settings(_env_file=None, deployment="public").et_client_name == "kildeverk-public"
    assert Settings(_env_file=None, entur_client_name="acme-app").et_client_name == "acme-app"


def _iso(value: str):
    import datetime as dt

    return dt.datetime.fromisoformat(value)
