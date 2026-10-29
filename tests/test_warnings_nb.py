"""The warning tools in Norwegian, against recordings of fixed past dates."""

from __future__ import annotations

from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def test_met_warnings_in_norwegian(ctx):
    result = await call(
        ctx, "weather_warnings", month="2023-08", county="03", language="nb", limit=3
    )
    warnings = result["data"]["warnings"]
    assert warnings
    assert "lang=no" in result["provenance"][0]["request"]["url"]
    # MET's own Norwegian event names and texts, e.g. 'Mye regn'.
    assert any("regn" in (w["event"] + (w["description"] or "")).lower() for w in warnings)
    assert not any("rain" in w["event"].lower() for w in warnings)


async def test_nve_flood_and_landslide_warnings_in_norwegian(ctx):
    result = await call(
        ctx,
        "hazards_flood_landslide",
        county="03",
        start="2023-08-08",
        end="2023-08-09",
        language="nb",
    )
    assert all("/api/Warning/County/03/1/" in p["request"]["url"] for p in result["provenance"])
    texts = " ".join(w["title"] or "" for w in result["data"]["warnings"])
    assert "farevarsel" in texts.lower() or "fare" in texts.lower()


async def test_nve_avalanche_forecast_in_norwegian(ctx):
    result = await call(
        ctx, "hazards_avalanche", region=3011, start="2026-03-10", end="2026-03-10", language="nb"
    )
    assert "/3011/1/2026-03-10/2026-03-10" in result["provenance"][0]["request"]["url"]
    assert not any("Norwegian" in n for n in result["notes"])
