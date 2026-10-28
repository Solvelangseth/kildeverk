"""Serve every registered operation as an MCP tool."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import mcp_types as types
from mcp.server.lowlevel import Server

from kildeverk import __version__
from kildeverk.context import Context
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.sources.registry import operations

INSTRUCTIONS = """\
Live Norwegian public data. Every successful result has `data`, `provenance` (source, licence, \
exact upstream URL, retrieval time and a citation line to quote) and `notes` worth reading.
Every error has a `code`, a plain `message`, `retryable`, and often a `next_call` you can make as is.
For statistics: statistics_search_tables -> statistics_describe_table -> statistics_get_data.
Call sources_list to see what each source covers and its licence."""

_ANNOTATIONS = types.ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


def _result(payload: dict[str, Any], *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=is_error,
    )


def build_mcp_server(get_context: Callable[[], Context]) -> Server:
    ops = {op.name: op for op in operations()}
    tools = [
        types.Tool(
            name=op.name,
            title=op.title,
            description=op.description,
            input_schema=op.input_schema(),
            output_schema=op.output_schema(),
            annotations=_ANNOTATIONS,
        )
        for op in ops.values()
    ]

    async def on_list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        op = ops.get(params.name)
        if op is None:
            error = ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"There is no tool named '{params.name}'.",
                next_call=NextCall(tool="sources_list", arguments={}),
            )
            return _result(error.envelope(), is_error=True)
        try:
            payload = await op.invoke(get_context(), params.arguments or {})
        except ToolError as exc:
            return _result(exc.envelope(), is_error=True)
        return _result(payload)

    return Server(
        "kildeverk",
        version=__version__,
        title="Kildeverk: Norwegian public data",
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
