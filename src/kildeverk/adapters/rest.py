"""Serve every registered operation as a read-only JSON endpoint, with the same handlers."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic.json_schema import models_json_schema
from starlette.exceptions import HTTPException as StarletteHTTPException

from kildeverk import __version__
from kildeverk.core.errors import ErrorCode, ErrorEnvelope, ToolError
from kildeverk.core.operation import Operation
from kildeverk.sources.registry import operations


def error_response(error: ToolError) -> JSONResponse:
    headers = {}
    if error.body.retry_after_s is not None:
        headers["Retry-After"] = str(max(1, round(error.body.retry_after_s)))
    return JSONResponse(error.envelope(), status_code=error.http_status, headers=headers)


def _list_fields(op: Operation) -> set[str]:
    """Input fields that take a list, so a query string may repeat them or separate with commas."""

    def is_array(schema: dict[str, Any]) -> bool:
        return schema.get("type") == "array" or any(is_array(s) for s in schema.get("anyOf", []))

    return {name for name, schema in op.input_schema()["properties"].items() if is_array(schema)}


def _query_arguments(request: Request, list_fields: set[str]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    for name in request.query_params:
        if name in list_fields:
            values = request.query_params.getlist(name)
            arguments[name] = [part for v in values for part in v.split(",") if part]
        else:
            arguments[name] = request.query_params[name]
    return arguments


def _endpoint(op: Operation):
    list_fields = _list_fields(op)

    async def endpoint(request: Request) -> JSONResponse:
        if op.http_method == "GET":
            arguments = _query_arguments(request, list_fields)
        else:
            try:
                arguments = json.loads(await request.body() or b"{}")
            except ValueError:
                arguments = None  # type: ignore[assignment]
            if not isinstance(arguments, dict):
                raise ToolError(
                    ErrorCode.INVALID_ARGUMENT, "The request body must be a JSON object."
                )
        arguments.update(request.path_params)
        return JSONResponse(await op.invoke(request.app.state.ctx, arguments))

    endpoint.__name__ = op.name
    return endpoint


def install(app: FastAPI) -> None:
    for op in operations():
        app.add_api_route(
            op.http_path,
            _endpoint(op),
            methods=[op.http_method],
            include_in_schema=False,
            name=op.name,
        )

    @app.exception_handler(ToolError)
    async def _tool_error(_request: Request, exc: ToolError) -> JSONResponse:
        return error_response(exc)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            error = ToolError(
                ErrorCode.NOT_FOUND,
                "No such endpoint. The list of endpoints is at /openapi.json.",
            )
        else:
            error = ToolError(ErrorCode.INVALID_ARGUMENT, f"HTTP {exc.status_code}: {exc.detail}")
        return JSONResponse(error.envelope(), status_code=exc.status_code)

    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]


def build_openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    ops = operations()
    models = [(op.input_model, "validation") for op in ops]
    models += [(op.result_model, "serialization") for op in ops]
    models.append((ErrorEnvelope, "serialization"))
    keys, definitions = models_json_schema(models, ref_template="#/components/schemas/{model}")

    error_ref = keys[(ErrorEnvelope, "serialization")]
    paths: dict[str, Any] = {}
    for op in ops:
        input_schema = keys[(op.input_model, "validation")]
        resolved = definitions["$defs"][input_schema["$ref"].rsplit("/", 1)[1]]
        operation: dict[str, Any] = {
            "operationId": op.name,
            "summary": op.title,
            "description": op.description + f"\n\nMCP tool: `{op.name}`.",
            "responses": {
                "200": {
                    "description": "Result with provenance",
                    "content": {
                        "application/json": {"schema": keys[(op.result_model, "serialization")]}
                    },
                },
                "default": {
                    "description": "Error",
                    "content": {"application/json": {"schema": error_ref}},
                },
            },
        }
        path_params = {part[1:-1] for part in op.http_path.split("/") if part.startswith("{")}
        if op.http_method == "GET":
            operation["parameters"] = [
                {
                    "name": name,
                    "in": "path" if name in path_params else "query",
                    "required": name in path_params or name in resolved.get("required", []),
                    "schema": prop,
                    "description": prop.get("description", ""),
                }
                for name, prop in resolved.get("properties", {}).items()
            ]
        else:
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": input_schema}},
            }
        paths.setdefault(op.http_path, {})[op.http_method.lower()] = operation

    app.openapi_schema = {
        "openapi": "3.1.0",
        "info": {
            "title": "Kildeverk",
            "version": __version__,
            "description": "Live Norwegian public data with provenance on every result. "
            "The same operations are available as MCP tools at /mcp.",
            "license": {"name": "MIT (code); each source's own licence applies to its data"},
        },
        "paths": paths,
        "components": {"schemas": definitions["$defs"]},
    }
    return app.openapi_schema
