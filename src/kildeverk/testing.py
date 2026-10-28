"""Record real upstream exchanges once, then replay them with no network.

A cassette is a JSON list of exchanges. Replay matches on method, URL and body,
and fails loudly on anything it has not seen, so a test can never reach the
network by accident.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

_KEPT_HEADERS = ("content-type", "etag", "last-modified", "expires", "retry-after")


def _key(method: str, url: str, body: bytes) -> str:
    return json.dumps([method, url, body.decode() if body else ""])


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self.exchanges: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        content = await response.aread()
        exchange = {
            "method": request.method,
            "url": str(request.url),
            "body": request.content.decode() if request.content else "",
            "status": response.status_code,
            "headers": {k: v for k, v in response.headers.items() if k.lower() in _KEPT_HEADERS},
            "response": content.decode(),
        }
        if exchange not in self.exchanges:
            self.exchanges.append(exchange)
        # The body is already decoded, so the encoding headers no longer describe it.
        headers = [
            (k, v)
            for k, v in response.headers.multi_items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        ]
        return httpx.Response(
            response.status_code, headers=headers, content=content, request=request
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


class ReplayTransport(httpx.AsyncBaseTransport):
    def __init__(self, *cassettes: Path) -> None:
        self.exchanges: dict[str, dict[str, Any]] = {}
        for path in cassettes:
            for exchange in json.loads(path.read_text()):
                key = _key(exchange["method"], exchange["url"], exchange["body"].encode())
                self.exchanges[key] = exchange
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        exchange = self.exchanges.get(_key(request.method, str(request.url), request.content))
        if exchange is None:
            raise AssertionError(
                f"No recorded exchange for {request.method} {request.url}. "
                "Re-record with scripts/record.py if the request is meant to change."
            )
        return httpx.Response(
            exchange["status"],
            headers=exchange["headers"],
            content=exchange["response"].encode(),
            request=request,
        )
