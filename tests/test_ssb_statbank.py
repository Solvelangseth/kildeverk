"""SSB tools against recorded upstream responses."""

from __future__ import annotations

import pytest

from kildeverk.core.errors import ToolError
from kildeverk.sources.registry import operations
from kildeverk.sources.ssb_statbank import jsonstat

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def fails(ctx, tool, **arguments) -> dict:
    with pytest.raises(ToolError) as caught:
        await call(ctx, tool, **arguments)
    return caught.value.envelope()["error"]


# --- search -------------------------------------------------------------------


async def test_search_returns_summaries_and_provenance(ctx):
    result = await call(ctx, "statistics_search_tables", query="population municipality", limit=3)
    data = result["data"]
    assert data["total_matches"] > 3 and len(data["tables"]) == 3
    table = data["tables"][0]
    assert table["table_id"] and table["title"] and table["subject_path"]
    [prov] = result["provenance"]
    assert prov["licence"]["id"] == "CC-BY-4.0"
    assert prov["request"]["url"].startswith("https://data.ssb.no/api/pxwebapi/v2/tables?query=")
    assert prov["citation"].startswith("Statistics Norway (SSB): ")


async def test_norwegian_words_in_english_search_get_a_hint(ctx):
    result = await call(ctx, "statistics_search_tables", query="befolkning kommune")
    assert result["data"]["tables"] == []
    assert any("lang='no'" in note for note in result["notes"])


# --- describe -----------------------------------------------------------------


async def test_describe_lists_dimensions_measures_and_codelists(ctx):
    data = (await call(ctx, "statistics_describe_table", table_id="07459"))["data"]
    dims = {d["code"]: d for d in data["dimensions"]}
    assert dims["Tid"]["role"] == "time" and dims["Tid"]["can_omit"] is False
    assert dims["Region"]["role"] == "region" and dims["Region"]["values_listed"] == "first"
    assert any(c["id"] == "agg_Fylker2024" for c in dims["Region"]["codelists"])
    assert data["measures"][0]["code"] == "Personer1"
    assert data["first_period"] == "1986" and data["last_period"] >= "2026"


async def test_value_search_finds_a_municipality_code(ctx):
    data = (await call(ctx, "statistics_describe_table", table_id="07459", value_search="bergen"))[
        "data"
    ]
    region = next(d for d in data["dimensions"] if d["code"] == "Region")
    assert region["values_listed"] == "matching"
    assert {"code": "4601", "label": "Bergen"} in region["values"]


async def test_example_arguments_are_accepted_by_get_data(ctx):
    described = (await call(ctx, "statistics_describe_table", table_id="07459"))["data"]
    result = await OPS["statistics_get_data"].invoke(ctx, described["example_arguments"])
    assert result["data"]["row_count"] == 1


async def test_unknown_table_points_to_search(ctx):
    error = await fails(ctx, "statistics_describe_table", table_id="99999")
    assert error["code"] == "NOT_FOUND" and error["upstream_status"] == 404
    assert error["next_call"]["tool"] == "statistics_search_tables"


# --- get data -----------------------------------------------------------------


async def test_get_data_returns_labelled_rows_and_exact_request(ctx):
    result = await call(
        ctx,
        "statistics_get_data",
        table_id="07459",
        select={"Region": ["0301", "4601"], "Tid": {"latest": 2}},
    )
    data = result["data"]
    assert data["row_count"] == 4
    row = data["rows"][0]
    assert row["Region"] == "0301" and row["Region_label"].startswith("Oslo")
    assert isinstance(row["value"], int) and row["value"] > 500_000
    assert [c["key"] for c in data["columns"]][-1] == "value"
    data_prov, meta_prov = result["provenance"]
    assert "valueCodes%5BRegion%5D=0301%2C4601" in data_prov["request"]["url"]
    assert "valueCodes%5BTid%5D=top%282%29" in data_prov["request"]["url"]
    assert meta_prov["request"]["url"].endswith("/tables/07459/metadata?lang=en")


async def test_codelist_aggregates_to_counties_and_defaults_time_to_latest(ctx):
    result = await call(
        ctx, "statistics_get_data", table_id="07459", codelists={"Region": "agg_Fylker2024"}
    )
    assert result["data"]["row_count"] == 16
    assert any("latest value" in note for note in result["notes"])
    sources = [p["request"]["url"] for p in result["provenance"]]
    assert any("/codeLists/agg_Fylker2024" in url for url in sources)


async def test_a_name_instead_of_a_code_suggests_the_lookup(ctx):
    error = await fails(ctx, "statistics_get_data", table_id="07459", select={"Region": ["Bergen"]})
    assert error["code"] == "INVALID_ARGUMENT"
    assert error["next_call"] == {
        "tool": "statistics_describe_table",
        "arguments": {"table_id": "07459", "value_search": "Bergen"},
    }


async def test_unknown_dimension_lists_the_real_ones(ctx):
    error = await fails(ctx, "statistics_get_data", table_id="07459", select={"Year": ["2020"]})
    assert "no dimension 'Year'" in error["message"] and "Tid (year)" in error["message"]


async def test_unknown_codelist_lists_the_offered_ones(ctx):
    error = await fails(ctx, "statistics_get_data", table_id="07459", codelists={"Region": "nope"})
    assert "agg_Fylker2024" in error["message"]


async def test_too_large_is_refused_before_any_data_request(ctx, replay):
    before = len(replay.requests)
    error = await fails(
        ctx, "statistics_get_data", table_id="07459", select={"Region": "*", "Tid": "*"}
    )
    assert error["code"] == "TOO_LARGE" and error["retryable"] is False
    assert not any(r.url.path.endswith("/data") for r in replay.requests[before:])


async def test_too_large_over_time_suggests_the_latest_period(ctx):
    error = await fails(
        ctx,
        "statistics_get_data",
        table_id="07459",
        select={"Region": "*", "Tid": {"latest": 5}},
        max_rows=1000,
    )
    assert error["next_call"]["arguments"]["select"]["Tid"] == {"latest": 1}


async def test_bad_arguments_are_explained(ctx):
    error = await fails(ctx, "statistics_get_data", table_id="0/../x")
    assert error["code"] == "INVALID_ARGUMENT" and "table_id" in error["message"]


# --- JSON-stat parsing --------------------------------------------------------


def test_status_marks_and_sparse_values():
    ds = {
        "id": ["A", "B"],
        "size": [2, 2],
        "role": {"time": ["B"]},
        "dimension": {
            "A": {
                "label": "a",
                "category": {"index": {"x": 0, "y": 1}, "label": {"x": "X", "y": "Y"}},
            },
            "B": {"label": "b", "category": {"index": ["2020", "2021"]}},
        },
        "value": {"0": 1, "3": 4},
        "status": {"1": ".."},
    }
    dims, rows, truncated = jsonstat.rows(ds, limit=10)
    assert [d.role for d in dims] == ["other", "time"]
    assert [r["value"] for r in rows] == [1, None, None, 4]
    assert rows[1]["status"] == ".." and "status" not in rows[0]
    assert rows[2]["A_label"] == "Y" and rows[2]["B"] == "2020"
    assert truncated is False
    assert jsonstat.rows(ds, limit=3)[2] is True
