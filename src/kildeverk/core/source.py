"""What the service knows about each upstream, in one place.

The website's source catalogue, `sources_list`, the README tables and the rate
limiters are all read from these specs, so they cannot disagree with each other.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from kildeverk.core.envelope import Licence


class Budget(BaseModel):
    """This service's own token bucket for one upstream."""

    rate_per_s: float
    capacity: float
    upstream_limit: str = Field(description="The upstream's published limit, in its own terms.")

    @property
    def max_per_minute(self) -> int:
        return int(self.capacity + 60 * self.rate_per_s)


class SourceSpec(BaseModel):
    id: str
    name: str
    publisher: str
    homepage: str
    docs_url: str
    terms_url: str = Field(description="Where the licence for this upstream was read.")
    licence: Licence
    budget: Budget
    cache_ttls_s: dict[str, int] = Field(description="Cache lifetime per kind of request.")
    honour_expires: bool = Field(
        default=False, description="Use the upstream's Expires header as the cache lifetime."
    )
    requires_env: list[str] = Field(
        default_factory=list, description="Environment variables the source needs, if any."
    )
    covers: list[str]
    known_gaps: list[str]
