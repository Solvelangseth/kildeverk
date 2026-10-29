"""Storm-surge return levels and record sea levels, against recordings."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.kartverket_sea.levels import LevelsInput, _date
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["sea_level_extremes"].invoke(ctx, arguments)


async def test_return_levels_records_and_tides_in_nn2000(ctx):
    data = (await call(ctx, lat=60.398, lon=5.32))["data"]
    assert (data["place"], data["gauge"], data["reference"]) == ("Bergen", "Bergen", "NN2000")
    highs = data["high_water_return_levels"]
    assert [r["years"] for r in highs] == [1, 5, 10, 20, 50, 100, 200, 1000]
    assert [r["level_cm"] for r in highs] == sorted(r["level_cm"] for r in highs)
    assert [r["years"] for r in data["low_water_return_levels"]] == [1, 5, 20]
    assert data["highest_observed"]["date"] == "1990-02-27"
    tides = {t["code"]: t["level_cm"] for t in data["tidal_levels"]}
    assert tides["NN2000"] == 0.0 and tides["HAT"] > tides["MHW"] > tides["MSL"] > tides["LAT"]
    assert data["high_end_level_cm"] > highs[-1]["level_cm"]


async def test_a_gauge_in_chart_datum_with_a_record_given_as_a_year(ctx):
    data = (await call(ctx, station="OSL", reference="chart_datum"))["data"]
    assert data["reference"] == "CD"
    assert data["highest_observed"] == {"level_cm": 270.1, "date": None, "when": "1914"}


async def test_a_record_with_a_storm_named(ctx):
    record = (await call(ctx, station="HFT"))["data"]["highest_observed"]
    assert record["date"] == "2011-11-26" and "Berit" in record["when"]


async def test_inland_has_no_sea_levels(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, lat=61.5, lon=9.0)
    error = caught.value.envelope()["error"]
    assert error["code"] == "NOT_FOUND" and "too far away from the coast" in error["message"]


def test_dates_and_input_rules():
    assert _date("26.11.2011 under stormen Berit") == dt.date(2011, 11, 26)
    assert _date("1914") is None
    with pytest.raises(ValidationError):
        LevelsInput(lat=60.4)
    with pytest.raises(ValidationError):
        LevelsInput(lat=60.4, lon=5.3, station="BGO")
