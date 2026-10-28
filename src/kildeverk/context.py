"""Everything a tool handler needs at run time, built once per process."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from kildeverk.core.cache import ResponseCache
from kildeverk.core.upstream import Upstream
from kildeverk.settings import Settings
from kildeverk.sources.registry import SOURCES


class HeaderAuth(httpx.Auth):
    """A key sent in a request header, so it never appears in a URL or in provenance."""

    def __init__(self, header: str, value: str) -> None:
        self.header = header
        self.value = value

    def auth_flow(self, request: httpx.Request):
        request.headers[self.header] = self.value
        yield request


@dataclass
class Context:
    settings: Settings
    cache: ResponseCache
    client: httpx.AsyncClient
    upstreams: dict[str, Upstream]
    memo: dict[Any, Any] = field(default_factory=dict)
    """Derived structures worth keeping between calls, keyed by what they were built from."""

    def upstream(self, source_id: str) -> Upstream:
        return self.upstreams[source_id]

    async def aclose(self) -> None:
        await self.client.aclose()
        self.cache.close()


def build_context(
    settings: Settings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    cache: ResponseCache | None = None,
) -> Context:
    settings = settings or Settings()
    client = client or httpx.AsyncClient(timeout=settings.timeout_s, follow_redirects=True)
    cache = cache or ResponseCache(settings.cache_path)
    credentials: dict[str, httpx.Auth] = {}
    if settings.frost_client_id:
        credentials["met_frost"] = httpx.BasicAuth(settings.frost_client_id, "")
    if settings.nve_api_key:
        credentials["nve_hydapi"] = HeaderAuth("X-API-Key", settings.nve_api_key)
    # Entur needs no key, but every request must say which client it comes from.
    for source_id in ("entur_geocoder", "entur_journeyplanner"):
        credentials[source_id] = HeaderAuth("ET-Client-Name", settings.et_client_name)
    upstreams = {
        spec.id: Upstream(
            spec,
            client=client,
            cache=cache,
            user_agent=settings.user_agent,
            max_wait_s=settings.max_wait_s,
            auth=credentials.get(spec.id),
        )
        for spec in SOURCES
    }
    return Context(settings=settings, cache=cache, client=client, upstreams=upstreams)
