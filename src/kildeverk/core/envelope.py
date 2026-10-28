"""The success shape: the data, and where every part of it came from."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Licence(BaseModel):
    id: str = Field(description="Short identifier, e.g. CC-BY-4.0 or NLOD-2.0.")
    name: str
    url: str


class UpstreamRequest(BaseModel):
    method: str
    url: str = Field(description="The exact request URL sent upstream, query string included.")
    body: Any | None = None


class CacheInfo(BaseModel):
    hit: bool
    age_s: float = Field(description="Seconds since the upstream response was retrieved.")
    stale: bool = Field(
        default=False,
        description="True when upstream failed and an expired cached copy was served instead.",
    )


class Provenance(BaseModel):
    source_id: str
    source_name: str
    publisher: str
    licence: Licence
    request: UpstreamRequest
    retrieved_at: datetime = Field(description="When the upstream response was retrieved, in UTC.")
    cache: CacheInfo
    citation: str = Field(description="Ready-to-paste citation line.")


class Result[T](BaseModel):
    data: T
    provenance: list[Provenance]
    notes: list[str] = Field(default_factory=list)
    truncated: bool = False


def citation(
    *, publisher: str, title: str, retrieved_at: datetime, url: str, licence: Licence
) -> str:
    when = retrieved_at.strftime("%Y-%m-%d %H:%M UTC")
    return f"{publisher}: {title}. Retrieved {when} from {url}. Licence: {licence.name} ({licence.url})."
