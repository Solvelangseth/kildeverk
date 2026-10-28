"""Municipality and county names are accepted wherever a code is, resolved through Klass."""

from __future__ import annotations

import pytest

from kildeverk.core.errors import ToolError
from kildeverk.sources.registry import operations
from kildeverk.sources.ssb_klass.names import resolve_region

OPS = {op.name: op for op in operations()}


async def test_codes_pass_through_without_a_lookup(ctx, replay):
    resolved = await resolve_region(ctx, "4601", "municipality")
    assert resolved.code == "4601" and resolved.provenance == [] and not replay.requests


@pytest.mark.parametrize(
    ("name", "level", "code"),
    [
        ("Bergen", "municipality", "4601"),
        ("bergen", "municipality", "4601"),
        ("Trondheim", "municipality", "5001"),  # official name 'Trondheim - Tråante'
        ("Vestland", "county", "46"),
    ],
)
async def test_current_names(ctx, name, level, code):
    resolved = await resolve_region(ctx, name, level)
    assert resolved.code == code and resolved.note is None
    assert resolved.provenance[0].source_id == "ssb_klass"


async def test_a_former_municipality_is_followed_to_today(ctx):
    resolved = await resolve_region(ctx, "Skoger", "municipality")
    assert resolved.code == "3301" and "today part of 3301 Drammen" in resolved.note


async def test_a_former_municipality_that_was_divided_is_refused(ctx):
    # Hobøl went to Indre Østfold, Vestby and Nordre Follo in 2020.
    with pytest.raises(ToolError) as caught:
        await resolve_region(ctx, "Hobøl", "municipality")
    assert caught.value.body.code == "NOT_FOUND" and "divided" in caught.value.body.message


async def test_a_name_shared_by_two_municipalities_is_ambiguous(ctx):
    with pytest.raises(ToolError) as caught:
        await resolve_region(ctx, "Våler", "municipality")
    error = caught.value.body
    assert error.code == "AMBIGUOUS" and "3114" in error.message and "3419" in error.message


async def test_an_unknown_name_is_not_found(ctx):
    with pytest.raises(ToolError) as caught:
        await resolve_region(ctx, "Nowhereville", "municipality")
    assert caught.value.body.code == "NOT_FOUND"
    assert caught.value.body.next_call.tool == "regions_resolve"


async def test_a_tool_given_a_name_behaves_as_given_the_code(ctx):
    by_code = await OPS["schools_search"].invoke(
        ctx, {"municipality": "4601", "level": "secondary"}
    )
    by_name = await OPS["schools_search"].invoke(
        ctx, {"municipality": "Bergen", "level": "secondary"}
    )
    assert by_name["data"] == by_code["data"]
    assert [p["source_id"] for p in by_name["provenance"]][:2] == ["ssb_klass", "ssb_klass"]
    assert by_name["provenance"][-1] == by_code["provenance"][-1] | {
        "retrieved_at": by_name["provenance"][-1]["retrieved_at"],
        "cache": by_name["provenance"][-1]["cache"],
    }
