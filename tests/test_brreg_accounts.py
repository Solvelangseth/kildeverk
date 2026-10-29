"""Annual accounts from Regnskapsregisteret, against recordings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.brreg.accounts import AccountsInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["companies_accounts"].invoke(ctx, arguments)


async def test_group_and_company_accounts_in_the_reported_currency(ctx):
    result = await call(ctx, org_number="923609016")
    data = result["data"]
    assert (data["legal_form"], data["parent_company"]) == ("ASA", True)
    rows = data["accounts"]
    assert [(a["year"], a["kind"]) for a in rows] == [
        (2025, "group"),
        (2025, "company"),
        (2024, "group"),
        (2024, "company"),
        (2023, "group"),
        (2023, "company"),
    ]
    group = rows[0]
    assert group["currency"] == "USD" and group["accounting_rules"] == "IFRS"
    assert rows[1]["accounting_rules"] == "simplified IFRS"
    assert group["operating_margin_pct"] == pytest.approx(
        group["operating_profit"] / group["revenue"] * 100, abs=0.05
    )
    assert group["equity_ratio_pct"] == pytest.approx(
        group["equity"] / group["total_assets"] * 100, abs=0.05
    )
    earlier = rows[2]
    assert group["revenue_change_pct"] == pytest.approx(
        (group["revenue"] - earlier["revenue"]) / earlier["revenue"] * 100, abs=0.05
    )
    assert rows[-1]["revenue_change_pct"] is None  # nothing older is open
    assert group["audited"] is True
    assert any("USD" in n for n in result["notes"])
    assert result["provenance"][0]["source_id"] == "brreg_accounts"


async def test_one_year_of_one_kind(ctx):
    result = await call(ctx, org_number="983974899", kind="company", year=2025)
    rows = result["data"]["accounts"]
    assert [(a["year"], a["kind"], a["currency"]) for a in rows] == [(2025, "company", "NOK")]
    assert rows[0]["accounting_rules"] == "NGAAP"
    request = result["provenance"][0]["request"]["url"]
    assert "regnskapstype=SELSKAP" in request and "%C3%A5r=2025" in request


async def test_a_small_company_that_opted_out_of_an_audit(ctx):
    rows = (await call(ctx, org_number="932267624"))["data"]["accounts"]
    assert {a["small_company"] for a in rows} == {True}
    assert {a["audited"] for a in rows} == {False}
    # No revenue: no margin, no change.
    assert rows[0]["revenue"] == 0 and rows[0]["operating_margin_pct"] is None


async def test_a_public_body_files_no_accounts(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, org_number="940101808")
    error = caught.value.envelope()["error"]
    assert error["code"] == "NOT_FOUND" and "Public bodies" in error["message"]
    assert error["next_call"] == {"tool": "companies_get", "arguments": {"org_number": "940101808"}}


def test_accounts_input_rules():
    with pytest.raises(ValidationError):
        AccountsInput(org_number="923609017")  # wrong check digit
    with pytest.raises(ValidationError):
        AccountsInput(org_number="923609016", kind="consolidated")
