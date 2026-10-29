"""USGS earthquakes, against recordings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.sources.registry import operations
from kildeverk.sources.usgs.ops import QuakesInput, _distance_km

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["hazards_earthquakes"].invoke(ctx, arguments)


async def test_the_largest_off_western_norway(ctx):
    result = await call(
        ctx,
        lat=60.4,
        lon=5.3,
        radius_km=300,
        start="2000-01-01",
        end="2025-12-31",
        min_magnitude=4,
        order="magnitude",
        limit=5,
    )
    data = result["data"]
    quakes = data["quakes"]
    assert len(quakes) == 5 and data["more"] is True
    magnitudes = [q["magnitude"] for q in quakes]
    assert magnitudes == sorted(magnitudes, reverse=True) and magnitudes[-1] >= 4
    assert all(q["distance_km"] <= 300 for q in quakes)
    assert all("2000-01-01" <= q["time"][:10] <= "2025-12-31" for q in quakes)
    request = result["provenance"][0]["request"]["url"]
    # The end day is inclusive, and one extra event is asked for to see if there are more.
    assert "endtime=2026-01-01" in request and "limit=6" in request
    assert result["provenance"][0]["licence"]["id"] == "US-public-domain"


async def test_newest_first_by_default(ctx):
    quakes = (await call(ctx, lat=66.9, lon=13.6, start="2025-10-01", end="2026-10-01"))["data"][
        "quakes"
    ]
    times = [q["time"] for q in quakes]
    assert times == sorted(times, reverse=True)


async def test_none_found_says_what_to_try(ctx):
    result = await call(
        ctx, lat=59.9, lon=10.7, radius_km=10, start="2025-01-01", end="2025-12-31", min_magnitude=5
    )
    assert result["data"]["quakes"] == [] and result["data"]["more"] is False
    assert any("Try a lower magnitude" in n for n in result["notes"])


def test_distance_and_input_rules():
    assert _distance_km(60.0, 5.0, 61.0, 5.0) == pytest.approx(111.2, abs=0.1)
    with pytest.raises(ValidationError):
        QuakesInput(lat=60, lon=5, start="2025-02-01", end="2025-01-01")
    with pytest.raises(ValidationError):
        QuakesInput(lat=60, lon=5, radius_km=5000)
