"""The HTTP service: MCP at /mcp and the JSON API at /v1, sharing one context."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route

from kildeverk import __version__
from kildeverk.adapters import rest
from kildeverk.adapters.mcp import build_mcp_server
from kildeverk.context import Context, build_context
from kildeverk.settings import Settings


def create_app(settings: Settings | None = None, *, context: Context | None = None) -> FastAPI:
    settings = settings or Settings()
    holder: dict[str, Context] = {}

    mcp_server = build_mcp_server(lambda: holder["ctx"])
    security = None
    if settings.deployment == "local":
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        )
    sessions = StreamableHTTPSessionManager(
        app=mcp_server, stateless=True, json_response=True, security_settings=security
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = context or build_context(settings)
        holder["ctx"] = ctx
        app.state.ctx = ctx
        async with sessions.run():
            yield
        if context is None:
            await ctx.aclose()

    app = FastAPI(
        title="Kildeverk",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Mcp-Protocol-Version", "Mcp-Session-Id"],
        expose_headers=["Retry-After", "Mcp-Session-Id"],
    )
    app.router.routes.append(
        Route("/mcp", StreamableHTTPASGIApp(sessions), methods=["GET", "POST", "DELETE"])
    )

    @app.get("/", include_in_schema=False)
    async def index() -> dict[str, str]:
        return {
            "name": "kildeverk",
            "version": __version__,
            "mcp": "/mcp",
            "api": "/v1",
            "openapi": "/openapi.json",
            "sources": "/v1/sources",
        }

    rest.install(app)
    return app
