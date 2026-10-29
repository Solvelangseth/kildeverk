"""The error shape, the token bucket and the upstream gateway, without any real upstream."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel, Field, ValidationError

from kildeverk.core.cache import ResponseCache
from kildeverk.core.envelope import Licence
from kildeverk.core.errors import ErrorCode, ToolError, from_validation_error
from kildeverk.core.ratelimit import TokenBucket
from kildeverk.core.source import Budget, SourceSpec
from kildeverk.core.upstream import Upstream, UpstreamClientError

URL = "https://upstream.test/thing"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def make_spec(**overrides) -> SourceSpec:
    fields = {
        "id": "test",
        "name": "Test upstream",
        "publisher": "Test publisher",
        "homepage": "https://upstream.test",
        "docs_url": "https://upstream.test/docs",
        "terms_url": "https://upstream.test/terms",
        "licence": Licence(
            id="CC-BY-4.0", name="CC BY 4.0", url="https://creativecommons.org/licenses/by/4.0/"
        ),
        "budget": Budget(rate_per_s=1.0, capacity=10, upstream_limit="lots"),
        "cache_ttls_s": {"default": 60},
        "covers": ["things"],
        "known_gaps": [],
    }
    fields.update(overrides)
    return SourceSpec(**fields)


def make_upstream(handler, *, clock=None, **spec_overrides) -> Upstream:
    return Upstream(
        make_spec(**spec_overrides),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        cache=ResponseCache(":memory:"),
        user_agent="kildeverk-test",
        max_wait_s=0.0,
        clock=clock or FakeClock(),
    )


# --- errors -------------------------------------------------------------------


class Strict(BaseModel):
    limit: int = Field(ge=1)
    name: str


def test_validation_errors_become_plain_sentences_without_echoing_input():
    with pytest.raises(ValidationError) as caught:
        Strict.model_validate({"limit": 0, "secret": "x"})
    error = from_validation_error(caught.value, tool="demo")
    body = error.envelope()["error"]
    assert body["code"] == "INVALID_ARGUMENT"
    assert body["retryable"] is False
    assert "limit: Input should be greater than or equal to 1" in body["message"]
    assert "name: Field required" in body["message"]
    assert "pydantic" not in body["message"] and "{" not in body["message"]


def test_retryable_follows_the_code():
    assert ToolError(ErrorCode.RATE_LIMITED, "x").body.retryable is True
    assert ToolError(ErrorCode.UPSTREAM_TIMEOUT, "x").body.retryable is True
    assert ToolError(ErrorCode.NOT_FOUND, "x").body.retryable is False


# --- token bucket ---------------------------------------------------------------


async def test_bucket_refuses_past_its_capacity_and_says_when_to_retry():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_s=0.5, capacity=2, source_id="test", clock=clock)
    await bucket.acquire(max_wait_s=0)
    await bucket.acquire(max_wait_s=0)
    with pytest.raises(ToolError) as caught:
        await bucket.acquire(max_wait_s=0)
    assert caught.value.body.code == ErrorCode.RATE_LIMITED
    assert caught.value.body.retry_after_s == 2.0
    clock.now += 2
    await bucket.acquire(max_wait_s=0)


async def test_bucket_honours_an_upstream_block():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_s=100, capacity=100, source_id="test", clock=clock)
    bucket.block_for(30)
    with pytest.raises(ToolError) as caught:
        await bucket.acquire(max_wait_s=5)
    assert caught.value.body.retry_after_s == 30.0


def test_budget_never_exceeds_ssb_published_limit():
    from kildeverk.sources.ssb_statbank.spec import SPEC

    assert SPEC.budget.max_per_minute <= 30


# --- gateway --------------------------------------------------------------------


async def test_second_identical_call_is_served_from_cache():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"n": 1})

    up = make_upstream(handler)
    first = await up.get_json(URL, params={"a": "1"}, ttl="default")
    second = await up.get_json(URL, params={"a": "1"}, ttl="default")
    assert len(calls) == 1
    assert first.cache.hit is False and second.cache.hit is True
    assert second.request.url == "https://upstream.test/thing?a=1"
    assert calls[0].headers["user-agent"] == "kildeverk-test"


async def test_concurrent_identical_calls_share_one_upstream_request():
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"n": 1})

    up = make_upstream(handler)
    results = await asyncio.gather(*(up.get_json(URL, ttl="default") for _ in range(5)))
    assert len(calls) == 1
    assert all(r.json == {"n": 1} for r in results)


async def test_expired_entry_is_revalidated_with_its_etag():
    clock = FakeClock()
    seen = []

    def handler(request):
        seen.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json={"n": 1}, headers={"ETag": '"v1"'})

    up = make_upstream(handler, clock=clock)
    await up.get_json(URL, ttl="default")
    clock.now += 120
    again = await up.get_json(URL, ttl="default")
    assert seen == [None, '"v1"']
    assert again.json == {"n": 1} and again.cache.age_s == 0.0


async def test_upstream_429_becomes_rate_limited_with_its_retry_after():
    up = make_upstream(lambda r: httpx.Response(429, headers={"Retry-After": "42"}))
    with pytest.raises(ToolError) as caught:
        await up.get_json(URL, ttl="default")
    body = caught.value.body
    assert body.code == ErrorCode.RATE_LIMITED and body.retryable
    assert body.retry_after_s == 42.0 and body.upstream_status == 429


async def test_upstream_failure_serves_an_expired_copy_and_says_so():
    clock = FakeClock()
    state = {"fail": False}

    def handler(request):
        if state["fail"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"n": 1})

    up = make_upstream(handler, clock=clock)
    await up.get_json(URL, ttl="default")
    clock.now += 3600
    state["fail"] = True
    stale = await up.get_json(URL, ttl="default")
    assert stale.cache.stale is True and stale.json == {"n": 1}
    assert "expired cached copy" in stale.notes[0]


async def test_upstream_failure_without_a_copy_is_retryable():
    up = make_upstream(lambda r: httpx.Response(503))
    with pytest.raises(ToolError) as caught:
        await up.get_json(URL, ttl="default")
    assert caught.value.body.code == ErrorCode.UPSTREAM_UNAVAILABLE
    assert caught.value.body.retryable is True


async def test_timeout_is_reported_as_such():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    up = make_upstream(handler)
    with pytest.raises(ToolError) as caught:
        await up.get_json(URL, ttl="default")
    assert caught.value.body.code == ErrorCode.UPSTREAM_TIMEOUT


async def test_non_json_means_the_upstream_changed():
    up = make_upstream(lambda r: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(ToolError) as caught:
        await up.get_json(URL, ttl="default")
    assert caught.value.body.code == ErrorCode.UPSTREAM_CHANGED


async def test_client_errors_carry_a_short_detail_not_the_body():
    body = {"type": "Parameter error", "title": "Missing selection", "status": 400}
    up = make_upstream(lambda r: httpx.Response(400, text=json.dumps(body)))
    with pytest.raises(UpstreamClientError) as caught:
        await up.get_json(URL, ttl="default")
    assert caught.value.detail == "Missing selection"
    assert caught.value.body.code == ErrorCode.INVALID_ARGUMENT


async def test_expires_header_sets_the_lifetime_when_the_source_asks():
    clock = FakeClock()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"n": 1}, headers={"Expires": "Thu, 01 Jan 1970 00:16:50 GMT"}
        )

    # The Expires header above is clock.now + 10 seconds.
    up = make_upstream(handler, clock=clock, honour_expires=True)
    await up.get_json(URL, ttl="default")
    clock.now += 5
    await up.get_json(URL, ttl="default")
    clock.now += 10
    await up.get_json(URL, ttl="default")
    assert len(calls) == 2


async def test_closing_waits_for_a_query_in_flight_and_later_calls_skip_the_cache():
    cache = ResponseCache(":memory:")
    await cache.put("key", source_id="s", body=b"kept", validators={}, ttl_s=60)
    # A read is in its worker thread when the close arrives, as when a test ends while a
    # failed gather's other tasks are still running.
    reading = asyncio.create_task(cache.get("key"))
    await asyncio.sleep(0)
    await cache.aclose()
    assert (await reading).body == b"kept"
    assert await cache.get("key") is None
    entry = await cache.put("later", source_id="s", body=b"x", validators={}, ttl_s=60)
    assert entry.body == b"x"
    await cache.delete("key")
    assert await cache.stats() == {}


async def test_usage_is_counted_per_tool(ctx):
    from kildeverk.core.errors import ToolError
    from kildeverk.sources.registry import operations

    ops = {op.name: op for op in operations()}
    await ops["sources_list"].invoke(ctx, {})
    await ops["sources_list"].invoke(ctx, {})
    with pytest.raises(ToolError):
        await ops["statistics_describe_table"].invoke(ctx, {"table_id": "x"})
    status = await ops["service_status"].invoke(ctx, {})
    tools = {t["tool"]: t for t in status["data"]["tools"]}
    assert tools["sources_list"]["calls"] == 2 and tools["sources_list"]["errors"] == {}
    assert tools["statistics_describe_table"]["errors"] == {"INVALID_ARGUMENT": 1}
