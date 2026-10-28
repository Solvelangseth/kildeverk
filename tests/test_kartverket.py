"""Address, place-name and elevation tools against recorded Kartverket responses."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from kildeverk.core.errors import ToolError
from kildeverk.sources.kartverket.models import (
    AddressSearchInput,
    ElevationInput,
    PlaceSearchInput,
)
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


def query_of(result) -> dict[str, list[str]]:
    return parse_qs(urlsplit(result["provenance"][0]["request"]["url"]).query)


async def test_address_by_free_text(ctx):
    result = await call(ctx, "addresses_search", query="Karl Johans gate 22 Oslo")
    [address] = result["data"]["addresses"]
    assert address["text"] == "Karl Johans gate 22" and address["postcode"] == "0026"
    assert address["municipality_code"] == "0301" and address["kind"] == "street"
    assert address["cadastre"] == {"farm": 207, "holding": 100, "leasehold": 0}
    assert 59.9 < address["lat"] < 60 and 10.7 < address["lon"] < 10.8
    [prov] = result["provenance"]
    assert prov["licence"]["id"] == "CC-BY-4.0" and "Kartverket" in prov["licence"]["name"]


async def test_addresses_near_a_point_nearest_first(ctx):
    result = await call(ctx, "addresses_search", lat=59.9139, lon=10.7522, radius_m=50)
    distances = [a["distance_m"] for a in result["data"]["addresses"]]
    assert distances == sorted(distances) and distances[-1] <= 50
    assert result["data"]["total_matches"] == 13 and result["truncated"] is True
    assert "/punktsok" in result["provenance"][0]["request"]["url"]


async def test_addresses_by_postcode(ctx):
    result = await call(ctx, "addresses_search", postcode="0184", limit=3)
    assert {a["postcode"] for a in result["data"]["addresses"]} == {"0184"}
    assert any("46 addresses matched" in n for n in result["notes"])


async def test_fuzzy_address_forgives_a_typo(ctx):
    result = await call(ctx, "addresses_search", query="Munkegata 1 Trondhiem", fuzzy=True, limit=3)
    assert result["data"]["addresses"][0]["municipality"] == "TRONDHEIM"
    assert query_of(result)["fuzzy"] == ["true"]


async def test_no_address_is_an_empty_result_with_a_hint(ctx):
    result = await call(ctx, "addresses_search", query="qqxxzzvv")
    assert result["data"]["addresses"] == [] and "wildcard" in result["notes"][0]


def test_address_search_is_either_text_or_near_a_point():
    with pytest.raises(ValidationError):
        AddressSearchInput()
    with pytest.raises(ValidationError):
        AddressSearchInput(query="Storgata", lat=59.9, lon=10.7)
    with pytest.raises(ValidationError):
        AddressSearchInput(postcode="0184", fuzzy=True)


async def test_place_by_name(ctx):
    result = await call(ctx, "places_search", query="Galdhøpiggen")
    top = result["data"]["places"][0]
    assert top["name"] == "Galdhøpiggen" and top["type"] == "Fjell"
    assert top["municipalities"] == [{"code": "3434", "name": "Lom"}]
    assert any("SSR" in n for n in result["notes"])


async def test_place_lists_every_language(ctx):
    result = await call(ctx, "places_search", query="Kautokeino", limit=3)
    town = result["data"]["places"][0]
    assert town["type"] == "Tettsted" and town["name"] == "Kautokeino"
    assert {"Norsk", "Nordsamisk", "Kvensk"} <= {n["language"] for n in town["names"]}


async def test_place_type_by_display_name_and_county(ctx):
    result = await call(ctx, "places_search", query="Storvatnet", type="Innsjø", county="50")
    assert {p["type"] for p in result["data"]["places"]} == {"Innsjø"}
    assert {c["code"] for p in result["data"]["places"] for c in p["counties"]} == {"50"}
    assert query_of(result)["navneobjekttype"] == ["innsjø"]


async def test_unknown_place_type_suggests_close_matches(ctx):
    with pytest.raises(ToolError) as caught:
        await call(ctx, "places_search", query="Storvatnet", type="Innsjoe")
    error = caught.value.envelope()["error"]
    assert error["code"] == "INVALID_ARGUMENT" and "innsjø" in error["message"]


async def test_places_near_a_point_filtered_by_type(ctx):
    nearby = await call(ctx, "places_search", lat=61.636, lon=8.312, radius_m=1000)
    assert nearby["data"]["places"][0]["name"] == "Galdhøpiggen"
    mountains = await call(ctx, "places_search", lat=61.636, lon=8.312, radius_m=3000, type="Fjell")
    places = mountains["data"]["places"]
    assert {p["type"] for p in places} == {"Fjell"} and len(places) == 10
    assert [p["distance_m"] for p in places] == sorted(p["distance_m"] for p in places)


def test_place_search_needs_a_query_or_a_point():
    with pytest.raises(ValidationError):
        PlaceSearchInput(type="Fjell")
    with pytest.raises(ValidationError):
        PlaceSearchInput(query="x", lat=61.6, lon=8.3)


async def test_elevation_on_land_lake_sea_and_outside(ctx, replay):
    result = await call(
        ctx,
        "terrain_elevation",
        points=[
            {"lat": 61.63644, "lon": 8.31248},
            {"lat": 59.91, "lon": 10.75},
            {"lat": 60.0, "lon": 3.0},
            {"lat": 59.85, "lon": 10.6},
        ],
    )
    peak, oslo, north_sea, fjord = result["data"]["points"]
    assert peak["elevation_m"] == 2468.25 and peak["data_source"] == "terrain model, 1 m"
    assert 0 < oslo["elevation_m"] < 10
    assert north_sea["elevation_m"] is None
    assert fjord["elevation_m"] < 0 and "navigation" in fjord["data_source"]
    assert len(result["notes"]) == 2
    sent = json.loads(parse_qs(urlsplit(str(replay.requests[-1].url)).query)["punkter"][0])
    assert sent[0] == [8.31248, 61.63644]  # (lon, lat), as the API wants


def test_elevation_takes_at_most_50_points():
    with pytest.raises(ValidationError):
        ElevationInput(points=[{"lat": 60, "lon": 10}] * 51)
