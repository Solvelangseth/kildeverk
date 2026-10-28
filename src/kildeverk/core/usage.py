"""Per-tool counters since the process started, for service_status."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ToolUsage:
    calls: int = 0
    errors: Counter[str] = field(default_factory=Counter)
    cached_parts: int = 0
    """Upstream responses served from the cache, summed over the provenance of results."""
    fresh_parts: int = 0
    total_ms: float = 0.0


@dataclass
class Usage:
    tools: dict[str, ToolUsage] = field(default_factory=dict)

    def record(self, tool: str, *, ms: float, error: str | None, provenance: list[dict]) -> None:
        usage = self.tools.setdefault(tool, ToolUsage())
        usage.calls += 1
        usage.total_ms += ms
        if error:
            usage.errors[error] += 1
        for p in provenance:
            if (p.get("cache") or {}).get("hit"):
                usage.cached_parts += 1
            else:
                usage.fresh_parts += 1
