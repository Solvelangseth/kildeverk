"""A token bucket per client address for the public service.

Upstream budgets are shared by everyone using one deployment. Without a per-client
limit, one busy client could spend them all and every other caller would get
RATE_LIMITED errors. Only API and MCP requests count; the website and docs do not.
"""

from __future__ import annotations

import json
import math
import time
from collections import OrderedDict
from collections.abc import Callable

from starlette.types import ASGIApp, Receive, Scope, Send

from kildeverk.core.errors import ErrorCode, ToolError

LIMITED_PREFIXES = ("/v1/", "/mcp")
MAX_CLIENTS = 10_000  # least recently seen addresses are forgotten beyond this


class ClientBuckets:
    def __init__(
        self,
        *,
        per_minute: float,
        burst: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rate = per_minute / 60
        self.burst = burst
        self._clock = clock
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def take(self, client: str) -> float:
        """Spend one token for `client`. Returns 0, or the seconds until one is available."""

        now = self._clock()
        tokens, updated = self._buckets.pop(client, (self.burst, now))
        tokens = min(self.burst, tokens + (now - updated) * self.rate)
        wait = 0.0
        if tokens >= 1:
            tokens -= 1
        else:
            wait = (1 - tokens) / self.rate
        self._buckets[client] = (tokens, now)
        while len(self._buckets) > MAX_CLIENTS:
            self._buckets.popitem(last=False)
        return wait


class ClientLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        per_minute: float,
        burst: float,
        client_ip_header: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.buckets = ClientBuckets(per_minute=per_minute, burst=burst, clock=clock)
        self.header = client_ip_header.lower().encode()

    def _client(self, scope: Scope) -> str:
        if self.header:
            for name, value in scope.get("headers") or []:
                if name == self.header and value:
                    return value.decode("latin-1").split(",")[0].strip()
        client = scope.get("client")
        return client[0] if client else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith(LIMITED_PREFIXES) or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        wait = self.buckets.take(self._client(scope))
        if not wait:
            await self.app(scope, receive, send)
            return
        error = ToolError(
            ErrorCode.RATE_LIMITED,
            "Too many requests from your address to this public service. Wait about "
            f"{math.ceil(wait)} seconds and repeat the same call, or run Kildeverk locally "
            "for a budget of your own.",
            retry_after_s=wait,
        )
        body = json.dumps(error.envelope()).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(max(1, math.ceil(wait))).encode()),
                    (b"access-control-allow-origin", b"*"),
                    (b"access-control-expose-headers", b"Retry-After"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
