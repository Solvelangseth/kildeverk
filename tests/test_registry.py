"""Invariants every source and tool must keep, so adding one cannot quietly skip a step."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kildeverk.catalogue import build_catalogue
from kildeverk.sources.registry import SOURCES, operations

ROOT = Path(__file__).parent.parent
OPS = operations()
SOURCE_IDS = {spec.id for spec in SOURCES}


def test_tool_names_are_unique_snake_case():
    names = [op.name for op in OPS]
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[a-z]+(_[a-z]+)+", name) for name in names)


def test_http_routes_are_unique():
    routes = [(op.http_method, op.http_path) for op in OPS]
    assert len(routes) == len(set(routes))


@pytest.mark.parametrize("op", OPS, ids=lambda op: op.name)
def test_every_tool_names_known_sources_and_has_valid_examples(op):
    assert set(op.source_ids) <= SOURCE_IDS
    assert len(op.description) > 80
    if op.source_ids:
        assert op.examples, "a data tool needs at least one example"
    for example in op.examples:
        op.input_model.model_validate(example)


@pytest.mark.parametrize("spec", SOURCES, ids=lambda spec: spec.id)
def test_every_source_is_documented(spec):
    assert spec.licence.url.startswith("https://")
    assert spec.terms_url.startswith("https://")
    assert spec.covers and spec.known_gaps
    assert any(spec.id in op.source_ids for op in OPS)
    readme = (ROOT / "README.md").read_text()
    assert f'<a id="{spec.id}"></a>' in readme, f"README needs a section for {spec.id}"
    assert (ROOT / "tests" / "fixtures" / spec.id / "cassette.json").exists()


def test_catalogue_builds():
    catalogue = build_catalogue()
    assert {s["id"] for s in catalogue["sources"]} == SOURCE_IDS
    assert {t["name"] for t in catalogue["tools"]} == {op.name for op in OPS}
