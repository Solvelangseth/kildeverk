"""The evaluation set stays runnable: valid reference calls, truth for every question, a sane scorer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.questions import QUESTIONS, Question
from eval.score import correct, number
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}
TRUTH = json.loads((Path(__file__).parent.parent / "eval" / "truth.json").read_text())


def test_ids_are_unique_and_every_question_has_truth():
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == len(set(ids)) >= 30
    assert set(ids) == set(TRUTH)


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q.id)
def test_reference_calls_and_expected_tools_exist(q: Question):
    OPS[q.tool].input_model.model_validate(q.arguments)
    assert all(tool in OPS for tool in q.tools)
    assert q.kind in ("number", "text")


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("5 594 340", 5594340),
        ("5,594,340 people", 5594340),
        ("5.594.340", 5594340),
        ("about 11,7456 kroner", 11.7456),
        ("11.7456", 11.7456),
        ("-4.9 °C", -4.9),
        ("It was 68.", 68),
        (2468.25, 2468.25),
    ],
)
def test_numbers_are_read_in_both_conventions(text, value):
    assert number(text) == pytest.approx(value)


def _q(kind: str, tolerance: float = 0.0) -> Question:
    return Question("t", "?", "sources_list", {}, lambda r: r, kind=kind, tolerance=tolerance)


def test_scoring():
    assert correct(_q("number"), "68 members", 68)
    assert not correct(_q("number"), "69", 68)
    assert correct(_q("number", 0.002), "2468", 2468.25)
    assert correct(_q("text"), "The nearest stop is Olav Kyrres gate.", "Olav Kyrres gate")
    assert correct(_q("text"), "Karmøy municipality", "Karmøy")
    assert not correct(_q("text"), "Kristiansund", "Kristiansand")
    assert not correct(_q("text"), "Bergenhus", "Bergen")
