"""Company tools against recorded Enhetsregisteret responses."""

from __future__ import annotations

import json

import httpx
import pytest

from kildeverk.core.errors import ToolError
from kildeverk.sources.brreg.models import GetInput, SearchInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


async def test_get_a_company_with_its_subunits(ctx, replay):
    result = await call(
        ctx, "companies_get", org_number="923609016", include_subunits=True, subunits_limit=3
    )
    company = result["data"]
    assert company["name"] == "EQUINOR ASA" and company["kind"] == "main_unit"
    assert company["legal_form"]["code"] == "ASA"
    assert company["municipality"] == {"code": "1103", "description": "STAVANGER"}
    assert [i["code"] for i in company["industries"]][:2] == ["06.100", "06.200"]
    assert company["registers"]["business_register"] is True
    assert company["share_capital"]["currency"] == "NOK"
    assert {"name": "STATOIL ASA", "from": "2001-05-11", "to": "2007-10-01"} in company[
        "former_names"
    ]
    assert company["register_page"].endswith("/923609016")
    assert len(company["subunits"]["items"]) == 3 and company["subunits"]["total"] > 3
    assert any("raise subunits_limit" in note for note in result["notes"])
    unit_prov, subunit_prov = result["provenance"]
    assert unit_prov["licence"]["id"] == "NLOD-2.0"
    assert subunit_prov["request"]["url"].endswith("/underenheter?overordnetEnhet=923609016&size=3")
    accepts = {r.headers["accept"] for r in replay.requests}
    assert accepts == {
        "application/vnd.brreg.enhetsregisteret.enhet.v2+json",
        "application/vnd.brreg.enhetsregisteret.underenhet.v2+json",
    }


async def test_contact_details_are_never_returned(ctx):
    company = (await call(ctx, "companies_get", org_number="923609016"))["data"]
    text = json.dumps(company)
    assert "telefon" not in text and "mobil" not in text and "epost" not in text


async def test_a_subunit_number_is_found_too(ctx):
    company = (await call(ctx, "companies_get", org_number="973861883"))["data"]
    assert company["kind"] == "subunit"
    assert company["parent_org_number"] == "923609016"
    assert company["registers"] is None


async def test_public_body_names_the_body_above_it(ctx):
    company = (await call(ctx, "companies_get", org_number="974760673"))["data"]
    assert company["legal_form"]["code"] == "ORGL"
    assert company["parent_org_number"] == "912660680"


async def test_unknown_number_is_not_found(ctx):
    error = await fails(ctx, "companies_get", org_number="999999999")
    assert error["code"] == "NOT_FOUND" and "companies_search" in error["message"]


def test_check_digit_is_validated_before_any_request():
    GetInput(org_number="923 609 016")
    with pytest.raises(ValueError, match="check digit"):
        GetInput(org_number="923609017")


async def test_search_by_name(ctx):
    result = await call(ctx, "companies_search", name="equinor", limit=5)
    data = result["data"]
    assert data["total_matches"] > 5 and len(data["companies"]) == 5
    assert all("EQUINOR" in c["name"].upper() for c in data["companies"])
    assert "konkurs=false" in result["provenance"][0]["request"]["url"]


async def test_search_by_place_industry_and_size(ctx):
    result = await call(
        ctx,
        "companies_search",
        municipality=["4601"],
        industry=["62"],
        sort="most_employees",
        limit=5,
    )
    companies = result["data"]["companies"]
    employees = [c["employees"] or 0 for c in companies]
    assert employees == sorted(employees, reverse=True)
    url = result["provenance"][0]["request"]["url"]
    assert "kommunenummer=4601" in url and "naeringskode=62" in url
    assert "sort=antallAnsatte%2CDESC" in url


async def test_old_industry_codes_get_a_hint(ctx):
    result = await call(ctx, "companies_search", industry=["62.010"])
    assert result["data"]["companies"] == []
    assert any("SN2025" in note for note in result["notes"])


async def test_search_needs_a_filter_and_respects_the_window(ctx):
    assert (await fails(ctx, "companies_search"))["code"] == "INVALID_ARGUMENT"
    error = await fails(ctx, "companies_search", name="as", limit=100, page=100)
    assert "10,000" in error["message"]


def test_search_input_accepts_rest_style_lists_and_rejects_bad_values():
    assert SearchInput(municipality="0301,4601").municipality == ["0301", "4601"]
    with pytest.raises(ValueError):
        SearchInput(municipality="Oslo")
    with pytest.raises(ValueError, match="0, 1, or 5"):
        SearchInput(min_employees=3)


async def test_withdrawn_entities_are_refused_and_purged(ctx):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"organisasjonsnummer": "923609016", "navn": "X"})
        return httpx.Response(410, json={"organisasjonsnummer": "923609016"})

    up = ctx.upstream("brreg")
    up.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await call(ctx, "companies_get", org_number="923609016")
    # Expire the cached copy, then the register withdraws the entity.
    up._clock = lambda: 10**12
    error = await fails(ctx, "companies_get", org_number="923609016")
    assert error["code"] == "NOT_FOUND" and "withdrawn" in error["message"]
    assert await ctx.cache.stats() == {}
    await up.client.aclose()
