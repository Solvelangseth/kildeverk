"""Atom feeds of warnings for a municipality."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from kildeverk.adapters.feeds import ATOM, build_feed
from kildeverk.app import create_app
from kildeverk.settings import Settings
from kildeverk.sources import composite

NS = {"a": ATOM}
NOW = dt.datetime(2026, 10, 28, 12, tzinfo=dt.UTC)
WEATHER = {
    "data": {
        "warnings": [
            {
                "id": "2.49.0.1.578.0.1",
                "level_name": "yellow",
                "event": "Gale",
                "area": "Stoett - Andenes",
                "valid_from": "2026-10-28T12:00:00+00:00",
                "description": "South near gale.",
                "consequences": "Moderate waves.",
                "instruction": None,
                "title": "Gale, yellow level",
                "web": "https://www.met.no/vaer-og-klima/ekstremvaervarsler-og-andre-farevarsler",
            }
        ]
    }
}
HAZARDS = {
    "data": {
        "warnings": [
            {
                "id": "525543",
                "kind": "flood",
                "level_name": "orange",
                "title": "Flood warning orange level",
                "published": "2026-10-28T09:28:30+01:00",
                "valid_from": "2026-10-28T07:00:00+01:00",
                "warning": "Rising water levels.",
                "advice": "Keep away from rivers.",
            }
        ]
    }
}


def _parse(body: bytes) -> ET.Element:
    root = ET.fromstring(body)
    assert root.tag == f"{{{ATOM}}}feed"
    return root


def test_feed_has_an_entry_per_warning():
    root = _parse(build_feed("https://k.test", "4601", "Bergen", WEATHER, HAZARDS, [], NOW))
    titles = [e.findtext("a:title", namespaces=NS) for e in root.findall("a:entry", NS)]
    assert titles == [
        "Yellow warning: Gale (Stoett - Andenes)",
        "Orange flood warning: Flood warning orange level",
    ]
    assert root.findtext("a:id", namespaces=NS) == "https://k.test/v1/feeds/warnings/4601.atom"
    assert root.findtext("a:updated", namespaces=NS) == "2026-10-28T12:00:00+00:00"
    ids = [e.findtext("a:id", namespaces=NS) for e in root.findall("a:entry", NS)]
    assert ids == ["urn:metalerts:2.49.0.1.578.0.1", "urn:varsom:flood:525543"]


def test_a_quiet_day_is_one_entry_saying_so():
    root = _parse(
        build_feed("https://k.test", "4601", "Bergen", {"data": {"warnings": []}}, None, ["x"], NOW)
    )
    [entry] = root.findall("a:entry", NS)
    assert entry.findtext("a:title", namespaces=NS) == "No warnings for Bergen today"


def test_route_resolves_names_and_serves_atom(ctx, monkeypatch):
    async def fake_part(ctx, tool, arguments):
        return {
            "weather_warnings": WEATHER,
            "hazards_flood_landslide": HAZARDS,
            "regions_resolve": {"data": {"matches": [{"name": "Bergen"}]}},
            "hazards_avalanche": {"data": {"forecasts": []}},
        }[tool]

    async def fake_region(ctx, value):
        return "4601", "municipality", None

    monkeypatch.setattr(composite, "_part", fake_part)
    monkeypatch.setattr(composite, "_region_for_series", fake_region)
    with TestClient(create_app(Settings(_env_file=None), context=ctx)) as http:
        response = http.get("/v1/feeds/warnings/Bergen.atom")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/atom+xml")
    assert len(_parse(response.content).findall("a:entry", NS)) == 2


AVALANCHE = [
    {
        "region_id": 3011,
        "region": "Tromsø",
        "date": "2026-03-10",
        "level": 2,
        "level_name": "moderate",
        "summary": "Possible to trigger avalanches in wind slabs.",
        "published": "2026-03-09T15:34:29+01:00",
    }
]


def test_avalanche_forecasts_are_entries_too():
    root = _parse(
        build_feed("https://k.test", "5501", "Tromsø", None, None, [], NOW, avalanche=AVALANCHE)
    )
    [entry] = root.findall("a:entry", NS)
    assert entry.findtext("a:title", namespaces=NS) == "Avalanche danger 2 (moderate): Tromsø"
    assert entry.findtext("a:id", namespaces=NS) == "urn:varsom:avalanche:3011:2026-03-10"


async def test_avalanche_regions_cover_a_municipality(ctx, monkeypatch):
    from kildeverk.adapters import feeds

    async def fake_regions(ctx, municipality):
        return {3011: "Tromsø"} if municipality == "5501" else {}

    async def fake_part(ctx, tool, arguments):
        assert tool == "hazards_avalanche"
        return {
            "data": {
                "forecasts": [
                    {**AVALANCHE[0], "date": "2026-03-10"},
                    {**AVALANCHE[0], "region_id": 3012, "region": "Lyngen", "level": 3},
                    {**AVALANCHE[0], "date": "2026-03-11", "level": 4},
                ]
            }
        }

    monkeypatch.setattr("kildeverk.sources.nve_varsom.ops.avalanche_regions_for", fake_regions)
    monkeypatch.setattr(composite, "_part", fake_part)
    found = await feeds._avalanche(ctx, "5501")
    assert [(f["region_id"], f["date"]) for f in found] == [(3011, "2026-03-10")]
    assert await feeds._avalanche(ctx, "0301") == []
