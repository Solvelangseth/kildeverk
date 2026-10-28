"""The only way any tool reaches the network.

Every upstream call goes through the same steps:
cache → coalesce identical in-flight calls → token bucket → conditional request → httpx.
When upstream fails and an expired copy exists, the copy is served and marked stale.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from kildeverk.core.cache import Entry, ResponseCache
from kildeverk.core.envelope import CacheInfo, Licence, Provenance, UpstreamRequest, citation
from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.core.ratelimit import TokenBucket
from kildeverk.core.source import SourceSpec

log = logging.getLogger(__name__)

DEFAULT_RETRY_AFTER_S = 60.0


@dataclass
class Fetched:
    json: Any
    """The parsed body: JSON values, or the root element for an XML upstream."""
    request: UpstreamRequest
    retrieved_at: datetime
    cache: CacheInfo
    notes: list[str] = field(default_factory=list)


class UpstreamClientError(ToolError):
    """Upstream answered 4xx. Sources catch this to explain it in their own terms."""

    def __init__(self, status: int, detail: str, *, source_id: str) -> None:
        if status in (401, 403):
            code = ErrorCode.NOT_CONFIGURED
            message = (
                f"The upstream service refused this service's credentials ({detail}). "
                "Check the configured client id."
            )
        else:
            code = ErrorCode.NOT_FOUND if status == 404 else ErrorCode.INVALID_ARGUMENT
            message = f"The upstream service rejected the request: {detail}"
        super().__init__(
            code,
            message,
            source_id=source_id,
            upstream_status=status,
        )
        self.status = status
        self.detail = detail


class Upstream:
    def __init__(
        self,
        spec: SourceSpec,
        *,
        client: httpx.AsyncClient,
        cache: ResponseCache,
        user_agent: str,
        max_wait_s: float = 5.0,
        auth: httpx.Auth | None = None,
        clock=time.time,
    ) -> None:
        self.spec = spec
        self.auth = auth
        self.client = client
        self.cache = cache
        self.user_agent = user_agent
        self.max_wait_s = max_wait_s
        self._clock = clock
        self.bucket = TokenBucket(
            rate_per_s=spec.budget.rate_per_s, capacity=spec.budget.capacity, source_id=spec.id
        )
        self._inflight: dict[str, asyncio.Task[Fetched]] = {}
        self.upstream_calls = 0

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        ttl: str,
        key_extra: str = "",
        accept: str = "application/json",
    ) -> Fetched:
        return await self._fetch(
            "GET", url, params=params, body=None, ttl=ttl, key_extra=key_extra, accept=accept
        )

    async def get_xml(
        self, url: str, *, params: dict[str, Any] | None = None, ttl: str, key_extra: str = ""
    ) -> Fetched:
        """For the few upstreams that only speak XML; `json` holds the root element."""

        return await self._fetch(
            "GET",
            url,
            params=params,
            body=None,
            ttl=ttl,
            key_extra=key_extra,
            accept="application/xml",
            fmt="xml",
        )

    async def post_json(
        self,
        url: str,
        *,
        body: Any,
        params: dict[str, Any] | None = None,
        ttl: str,
        key_extra: str = "",
    ) -> Fetched:
        return await self._fetch(
            "POST", url, params=params, body=body, ttl=ttl, key_extra=key_extra, accept=None
        )

    def provenance(
        self, fetched: Fetched, *, title: str, licence: Licence | None = None
    ) -> Provenance:
        """`licence` overrides the spec's when the response itself states a different one."""

        spec = self.spec
        licence = licence or spec.licence
        return Provenance(
            source_id=spec.id,
            source_name=spec.name,
            publisher=spec.publisher,
            title=title,
            licence=licence,
            request=fetched.request,
            retrieved_at=fetched.retrieved_at,
            cache=fetched.cache,
            citation=citation(
                publisher=spec.publisher,
                title=title,
                retrieved_at=fetched.retrieved_at,
                url=fetched.request.url,
                licence=licence,
            ),
        )

    async def _fetch(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        body: Any,
        ttl: str,
        key_extra: str,
        accept: str | None,
        fmt: str = "json",
    ) -> Fetched:
        request = self.client.build_request(
            method,
            url,
            params=params,
            json=body,
            headers={"User-Agent": self.user_agent, "Accept": accept or "application/json"},
        )
        described = UpstreamRequest(method=method, url=str(request.url), body=body)
        key = _cache_key(described, key_extra)

        entry = await self.cache.get(key)
        if entry is not None and entry.fresh(self._clock()):
            return self._from_entry(entry, described, hit=True, fmt=fmt)

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._send(request, described, key, entry, ttl, fmt))
            self._inflight[key] = task
            task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    async def _send(
        self,
        request: httpx.Request,
        described: UpstreamRequest,
        key: str,
        stale: Entry | None,
        ttl: str,
        fmt: str = "json",
    ) -> Fetched:
        try:
            await self.bucket.acquire(max_wait_s=self.max_wait_s)
        except ToolError:
            if stale is not None:
                return self._serve_stale(
                    stale, described, "this service's request budget is used up", fmt
                )
            raise

        if stale is not None:
            if etag := stale.validators.get("etag"):
                request.headers["If-None-Match"] = etag
            if modified := stale.validators.get("last_modified"):
                request.headers["If-Modified-Since"] = modified

        self.upstream_calls += 1
        try:
            response = await self.client.send(request, auth=self.auth or httpx.USE_CLIENT_DEFAULT)
        except httpx.TimeoutException:
            if stale is not None:
                return self._serve_stale(stale, described, "upstream timed out", fmt)
            raise ToolError(
                ErrorCode.UPSTREAM_TIMEOUT,
                f"{self.spec.name} did not answer in time. Retry in a little while.",
                retry_after_s=10,
                source_id=self.spec.id,
            ) from None
        except httpx.TransportError as exc:
            log.warning("transport error from %s: %s", self.spec.id, exc)
            if stale is not None:
                return self._serve_stale(stale, described, "upstream could not be reached", fmt)
            raise ToolError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                f"{self.spec.name} could not be reached. Retry in a little while.",
                retry_after_s=30,
                source_id=self.spec.id,
            ) from None

        status = response.status_code
        if status == 304 and stale is not None:
            entry = await self.cache.put(
                key,
                source_id=self.spec.id,
                body=stale.body,
                validators=stale.validators,
                ttl_s=self._ttl(ttl, response),
            )
            return self._from_entry(entry, described, hit=True, fmt=fmt)

        if status == 429:
            wait = _retry_after(response) or DEFAULT_RETRY_AFTER_S
            self.bucket.block_for(wait)
            if stale is not None:
                return self._serve_stale(stale, described, "upstream rate limit reached", fmt)
            raise ToolError(
                ErrorCode.RATE_LIMITED,
                f"{self.spec.name} is rate limiting requests. Wait {wait:.0f} seconds and repeat "
                "the same call.",
                retry_after_s=wait,
                source_id=self.spec.id,
                upstream_status=429,
            )

        if status >= 500:
            log.warning("%s answered %s for %s", self.spec.id, status, described.url)
            if stale is not None:
                return self._serve_stale(stale, described, f"upstream answered {status}", fmt)
            raise ToolError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                f"{self.spec.name} is having problems (HTTP {status}). Retry in a little while.",
                retry_after_s=30,
                source_id=self.spec.id,
                upstream_status=status,
            )

        if status >= 400:
            if status in (404, 410):
                # Gone upstream means gone here: a publisher that withdraws a record (Brreg
                # answers 410 for legal removals) asks that copies be removed too.
                await self.cache.delete(key)
            raise UpstreamClientError(status, _detail(response), source_id=self.spec.id)

        try:
            _parse(response.content, fmt)
        except (ValueError, ET.ParseError):
            raise ToolError(
                ErrorCode.UPSTREAM_CHANGED,
                f"{self.spec.name} returned something that is not {fmt.upper()}. Its API may "
                "have changed.",
                source_id=self.spec.id,
                upstream_status=status,
            ) from None

        if status == 203:
            # MET's convention: 203 means this API version is deprecated and will be retired.
            log.warning("%s marked %s as deprecated (HTTP 203)", self.spec.id, described.url)

        validators = {}
        if etag := response.headers.get("etag"):
            validators["etag"] = etag
        if modified := response.headers.get("last-modified"):
            validators["last_modified"] = modified
        entry = await self.cache.put(
            key,
            source_id=self.spec.id,
            body=response.content,
            validators=validators,
            ttl_s=self._ttl(ttl, response),
            retrieved_at=self._clock(),
        )
        return self._from_entry(entry, described, hit=False, fmt=fmt)

    def _ttl(self, kind: str, response: httpx.Response) -> float:
        ttl = float(self.spec.cache_ttls_s[kind])
        if self.spec.honour_expires and (expires := response.headers.get("expires")):
            try:
                ttl = max(0.0, parsedate_to_datetime(expires).timestamp() - self._clock())
            except (TypeError, ValueError):
                pass
        return ttl

    def _from_entry(
        self, entry: Entry, described: UpstreamRequest, *, hit: bool, fmt: str = "json"
    ) -> Fetched:
        return Fetched(
            json=_parse(entry.body, fmt),
            request=described,
            retrieved_at=datetime.fromtimestamp(entry.retrieved_at, UTC),
            cache=CacheInfo(hit=hit, age_s=round(max(0.0, self._clock() - entry.retrieved_at), 1)),
        )

    def _serve_stale(
        self, entry: Entry, described: UpstreamRequest, why: str, fmt: str = "json"
    ) -> Fetched:
        fetched = self._from_entry(entry, described, hit=True, fmt=fmt)
        fetched.cache.stale = True
        fetched.notes.append(
            f"Served an expired cached copy from {fetched.retrieved_at:%Y-%m-%d %H:%M} UTC "
            f"because {why}."
        )
        return fetched


def _parse(body: bytes, fmt: str) -> Any:
    # Python's expat refuses external entities and entity expansion attacks by default.
    return ET.fromstring(body) if fmt == "xml" else json.loads(body)


def _cache_key(request: UpstreamRequest, extra: str) -> str:
    raw = json.dumps([request.method, request.url, request.body, extra], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def _detail(response: httpx.Response) -> str:
    """A short human sentence from an upstream error body, never the whole body."""

    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:200] if text else f"HTTP {response.status_code}"
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    if isinstance(body, dict):
        for field_name in ("reason", "detail", "message", "title", "error"):
            value = body.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
    return f"HTTP {response.status_code}"
