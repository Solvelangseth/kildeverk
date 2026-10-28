"""Tools about the service itself: what it covers, and how much budget it has left."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Licence, Result
from kildeverk.core.operation import Operation
from kildeverk.sources.registry import SOURCES, operations


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceInfo(BaseModel):
    id: str
    name: str
    publisher: str
    homepage: str
    docs_url: str
    terms_url: str
    licence: Licence
    upstream_limit: str
    this_service_max_per_minute: int
    cache_ttls_s: dict[str, int]
    requires_env: list[str]
    covers: list[str]
    known_gaps: list[str]
    tools: list[str]


class SourcesListOutput(BaseModel):
    sources: list[SourceInfo]


def source_infos() -> list[SourceInfo]:
    ops = operations()
    return [
        SourceInfo(
            id=spec.id,
            name=spec.name,
            publisher=spec.publisher,
            homepage=spec.homepage,
            docs_url=spec.docs_url,
            terms_url=spec.terms_url,
            licence=spec.licence,
            upstream_limit=spec.budget.upstream_limit,
            this_service_max_per_minute=spec.budget.max_per_minute,
            cache_ttls_s=spec.cache_ttls_s,
            requires_env=spec.requires_env,
            covers=spec.covers,
            known_gaps=spec.known_gaps,
            tools=[op.name for op in ops if spec.id in op.source_ids],
        )
        for spec in SOURCES
    ]


async def sources_list(ctx: Context, args: NoInput) -> Result[SourcesListOutput]:
    return Result(data=SourcesListOutput(sources=source_infos()), provenance=[])


class UpstreamStatus(BaseModel):
    source_id: str
    tokens_available: float = Field(
        description="Calls this service can make right now without waiting."
    )
    max_per_minute: int
    upstream_calls_since_start: int
    cache_entries: int
    cache_entries_fresh: int


class ServiceStatusOutput(BaseModel):
    deployment: str
    checked_at: datetime
    upstreams: list[UpstreamStatus]


async def service_status(ctx: Context, args: NoInput) -> Result[ServiceStatusOutput]:
    stats = await ctx.cache.stats()
    upstreams = [
        UpstreamStatus(
            source_id=source_id,
            tokens_available=round(up.bucket.tokens, 2),
            max_per_minute=up.spec.budget.max_per_minute,
            upstream_calls_since_start=up.upstream_calls,
            cache_entries=stats.get(source_id, {}).get("entries", 0),
            cache_entries_fresh=stats.get(source_id, {}).get("fresh", 0),
        )
        for source_id, up in ctx.upstreams.items()
    ]
    return Result(
        data=ServiceStatusOutput(
            deployment=ctx.settings.deployment, checked_at=datetime.now(UTC), upstreams=upstreams
        ),
        provenance=[],
    )


OPERATIONS = (
    Operation(
        name="sources_list",
        title="List data sources",
        description=(
            "List every upstream source this service reads from, with its licence, rate limits, "
            "cache lifetimes, what it covers, its known gaps, and the tools that use it."
        ),
        input_model=NoInput,
        output_model=SourcesListOutput,
        handler=sources_list,
        source_ids=(),
        http_method="GET",
        http_path="/v1/sources",
    ),
    Operation(
        name="service_status",
        title="Service status",
        description=(
            "Show how much request budget is left for each upstream and how full the cache is. "
            "Useful after a RATE_LIMITED error."
        ),
        input_model=NoInput,
        output_model=ServiceStatusOutput,
        handler=service_status,
        source_ids=(),
        http_method="GET",
        http_path="/v1/status",
    ),
)
