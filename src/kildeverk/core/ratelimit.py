"""A token bucket per upstream, so this service never spends more than its share.

The bucket is sized so that no 60-second window can exceed the upstream's
published limit: capacity plus one minute of refill stays at or under it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from kildeverk.core.errors import ErrorCode, ToolError


class TokenBucket:
    def __init__(
        self,
        *,
        rate_per_s: float,
        capacity: float,
        source_id: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rate = rate_per_s
        self.capacity = capacity
        self.source_id = source_id
        self._clock = clock
        self._tokens = capacity
        self._updated = clock()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    @property
    def tokens(self) -> float:
        self._refill()
        return self._tokens

    def block_for(self, seconds: float) -> None:
        """Honour an upstream's own Retry-After: spend nothing until it passes."""

        self._blocked_until = max(self._blocked_until, self._clock() + seconds)
        self._tokens = 0.0

    def _wait_needed(self) -> float:
        self._refill()
        blocked = max(0.0, self._blocked_until - self._clock())
        if blocked:
            return blocked
        if self._tokens >= 1:
            return 0.0
        return (1 - self._tokens) / self.rate

    async def acquire(self, *, max_wait_s: float) -> None:
        """Take one token, waiting up to `max_wait_s`, else raise RATE_LIMITED."""

        async with self._lock:
            wait = self._wait_needed()
            if wait > max_wait_s:
                raise ToolError(
                    ErrorCode.RATE_LIMITED,
                    f"This service's request budget for {self.source_id} is used up for the moment. "
                    f"Wait about {wait:.0f} seconds and repeat the same call.",
                    retry_after_s=wait,
                    source_id=self.source_id,
                )
            if wait:
                await asyncio.sleep(wait)
                self._refill()
            self._tokens -= 1
