"""Stortinget, traffic counts and the school register, against recordings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.registry import operations
from kildeverk.sources.stortinget.ops import _date
from kildeverk.sources.udir_nsr.ops import SchoolsSearchInput
from kildeverk.sources.vegvesen_traffic.ops import FindPointsInput, VolumesInput, _road

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


# --- Stortinget --------------------------------------------------------------------


async def test_cases_by_words_in_the_title(ctx):
    result = await call(ctx, "parliament_cases", query="energipriser", session="2025-2026")
    [case] = result["data"]["cases"]
    assert case["id"] == 200084 and case["status"] == "dealt_with"
    assert case["document_group"] == "members_proposal" and case["committee"]["id"] == "FINANS"
    assert result["provenance"][0]["licence"]["id"] == "NLOD-2.0"


async def test_cases_by_type_newest_first(ctx):
    result = await call(ctx, "parliament_cases", session="2025-2026", type="law", limit=5)
    cases = result["data"]["cases"]
    assert len(cases) == 5 and {c["type"] for c in cases} == {"law"}
    assert result["data"]["total_matches"] > 5 and result["truncated"] is True
    updated = [c["updated"] for c in cases]
    assert updated == sorted(updated, reverse=True)


async def test_unknown_session_is_not_found(ctx):
    error = await fails(ctx, "parliament_cases", session="1850-1851")
    assert error["code"] == "NOT_FOUND" and error["next_call"]["tool"] == "parliament_cases"


async def test_case_with_votes_counted_by_party(ctx):
    result = await call(ctx, "parliament_case", case_id=200084)
    data = result["data"]
    assert data["rapporteurs"] == ["Tuva Moflag (A)"] and "Elektrisitet" in data["topics"]
    vote = next(v for v in data["votes"] if v["id"] == 28502)
    assert vote["recorded_by_name"] and vote["adopted"] is True
    assert (vote["for_count"], vote["against_count"], vote["absent_count"]) == (68, 29, 72)
    parties = {p["party"]: p for p in vote["parties"]}
    assert sum(p["for_votes"] for p in parties.values()) == 68
    assert sum(p["against_votes"] for p in parties.values()) == 29
    assert parties["FrP"]["against_votes"] == 29 and parties["A"]["for_votes"] > 0
    assert data["page_url"].endswith("?p=200084")
    assert len(result["provenance"]) >= 3


async def test_case_decided_without_a_count(ctx):
    result = await call(ctx, "parliament_case", case_id=107200)
    assert all(v["for_count"] is None for v in result["data"]["votes"])
    assert any("not counted" in n for n in result["notes"])


async def test_unknown_case_is_not_found_despite_the_upstream_500(ctx):
    error = await fails(ctx, "parliament_case", case_id=1)
    assert error["code"] == "NOT_FOUND" and error["retryable"] is False


async def test_members_by_period_and_party(ctx):
    sv = await call(ctx, "parliament_members", period="2021-2025", party="SV")
    assert sv["data"]["by_party"] == {"SV": sv["data"]["count"]}
    everyone = await call(ctx, "parliament_members", period="2025-2029")
    assert everyone["data"]["count"] == 169
    assert sum(everyone["data"]["by_party"].values()) == 169
    assert "epost" not in str(everyone)


def test_stortinget_dates():
    assert _date("/Date(1781864904800+0200)/").isoformat() == "2026-06-19T12:28:24.800000+02:00"
    assert _date("not a date") is None


# --- traffic -----------------------------------------------------------------------


async def test_points_by_name(ctx):
    result = await call(ctx, "traffic_find_points", name="Nygårdstunnelen")
    points = result["data"]["points"]
    assert "09194V804833" in {p["id"] for p in points}
    assert all(p["status"] == "operational" for p in points)
    assert result["provenance"][0]["licence"]["id"] == "NLOD-2.0"


async def test_points_near_a_point_use_kartverket_for_the_county(ctx):
    result = await call(ctx, "traffic_find_points", lat=59.91, lon=10.75, radius_km=1)
    distances = [p["distance_km"] for p in result["data"]["points"]]
    assert distances and distances == sorted(distances) and distances[-1] <= 1
    assert [p["source_id"] for p in result["provenance"]] == ["kartverket", "vegvesen_traffic"]
    assert any("county border" in n for n in result["notes"])


async def test_points_on_a_road_in_a_municipality(ctx):
    result = await call(ctx, "traffic_find_points", municipality="4601", road="E39", limit=5)
    points = result["data"]["points"]
    assert all(p["municipality_code"] == "4601" and p["road"].startswith("EV39 ") for p in points)


def test_road_names_are_normalised():
    assert _road("E39") == "EV39" and _road("rv 7") == "RV7" and _road("Fv5000") == "FV5000"
    with pytest.raises(ValidationError):
        FindPointsInput(road="highway")


async def test_daily_volumes_split_by_length_and_direction(ctx):
    result = await call(
        ctx, "traffic_volumes", point="09194V804833", start="2026-10-19", end="2026-10-25"
    )
    rows = result["data"]["rows"]
    assert len(rows) == 7
    for r in rows:
        # Vehicles whose length was not measured are in neither group.
        assert 0.9 * r["vehicles"] <= r["light"] + r["heavy"] <= r["vehicles"]
        assert sum(r["by_direction"].values()) == r["vehicles"]


async def test_hourly_volumes_page_through(ctx):
    result = await call(
        ctx,
        "traffic_volumes",
        point="09194V804833",
        resolution="hourly",
        start="2026-10-20",
        end="2026-10-24",
    )
    rows = result["data"]["rows"]
    assert len(rows) == 5 * 24
    assert len(result["provenance"]) == 2  # 100 hours a page


async def test_annual_average_daily_traffic(ctx):
    result = await call(
        ctx, "traffic_volumes", point="09194V804833", resolution="annual", start="2015-01-01"
    )
    rows = result["data"]["rows"]
    assert rows[0]["year"] >= 2015 and all(r["vehicles"] > 1000 for r in rows)
    assert any("ÅDT" in n for n in result["notes"])
    assert any("under 95%" in n for n in result["notes"])


async def test_unknown_point_is_not_found(ctx):
    error = await fails(ctx, "traffic_volumes", point="00000V000000", start="2026-10-19")
    assert error["code"] == "NOT_FOUND"


def test_volume_period_limits():
    with pytest.raises(ValidationError):
        VolumesInput(
            point="09194V804833", resolution="hourly", start="2026-10-01", end="2026-10-20"
        )


# --- schools -----------------------------------------------------------------------


async def test_secondary_schools_in_a_municipality(ctx):
    result = await call(ctx, "schools_search", municipality="4601", level="secondary")
    schools = result["data"]["schools"]
    assert result["data"]["total_matches"] > 20
    assert all("secondary" in s["levels"] and s["municipality_code"] == "4601" for s in schools)
    assert {"public", "private"} <= {s["ownership"] for s in schools}


async def test_private_primary_schools_in_a_county(ctx):
    result = await call(ctx, "schools_search", county="03", ownership="private", level="primary")
    assert all(s["ownership"] == "private" for s in result["data"]["schools"])


async def test_one_school_in_detail(ctx):
    result = await call(ctx, "schools_get", org_number="874738352")
    school = result["data"]
    assert school["name"] == "Alvøen skole" and school["owner"] == "Bergen kommune"
    assert school["pupils"] > 100 and school["grades"] == "1-7"
    assert school["language_form"] == "Bokmål" and school["lat"] and school["address"]


async def test_unknown_school_is_not_found(ctx):
    error = await fails(ctx, "schools_get", org_number="999999999")
    assert error["code"] == "NOT_FOUND"


def test_school_search_needs_an_area_or_name():
    with pytest.raises(ValidationError):
        SchoolsSearchInput(level="primary")
