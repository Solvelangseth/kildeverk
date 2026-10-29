"""Regobs field observations, against recordings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.sources.nve_regobs.ops import ObservationsInput, credit_name
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["hazards_field_observations"].invoke(ctx, arguments)


async def test_snow_observations_newest_first_with_credit(ctx):
    result = await call(
        ctx,
        lat=69.65,
        lon=18.95,
        radius_km=30,
        hazards=["snow"],
        start="2026-03-01",
        end="2026-03-31",
        limit=3,
    )
    data = result["data"]
    rows = data["observations"]
    assert len(rows) == 3 and data["total_matches"] > 3
    assert [r["time"] for r in rows] == sorted((r["time"] for r in rows), reverse=True)
    assert {r["hazard"] for r in rows} == {"snow"}
    assert all(
        r["observer"] and r["url"].startswith("https://www.regobs.no/registration/") for r in rows
    )
    assert all(r["findings"] for r in rows)
    assert all(len(f["text"]) <= 600 for r in rows for f in r["findings"])
    assert any("raise limit" in n for n in result["notes"])
    assert any("Credit Regobs.no" in n for n in result["notes"])
    assert "credit: Regobs.no and the observer" in result["provenance"][0]["licence"]["name"]


async def test_landslides_after_a_storm(ctx):
    rows = (
        await call(
            ctx,
            lat=61.1,
            lon=10.4,
            hazards=["flood", "landslide"],
            start="2023-08-06",
            end="2023-08-12",
            radius_km=50,
            limit=3,
        )
    )["data"]["observations"]
    assert {r["hazard"] for r in rows} <= {"flood", "landslide"}
    assert all(r["municipality_code"] and len(r["municipality_code"]) == 4 for r in rows)
    # No username comes back as an e-mail address.
    assert all("." not in (r["observer"] or "").split("@")[-1] for r in rows)


async def test_nothing_found_says_what_to_try(ctx):
    result = await call(
        ctx,
        lat=59.91,
        lon=10.75,
        radius_km=1,
        hazards=["ice"],
        start="2026-07-01",
        end="2026-07-31",
    )
    assert result["data"]["observations"] == []
    assert any("Try a wider radius" in n for n in result["notes"])


def test_usernames_that_are_e_mail_addresses_are_cut():
    assert credit_name("ola.nordmann@nve.no") == "ola.nordmann@nve"
    assert credit_name("guro@svv.no") == "guro@svv"
    assert credit_name("Ingrid@NVE") == "Ingrid@NVE"
    assert credit_name("Pudding") == "Pudding"
    assert credit_name(None) is None


def test_input_rules():
    with pytest.raises(ValidationError):
        ObservationsInput(lat=60, lon=10, hazards=["volcano"])
    with pytest.raises(ValidationError):
        ObservationsInput(lat=60, lon=10, start="2026-02-01", end="2026-01-01")
