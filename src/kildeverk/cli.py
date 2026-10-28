"""`kildeverk serve` (stdio by default, or --http), `kildeverk call`, `kildeverk catalogue`,
`kildeverk site`."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from kildeverk.settings import Settings


async def _serve_stdio() -> None:
    from mcp.server.stdio import stdio_server

    from kildeverk.adapters.mcp import build_mcp_server
    from kildeverk.context import build_context

    ctx = build_context(Settings())
    server = build_mcp_server(lambda: ctx)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await ctx.aclose()


def _serve_http(host: str, port: int) -> None:
    import uvicorn

    from kildeverk.app import create_app

    uvicorn.run(create_app(), host=host, port=port, proxy_headers=True, forwarded_allow_ips="*")


async def _call(tool: str, arguments: str) -> int:
    from kildeverk.context import build_context
    from kildeverk.core.errors import ToolError
    from kildeverk.sources.registry import operations

    ops = {op.name: op for op in operations()}
    if tool not in ops:
        print(f"unknown tool {tool!r}; tools: {', '.join(ops)}", file=sys.stderr)
        return 2
    ctx = build_context(Settings())
    try:
        result = await ops[tool].invoke(ctx, json.loads(arguments))
        code = 0
    except ToolError as exc:
        result, code = exc.envelope(), 1
    finally:
        await ctx.aclose()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


def _catalogue() -> None:
    from kildeverk.catalogue import build_catalogue

    print(json.dumps(build_catalogue(), ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kildeverk", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the MCP server (stdio unless --http).")
    serve.add_argument("--http", action="store_true", help="Serve MCP and the JSON API over HTTP.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    call = sub.add_parser("call", help="Run one tool and print its JSON result.")
    call.add_argument("tool")
    call.add_argument("arguments", nargs="?", default="{}", help="JSON object of arguments.")

    sub.add_parser("catalogue", help="Print the source and tool catalogue as JSON.")

    site = sub.add_parser("site", help="Build the static website from the catalogue.")
    site.add_argument("--out", default="site/dist", help="Directory to write it to.")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "serve":
        if args.http:
            _serve_http(args.host, args.port)
        else:
            asyncio.run(_serve_stdio())
        return 0
    if args.command == "call":
        return asyncio.run(_call(args.tool, args.arguments))
    if args.command == "site":
        from pathlib import Path

        from kildeverk.site import build_site

        print(build_site(Path(args.out)))
        return 0
    _catalogue()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
