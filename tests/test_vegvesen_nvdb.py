"""The road at a point, from NVDB, against recordings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.registry import operations
from kildeverk.sources.vegvesen_nvdb.ops import RoadInput

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["road_at_point"].invoke(ctx, arguments)


async def test_a_municipal_road_with_its_speed_limit(ctx):
    result = await call(ctx, lat=60.3790, lon=5.3388)
    data = result["data"]
    assert (
        data["road"]["category"] == "municipal road" and data["road"]["municipality_code"] == "4601"
    )
    assert data["road"]["reference"].startswith("KV") and data["speed_limit_kmh"] == 30
    assert {p["source_id"] for p in result["provenance"]} == {"vegvesen_nvdb"}
    assert len(result["provenance"]) == 6  # the position and five kinds of object


async def test_a_county_road_with_traffic(ctx):
    data = (await call(ctx, lat=60.3925, lon=5.3185, max_distance_m=80))["data"]
    assert data["road"]["category"] == "county road"
    traffic = data["traffic"]
    assert traffic["vehicles_per_day"] > 1000 and traffic["year"] >= 2020


async def test_no_road_nearby(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, lat=61.6, lon=8.3, max_distance_m=20)
    assert caught.value.envelope()["error"]["code"] == "NOT_FOUND"


async def test_requests_name_the_client(ctx, replay):
    await call(ctx, lat=60.3790, lon=5.3388)
    nvdb = [r for r in replay.requests if "nvdbapiles" in str(r.url)]
    assert nvdb and all(r.headers.get("x-client") for r in nvdb)


def test_input_rules():
    with pytest.raises(ValidationError):
        RoadInput(lat=60, lon=5, max_distance_m=1000)
