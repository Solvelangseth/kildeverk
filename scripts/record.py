"""Record the upstream exchanges the offline tests replay.

    uv run python scripts/record.py ssb_statbank

Runs each scenario against the live upstream and writes every request and
response it caused to tests/fixtures/<source>/cassette.json. Re-run it when a
test needs a request that has not been recorded, then review the diff.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

from kildeverk.context import build_context
from kildeverk.core.cache import ResponseCache
from kildeverk.core.errors import ToolError
from kildeverk.settings import Settings
from kildeverk.sources.registry import operations
from kildeverk.testing import RecordingTransport

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

SCENARIOS: dict[str, list[tuple[str, dict]]] = {
    "ssb_statbank": [
        ("statistics_search_tables", {"query": "population municipality", "limit": 3}),
        ("statistics_search_tables", {"query": "befolkning kommune"}),
        ("statistics_describe_table", {"table_id": "07459"}),
        ("statistics_describe_table", {"table_id": "99999"}),
        (
            "statistics_get_data",
            {"table_id": "07459", "select": {"Region": ["0301", "4601"], "Tid": {"latest": 2}}},
        ),
        (
            "statistics_get_data",
            {
                "table_id": "07459",
                "select": {"Region": ["0"], "ContentsCode": ["Personer1"], "Tid": {"latest": 1}},
            },
        ),
        ("statistics_get_data", {"table_id": "07459", "codelists": {"Region": "agg_Fylker2024"}}),
    ],
}


async def record(source_id: str) -> None:
    transport = RecordingTransport()
    ctx = build_context(
        Settings(),
        client=httpx.AsyncClient(transport=transport, timeout=30),
        cache=ResponseCache(":memory:"),
    )
    ops = {op.name: op for op in operations()}
    for tool, arguments in SCENARIOS[source_id]:
        try:
            await ops[tool].invoke(ctx, arguments)
            outcome = "ok"
        except ToolError as exc:
            outcome = exc.body.code
        print(f"{tool} {json.dumps(arguments)} -> {outcome}")
    await ctx.aclose()

    out = FIXTURES / source_id / "cassette.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(transport.exchanges, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {len(transport.exchanges)} exchanges to {out}")


if __name__ == "__main__":
    asyncio.run(record(sys.argv[1] if len(sys.argv) > 1 else "ssb_statbank"))
