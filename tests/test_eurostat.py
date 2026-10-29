"""Eurostat search and data, against recordings (a slice of the table of contents)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.eurostat.ops import DataInput, _open
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def test_search_ranks_full_matches_and_recent_data_first(ctx):
    result = await call(ctx, "eurostat_search", query="electricity prices household", limit=5)
    datasets = result["data"]["datasets"]
    assert datasets[0]["code"] == "nrg_pc_204"
    assert all("lectricity" in d["title"] for d in datasets)
    assert result["provenance"][0]["source_id"] == "eurostat"


async def test_search_with_nothing_found(ctx):
    result = await call(ctx, "eurostat_search", query="zzzqx")
    assert result["data"]["total_matches"] == 0
    assert any("Try fewer or broader words" in n for n in result["notes"])


async def test_one_series_for_the_nordics_and_the_eu(ctx):
    result = await call(
        ctx,
        "eurostat_data",
        dataset="une_rt_a",
        filters={"age": ["Y15-74"], "unit": ["PC_ACT"], "sex": ["T"]},
    )
    data = result["data"]
    geos = list(dict.fromkeys(r["geo"] for r in data["rows"]))
    assert geos == ["NO", "SE", "DK", "FI", "IS", "EU27_2020"]  # as asked
    norway = [r for r in data["rows"] if r["geo"] == "NO"]
    assert len(norway) == 5 and [r["period"] for r in norway] == sorted(r["period"] for r in norway)
    assert {r["other"]["sex"] for r in data["rows"]} == {"T"}
    assert all(len(d["values"]) == 1 for d in data["dimensions"])
    assert data["restricted_geo"] == []
    request = result["provenance"][0]["request"]["url"]
    assert "geo=NO&geo=SE" in request and "lastTimePeriod=5" in request


async def test_regions_and_one_period(ctx):
    rows = (
        await call(
            ctx,
            "eurostat_data",
            dataset="demo_r_pjangrp3",
            geo=["NO08", "NO09"],
            filters={"sex": ["T"], "age": ["TOTAL"]},
            last_periods=1,
        )
    )["data"]["rows"]
    assert [r["geo"] for r in rows] == ["NO08", "NO09"] and rows[0]["value"] > rows[1]["value"]


async def test_unfiltered_dimensions_and_restricted_countries_are_flagged(ctx):
    result = await call(ctx, "eurostat_data", dataset="une_rt_a", geo=["NO", "US"], last_periods=1)
    assert result["data"]["restricted_geo"] == ["US"]
    assert any("non-commercial use only" in n for n in result["notes"])
    assert any(n.startswith("Several values for") for n in result["notes"])


async def test_an_unknown_dataset(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, "eurostat_data", dataset="nonexist_xx")
    error = caught.value.envelope()["error"]
    assert error["code"] == "NOT_FOUND" and error["next_call"]["tool"] == "eurostat_search"


def test_open_countries_and_input_rules():
    assert all(_open(g) for g in ("NO", "EL", "EU27_2020", "EA20", "NO08", "CH"))
    assert not any(_open(g) for g in ("US", "JP", "CN"))
    with pytest.raises(ValidationError):
        DataInput(dataset="une_rt_a", last_periods=0)
