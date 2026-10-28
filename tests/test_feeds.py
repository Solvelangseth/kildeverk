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
