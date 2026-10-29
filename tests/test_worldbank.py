"""World Development Indicators, against recordings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.registry import operations
from kildeverk.sources.worldbank.ops import ALIASES, IndicatorInput

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["world_indicators"].invoke(ctx, arguments)


async def fails(ctx, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, **arguments)
    return caught.value.envelope()["error"]


async def test_the_nordics_ranked_on_their_latest_value(ctx):
    result = await call(ctx, indicator="gdp_per_capita")
    data = result["data"]
    assert data["code"] == ALIASES["gdp_per_capita"] and "GDP per capita" in data["name"]
    assert [v["country_code"] for v in data["values"]] == ["NOR", "SWE", "DNK", "FIN", "ISL"]
    latest = data["latest"]
    assert [r["rank"] for r in latest] == [1, 2, 3, 4, 5]
    assert [r["value"] for r in latest] == sorted((r["value"] for r in latest), reverse=True)
    assert "mrnev=1" in result["provenance"][0]["request"]["url"]
    assert result["provenance"][0]["licence"]["id"] == "CC-BY-4.0"


async def test_a_range_of_years_for_regions(ctx):
    data = (
        await call(
            ctx,
            indicator="SP.DYN.LE00.IN",
            countries=["NOR", "WLD", "EUU"],
            from_year=2015,
            to_year=2020,
        )
    )["data"]
    assert {v["year"] for v in data["values"]} == set(range(2015, 2021))
    codes = [v["country_code"] for v in data["values"]]
    assert codes == sorted(codes, key=["NOR", "WLD", "EUU"].index)  # as asked
    assert data["latest"][0]["country_code"] == "NOR"


async def test_archived_indicators_are_refused_with_the_current_one(ctx):
    error = await fails(ctx, indicator="EN.ATM.CO2E.PC")
    assert error["code"] == "INVALID_ARGUMENT" and "WDI Database Archives" in error["message"]
    assert error["next_call"] == {
        "tool": "world_indicators",
        "arguments": {"indicator": "co2_per_capita"},
    }


async def test_an_unknown_indicator_lists_the_common_names(ctx):
    error = await fails(ctx, indicator="XX.FAKE")
    assert error["code"] == "NOT_FOUND" and "gdp_per_capita" in error["message"]


async def test_one_unknown_country_does_not_sink_the_others(ctx):
    result = await call(ctx, indicator="population", countries=["SE", "NO", "ZZZ"])
    data = result["data"]
    assert [r["country_code"] for r in data["latest"]] == ["SWE", "NOR"]
    assert data["missing"] == ["ZZZ"]
    assert any("Not World Bank country codes: ZZZ" in n for n in result["notes"])


async def test_countries_without_values_in_the_period(ctx):
    result = await call(
        ctx, indicator="gini", countries=["NOR", "SWE"], from_year=2024, to_year=2025
    )
    assert result["data"]["missing"] == ["NOR", "SWE"] and result["data"]["latest"] == []
    assert any("in this period" in n for n in result["notes"])


def test_input_rules():
    assert IndicatorInput(indicator="gdp", countries=["nor", " se "]).countries == ["NOR", "SE"]
    with pytest.raises(ValidationError):
        IndicatorInput(indicator="gdp", countries=["Norway"])
    with pytest.raises(ValidationError):
        IndicatorInput(indicator="gdp", from_year=2020, to_year=2010)
