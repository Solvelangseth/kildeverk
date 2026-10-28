"""Catalogue search against recorded data.norge.no responses."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from kildeverk.sources.datanorge.models import CatalogSearchInput
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["catalog_search"].invoke(ctx, arguments)


async def test_open_datasets_by_text(ctx, replay):
    result = await call(ctx, query="befolkning", open_data_only=True)
    data = result["data"]
    assert data["total_matches"] > 10 and data["pages"] > 1 and result["truncated"] is True
    entry = data["entries"][0]
    assert entry["kind"] == "dataset" and entry["open_data"] is True
    assert entry["page_url"] == f"https://data.norge.no/datasets/{entry['id']}"
    assert entry["publisher"]["path"].startswith("/")
    sent = json.loads(replay.requests[-1].content)
    assert sent["filters"] == {"openData": {"value": True}}
    [prov] = result["provenance"]
    assert prov["licence"]["id"] == "not-stated" and prov["request"]["body"] == sent
    assert any("page=1" in n for n in result["notes"])


async def test_publisher_path_from_a_result_narrows_the_search(ctx):
    result = await call(ctx, query="befolkning", publisher="/STAT/972417807/971526920", limit=3)
    publishers = {e["publisher"]["org_number"] for e in result["data"]["entries"]}
    assert publishers == {"971526920"}


async def test_data_services(ctx, replay):
    result = await call(ctx, query="vær", kind="data_services")
    assert {e["kind"] for e in result["data"]["entries"]} == {"data_service"}
    assert all("/data-services/" in e["page_url"] for e in result["data"]["entries"])
    assert replay.requests[-1].url.path.endswith("/search/data-services")


async def test_filters_only_sort_newest_first(ctx, replay):
    result = await call(ctx, themes=["TRAN"], formats=["CSV"], limit=5)
    entries = result["data"]["entries"]
    assert all("TRAN" in e["themes"] and "CSV" in e["formats"] for e in entries)
    sent = json.loads(replay.requests[-1].content)
    assert sent["filters"]["formats"] == {"value": ["FILE_TYPE CSV"]}
    assert sent["sort"] == {"field": "FIRST_HARVESTED", "direction": "DESC"}
    assert any("TRAN = Transport" in n for n in result["notes"])


async def test_nothing_found_suggests_what_to_try(ctx):
    result = await call(ctx, query="qqxxzzvvyy")
    assert result["data"]["entries"] == [] and "Norwegian words" in result["notes"][0]


def test_search_needs_a_query_or_a_filter():
    with pytest.raises(ValidationError):
        CatalogSearchInput()
    with pytest.raises(ValidationError):
        CatalogSearchInput(publisher="Statistisk sentralbyrå")
    CatalogSearchInput(publisher="/KOMMUNE")
