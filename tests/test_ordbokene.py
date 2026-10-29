"""Ordbøkene dictionary lookups, against recordings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kildeverk.sources.ordbokene.ops import LookupInput, _render
from kildeverk.sources.ordbokene.spec import CREDIT
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["dictionary_lookup"].invoke(ctx, arguments)


async def test_a_word_in_both_dictionaries(ctx):
    result = await call(ctx, word="fjord")
    data = result["data"]
    assert data["total_matches"] == {"bokmål": 1, "nynorsk": 1}
    bm, nn = data["articles"]
    assert (bm["dictionary"], nn["dictionary"]) == ("bokmål", "nynorsk")
    assert (bm["word_class"], bm["gender"]) == ("noun", "masculine")
    assert [f["form"] for f in bm["forms"]] == ["fjord", "fjorden", "fjorder", "fjordene"]
    assert [f["form"] for f in nn["forms"]][2:] == ["fjordar", "fjordane"]
    assert bm["meanings"][0]["text"].startswith("smal innskjæring av havet")
    # Placeholders and abbreviations are filled in.
    assert "$" not in bm["origin"] and "norrønt" in bm["origin"]
    assert all("$" not in m["text"] for a in data["articles"] for m in a["meanings"])
    assert bm["url"] == "https://ordbokene.no/bm/15101"
    assert data["credit"] == CREDIT and any(CREDIT in n for n in result["notes"])


async def test_a_verb_in_nynorsk(ctx):
    article = (await call(ctx, word="springe", dictionary="nn", limit=1))["data"]["articles"][0]
    assert article["word_class"] == "verb" and article["gender"] is None
    assert {"springe", "sprang", "sprunge"} <= {f["form"] for f in article["forms"]}


async def test_a_misspelling_gets_suggestions(ctx):
    data = (await call(ctx, word="fjrod"))["data"]
    assert data["articles"] == [] and data["did_you_mean"]
    assert "fjrod" not in data["did_you_mean"]


async def test_a_wildcard_says_how_many_more(ctx):
    result = await call(ctx, word="spring*", dictionary="bm", limit=2)
    assert len(result["data"]["articles"]) == 2 and result["data"]["total_matches"]["bokmål"] > 2
    assert any("showing 2 of" in n for n in result["notes"])


def test_render_fills_placeholders_in_order():
    concepts = {"norr.": {"expansion": "norrønt"}}
    block = {
        "content": "$ $ fra $",
        "items": [
            {"type_": "language", "id": "norr."},
            {"type_": "usage", "text": "fjǫrdr"},
            {"type_": "article_ref", "lemmas": [{"lemma": "fare"}]},
        ],
    }
    assert _render(block, concepts) == "norrønt fjǫrdr fra fare"


def test_input_rules():
    with pytest.raises(ValidationError):
        LookupInput(word="", dictionary="bm")
    with pytest.raises(ValidationError):
        LookupInput(word="ord", dictionary="sv")
