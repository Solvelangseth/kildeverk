"""Exchange rates and the policy rate against recorded Norges Bank responses."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.norges_bank.models import ExchangeRatesInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def test_latest_rates_for_the_default_currencies(ctx):
    result = await call(ctx, "currency_exchange_rates")
    rows = result["data"]["rows"]
    assert [r["currency"] for r in rows] == ["EUR", "USD", "GBP", "SEK", "DKK"]
    assert len({r["period"] for r in rows}) == 1
    [prov] = result["provenance"]
    assert prov["licence"]["id"] == "not-stated"
    assert "No licence stated" in prov["citation"]


async def test_currencies_quoted_per_hundred_get_a_per_unit_rate(ctx):
    result = await call(ctx, "currency_exchange_rates", currencies=["JPY", "USD"])
    jpy, usd = result["data"]["rows"]
    assert jpy["per"] == 100 and jpy["nok_per_unit"] == pytest.approx(jpy["nok"] / 100)
    assert usd["per"] == 1 and usd["nok_per_unit"] == usd["nok"]
    assert any("per 100 units" in n for n in result["notes"])


async def test_daily_rates_over_a_period_skip_weekends(ctx):
    result = await call(
        ctx, "currency_exchange_rates", currencies=["EUR"], start="2026-10-01", end="2026-10-09"
    )
    periods = [r["period"] for r in result["data"]["rows"]]
    assert periods[0] == "2026-10-01" and periods[-1] == "2026-10-09"
    assert "2026-10-03" not in periods and len(periods) == 7
    assert "startPeriod=2026-10-01" in result["provenance"][0]["request"]["url"]


async def test_monthly_averages(ctx):
    result = await call(
        ctx,
        "currency_exchange_rates",
        currencies=["EUR"],
        frequency="monthly",
        start="2025-01-01",
        end="2025-12-31",
    )
    assert [r["period"] for r in result["data"]["rows"]] == [f"2025-{m:02}" for m in range(1, 13)]
    assert "/EXR/M.EUR.NOK.SP" in result["provenance"][0]["request"]["url"]


async def test_one_unknown_code_among_known_ones_is_a_note(ctx):
    result = await call(ctx, "currency_exchange_rates", currencies=["USD", "XXX"])
    assert [r["currency"] for r in result["data"]["rows"]] == ["USD"]
    assert any("XXX" in n for n in result["notes"])


async def test_only_unknown_codes_is_not_found_with_the_list(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, "currency_exchange_rates", currencies=["XXX"])
    error = caught.value.envelope()["error"]
    assert error["code"] == "NOT_FOUND" and "EUR" in error["message"] and "XXX" in error["message"]


async def test_discontinued_currency_says_when_it_was_last_quoted(ctx):
    result = await call(ctx, "currency_exchange_rates", currencies=["HRK"])
    assert result["data"]["rows"][0]["period"] == "2022-12-30"
    assert any("no longer publishes" in n for n in result["notes"])


def test_end_needs_start():
    with pytest.raises(ValidationError):
        ExchangeRatesInput(end="2025-01-01")
    with pytest.raises(ValidationError):
        ExchangeRatesInput(currencies=["euro"])


async def test_policy_rate_changes_since_a_date(ctx):
    result = await call(ctx, "rates_policy_rate", since="2021-01-01")
    data = result["data"]
    changes = data["changes"]
    assert changes[0] == {"effective": "2021-09-24", "rate": 0.25, "change_pp": 0.25}
    assert data["rate"] == changes[-1]["rate"]
    assert data["unchanged_since"] == changes[-1]["effective"]
    rates = [0.0] + [c["rate"] for c in changes]
    assert all(c["change_pp"] == pytest.approx(b - a) for c, a, b in zip(changes, rates, rates[1:]))


async def test_policy_rate_over_a_short_window(ctx):
    result = await call(ctx, "rates_policy_rate", since="2026-06-01")
    assert len(result["data"]["changes"]) == 1
