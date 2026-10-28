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
    assert "provenance" in data_tool.output_schema["properties"]
    assert data_tool.annotations.read_only_hint is True


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
