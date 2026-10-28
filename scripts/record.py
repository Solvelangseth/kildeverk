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
    # Every region tool reads the same two responses per level, so these cover them all.
    "ssb_klass": [
        ("regions_list", {"level": "municipality"}),
        ("regions_list", {"level": "county"}),
    ],
    "brreg": [
        (
            "companies_get",
            {"org_number": "923609016", "include_subunits": True, "subunits_limit": 3},
        ),
        ("companies_get", {"org_number": "973861883"}),
        ("companies_get", {"org_number": "974760673"}),
        ("companies_get", {"org_number": "999999999"}),
        ("companies_search", {"name": "equinor", "limit": 5}),
        (
            "companies_search",
            {"municipality": ["4601"], "industry": ["62"], "sort": "most_employees", "limit": 5},
        ),
        ("companies_search", {"industry": ["62.010"]}),
    ],
    "met_locationforecast": [
        ("weather_forecast", {"lat": 60.3913, "lon": 5.3221, "hours": 24}),
        ("weather_forecast", {"lat": 95, "lon": 5}),
    ],
    # Needs KILDEVERK_FROST_CLIENT_ID. Requests carry it as basic auth, and recorded
    # exchanges keep no request headers, so it never reaches the fixtures.
    "met_frost": [
        ("weather_find_stations", {"lat": 60.3913, "lon": 5.3221, "limit": 3}),
        ("weather_find_stations", {"name": "Blindern"}),
        ("weather_station_elements", {"station": "SN50540", "element_search": "precipitation"}),
        (
            "weather_observations",
            {
                "station": "SN50540",
                "elements": ["daily_mean_temperature", "daily_precipitation"],
                "start": "2026-10-01",
                "end": "2026-10-08",
            },
        ),
        (
            "weather_observations",
            {
                "station": "SN50540",
                "elements": ["nonsense"],
                "start": "2026-10-01",
                "end": "2026-10-04",
            },
        ),
        (
            "weather_observations",
            {
                "station": "SN50540",
                "elements": ["temperature"],
                "start": "2030-10-01",
                "end": "2030-10-04",
            },
        ),
    ],
}


# Fields removed from recorded responses before they are written. The tools never
# return them, and fixtures end up in a public repository.
SCRUB = {"brreg": {"telefon", "mobil", "epostadresse"}}


def _scrub(value, keys: set[str]):
    if isinstance(value, dict):
        return {k: _scrub(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_scrub(v, keys) for v in value]
    return value


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

    keys = SCRUB.get(source_id)
    if keys:
        for exchange in transport.exchanges:
            try:
                body = json.loads(exchange["response"])
            except ValueError:
                continue
            exchange["response"] = json.dumps(_scrub(body, keys), ensure_ascii=False)

    out = FIXTURES / source_id / "cassette.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(transport.exchanges, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {len(transport.exchanges)} exchanges to {out}")


if __name__ == "__main__":
    asyncio.run(record(sys.argv[1] if len(sys.argv) > 1 else "ssb_statbank"))
