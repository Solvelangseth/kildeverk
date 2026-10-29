"""MCP and REST serve the same operations with the same results and errors."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from kildeverk.adapters.mcp import build_mcp_server
from kildeverk.app import create_app
from kildeverk.settings import Settings
from kildeverk.sources.registry import operations

TOOL_NAMES = {op.name for op in operations()}


# --- MCP ----------------------------------------------------------------------


async def test_mcp_lists_every_tool_with_schemas(ctx):
    async with Client(build_mcp_server(lambda: ctx)) as client:
        listed = await client.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert set(tools) == TOOL_NAMES
    data_tool = tools["statistics_get_data"]
    assert data_tool.input_schema["properties"]["table_id"]["pattern"]
    assert data_tool.output_schema is None
    assert data_tool.annotations.read_only_hint is True


async def test_the_tool_list_stays_small_enough_to_load(ctx):
    # Clients load every tool definition before the first question. Output schemas once made
    # this list 109,000 tokens; at about four characters a token, this keeps it under 30,000.
    async with Client(build_mcp_server(lambda: ctx)) as client:
        listed = await client.list_tools()
    size = len(
        json.dumps([t.model_dump(exclude_none=True) for t in listed.tools], ensure_ascii=False)
    )
    assert size < 120_000, f"the tool list is about {size // 4:,} tokens"


async def test_mcp_call_returns_structured_result(ctx):
    async with Client(build_mcp_server(lambda: ctx)) as client:
        result = await client.call_tool(
            "statistics_get_data",
            {"table_id": "07459", "select": {"Region": ["0301", "4601"], "Tid": {"latest": 2}}},
        )
    assert result.is_error is False
    assert result.structured_content["data"]["row_count"] == 4
    assert json.loads(result.content[0].text) == result.structured_content


async def test_mcp_errors_are_tool_results_with_the_error_shape(ctx):
    async with Client(build_mcp_server(lambda: ctx)) as client:
        result = await client.call_tool("statistics_describe_table", {"table_id": "99999"})
        unknown = await client.call_tool("no_such_tool", {})
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "NOT_FOUND"
    assert unknown.structured_content["error"]["next_call"]["tool"] == "sources_list"


# --- REST ---------------------------------------------------------------------


@pytest.fixture
def http(ctx):
    app = create_app(Settings(_env_file=None), context=ctx)
    with TestClient(app) as client:
        yield client


def test_rest_get_with_query_parameters(http):
    response = http.get(
        "/v1/statistics/tables", params={"query": "population municipality", "limit": 3}
    )
    assert response.status_code == 200
    assert len(response.json()["data"]["tables"]) == 3


@pytest.mark.parametrize(
    "params",
    [
        [("municipality", "4601"), ("stop_types", "railStation")],
        [("municipality", "4601"), ("stop_types", "railStation,")],
    ],
)
def test_rest_list_parameters_repeat_or_use_commas(http, params):
    response = http.get("/v1/transit/stops", params=params)
    assert response.status_code == 200
    assert all("railStation" in s["stop_types"] for s in response.json()["data"]["stops"])


def test_rest_repeated_list_parameter_keeps_every_value(http):
    response = http.get(
        "/v1/transit/departures",
        params=[("stop", "NSR:StopPlace:59872"), ("modes", "rail"), ("within_minutes", "60")],
    )
    assert response.status_code == 200
    assert {d["mode"] for d in response.json()["data"]["departures"]} == {"rail"}


def test_rest_path_parameter(http):
    response = http.get("/v1/statistics/tables/07459", params={"value_search": "bergen"})
    assert response.status_code == 200
    assert response.json()["data"]["table_id"] == "07459"


def test_rest_post_body(http):
    response = http.post(
        "/v1/statistics/data",
        json={"table_id": "07459", "select": {"Region": ["0301", "4601"], "Tid": {"latest": 2}}},
    )
    assert response.status_code == 200 and response.json()["data"]["row_count"] == 4


def test_rest_errors_use_the_same_shape_and_http_status(http):
    missing = http.get("/v1/statistics/tables/99999")
    assert missing.status_code == 404
    assert missing.json()["error"]["next_call"]["tool"] == "statistics_search_tables"

    invalid = http.get("/v1/statistics/tables", params={"limit": "lots"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_ARGUMENT"

    not_json = http.post("/v1/statistics/data", content=b"nope")
    assert not_json.status_code == 400

    nowhere = http.get("/v2/whatever")
    assert nowhere.status_code == 404 and nowhere.json()["error"]["code"] == "NOT_FOUND"


def test_openapi_documents_every_operation(http):
    spec = http.get("/openapi.json").json()
    operation_ids = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert operation_ids == TOOL_NAMES
    import re

    refs = set(re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(spec)))
    assert refs and refs <= set(spec["components"]["schemas"])


def test_mcp_over_http(http):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = http.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "kildeverk"
    listed = http.post(
        "/mcp",
        headers={**headers, "Mcp-Protocol-Version": "2025-06-18"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert listed.status_code == 200, listed.text
    assert {t["name"] for t in listed.json()["result"]["tools"]} == TOOL_NAMES


async def test_mcp_resources_describe_every_source(ctx):
    from kildeverk.sources.registry import SOURCES

    async with Client(build_mcp_server(lambda: ctx)) as client:
        listed = await client.list_resources()
        uris = {str(r.uri) for r in listed.resources}
        assert {"kildeverk://guide", "kildeverk://sources"} <= uris
        assert {f"kildeverk://sources/{s.id}" for s in SOURCES} <= uris
        guide = await client.read_resource("kildeverk://guide")
        assert "place_overview" in guide.contents[0].text
        one = await client.read_resource("kildeverk://sources/brreg")
        assert json.loads(one.contents[0].text)["licence"]["id"] == "NLOD-2.0"


async def test_mcp_prompts_fill_their_arguments(ctx):
    async with Client(build_mcp_server(lambda: ctx)) as client:
        names = {p.name for p in (await client.list_prompts()).prompts}
        assert {
            "profile_place",
            "profile_municipality",
            "find_statistic",
            "compare_places",
        } <= names
        prompt = await client.get_prompt(
            "find_statistic", {"topic": "house prices", "region": "Oslo"}
        )
        text = prompt.messages[0].content.text
        assert "'house prices' for Oslo" in text and "statistics_search_tables" in text
        bare = await client.get_prompt("find_statistic", {"topic": "unemployment"})
        assert "'unemployment'. Search" in bare.messages[0].content.text


def test_openapi_carries_each_tools_examples(http):
    spec = http.get("/openapi.json").json()
    get = spec["paths"]["/v1/statistics/tables"]["get"]
    query = {p["name"]: p for p in get["parameters"]}
    assert query["query"]["example"] == "population municipality"
    post = spec["paths"]["/v1/statistics/series"]["post"]
    examples = post["requestBody"]["content"]["application/json"]["examples"]
    assert examples["example_1"]["value"]["region"] == "Tromsø"


async def test_website_recipes_are_mcp_prompts(ctx):
    async with Client(build_mcp_server(lambda: ctx)) as client:
        names = {p.name for p in (await client.list_prompts()).prompts}
        assert {"recipe_place_overview", "recipe_statistics_rank"} <= names
        prompt = await client.get_prompt("recipe_statistics_rank", {})
        text = prompt.messages[0].content.text
        assert text.startswith("Which municipalities have grown fastest") and '"07459"' in text
