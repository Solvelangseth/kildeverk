"""Elhub electricity data, against recordings."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.elhub import ops as elhub
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


# --- electricity_municipality ------------------------------------------------------


async def test_three_days_by_group_with_capacity(ctx):
    result = await call(
        ctx,
        "electricity_municipality",
        municipality="4601",
        from_date="2026-10-22",
        to_date="2026-10-24",
    )
    data = result["data"]
    assert (data["code"], data["name"], data["days_with_figures"]) == ("4601", "Bergen", 3)
    assert [d["date"] for d in data["days"]] == ["2026-10-22", "2026-10-23", "2026-10-24"]
    assert data["hours"] == []
    assert {g["group"] for g in data["by_group"]} == {"private", "business", "industry"}
    assert sum(g["share_pct"] for g in data["by_group"]) == pytest.approx(100, abs=0.2)
    assert sum(d["total_mwh"] for d in data["days"]) == pytest.approx(data["total_mwh"], rel=1e-6)
    day = data["days"][0]
    assert day["total_mwh"] == pytest.approx(
        day["private_mwh"] + day["business_mwh"] + day["industry_mwh"], rel=1e-6
    )
    assert data["average_mwh_per_day"] == pytest.approx(data["total_mwh"] / 3, rel=1e-3)
    assert data["capacity_date"] == "2026-10-24" and data["capacity"]
    solar = next(c for c in data["capacity"] if c["kind"] == "solar")
    assert 0 < solar["prosumer_mw"] <= solar["mw"]
    # One request per day, and one for capacity.
    assert len(result["provenance"]) == 4
    assert result["provenance"][0]["licence"]["id"] == "CC-BY-4.0"
    assert any("private is homes and cabins" in n for n in result["notes"])


async def test_the_autumn_clock_change_has_25_hours_and_old_codes_are_followed(ctx):
    result = await call(
        ctx,
        "electricity_municipality",
        municipality="1201",
        from_date="2026-10-25",
        to_date="2026-10-25",
        resolution="hour",
    )
    data = result["data"]
    assert data["code"] == "4601"
    assert len(data["hours"]) == 25
    assert data["hours"][2]["start"] == "2026-10-25T02:00:00+02:00"
    assert data["hours"][3]["start"] == "2026-10-25T02:00:00+01:00"
    assert sum(h["total_mwh"] for h in data["hours"]) == pytest.approx(data["total_mwh"], rel=1e-6)
    assert result["notes"][0] == "1201 is today 4601 Bergen."


async def test_a_name_and_a_hydropower_municipality(ctx):
    result = await call(
        ctx,
        "electricity_municipality",
        municipality="Suldal",
        from_date="2026-10-27",
        to_date="2026-10-27",
    )
    data = result["data"]
    assert data["code"] == "1134"
    assert data["capacity"][0]["kind"] == "hydro" and data["capacity"][0]["mw"] > 1000
    assert data["capacity_mw"] == pytest.approx(sum(c["mw"] for c in data["capacity"]), abs=0.01)


async def test_a_municipality_elhub_does_not_know(ctx):
    error = await fails(
        ctx,
        "electricity_municipality",
        municipality="9999",
        from_date="2026-10-27",
        to_date="2026-10-27",
    )
    assert error["code"] == "NOT_FOUND" and error["next_call"]["tool"] == "regions_resolve"


async def test_period_rules(ctx, monkeypatch):
    monkeypatch.setattr(elhub, "_today", lambda: dt.date(2026, 10, 29))
    retry = ("electricity_municipality", {"municipality": "4601"})
    assert elhub._period(None, None, retry)[:2] == (dt.date(2026, 10, 22), dt.date(2026, 10, 28))
    assert elhub._period(dt.date(2026, 1, 1), None, retry)[:2] == (
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 7),
    )
    assert elhub._period(None, dt.date(2026, 3, 10), retry)[:2] == (
        dt.date(2026, 3, 4),
        dt.date(2026, 3, 10),
    )
    _, _, notes = elhub._period(dt.date(2026, 10, 29), dt.date(2026, 10, 29), retry)
    assert any("incomplete" in n for n in notes)
    for first, last, words in [
        (dt.date(2026, 10, 1), dt.date(2026, 10, 30), "future"),
        (dt.date(2026, 10, 2), dt.date(2026, 10, 1), "after"),
        (dt.date(2020, 12, 31), dt.date(2021, 1, 2), "2021-01-01"),
        (dt.date(2026, 1, 1), dt.date(2026, 2, 1), "at most 31 days"),
    ]:
        with pytest.raises(ToolError) as caught:
            elhub._period(first, last, retry)
        assert words in caught.value.body.message
        assert caught.value.body.next_call.tool == "electricity_municipality"


async def test_hourly_is_limited_to_three_days(ctx):
    error = await fails(
        ctx,
        "electricity_municipality",
        municipality="4601",
        from_date="2026-10-20",
        to_date="2026-10-24",
        resolution="hour",
    )
    assert error["code"] == "INVALID_ARGUMENT"
    assert "resolution" not in error["next_call"]["arguments"]


def test_municipality_input_rules():
    with pytest.raises(ValidationError):
        elhub.MunicipalityInput(municipality="46")
    with pytest.raises(ValidationError):
        elhub.MunicipalityInput(municipality="4601", resolution="minute")


# --- electricity_price_areas -------------------------------------------------------


async def test_one_day_in_every_area_with_a_total_for_norway(ctx):
    result = await call(
        ctx, "electricity_price_areas", from_date="2026-10-27", to_date="2026-10-27"
    )
    data = result["data"]
    areas = [t["area"] for t in data["totals"]]
    assert areas == ["NO1", "NO2", "NO3", "NO4", "NO5", "NO"]
    norway = data["totals"][-1]
    parts = data["totals"][:-1]
    assert norway["consumption_mwh"] == pytest.approx(sum(t["consumption_mwh"] for t in parts))
    assert norway["production_mwh"] == pytest.approx(sum(t["production_mwh"] for t in parts))
    assert set(norway["consumption_by_group"]) == {
        "household",
        "cabin",
        "primary",
        "secondary",
        "tertiary",
    }
    assert norway["production_by_kind"]["hydro"] > norway["production_by_kind"]["wind"]
    for total in data["totals"]:
        assert total["net_mwh"] == pytest.approx(
            total["production_mwh"] - total["consumption_mwh"], abs=0.01
        )
    assert len(data["days"]) == 5 and {d["date"] for d in data["days"]} == {"2026-10-27"}
    # Consumption and production for each of the five areas.
    assert len(result["provenance"]) == 10


async def test_a_long_period_is_fetched_in_parts(ctx):
    result = await call(
        ctx,
        "electricity_price_areas",
        areas=["NO4"],
        from_date="2026-01-01",
        to_date="2026-01-30",
    )
    data = result["data"]
    assert [t["area"] for t in data["totals"]] == ["NO4"]
    assert next(d["date"] for d in data["days"]) == "2026-01-01"
    assert [d["date"] for d in data["days"]][-1] == "2026-01-30" and len(data["days"]) == 30
    # Two consumption and two production requests: 28 days, then 2.
    titles = [p["title"] for p in result["provenance"]]
    assert sum("2026-01-01 to 2026-01-28" in t for t in titles) == 2
    assert sum("2026-01-29 to 2026-01-30" in t for t in titles) == 2


def test_price_area_input_rules():
    with pytest.raises(ValidationError):
        elhub.PriceAreasInput(areas=["NO6"])
    with pytest.raises(ValidationError):
        elhub.PriceAreasInput(areas=[])
