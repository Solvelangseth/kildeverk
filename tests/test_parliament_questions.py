"""Questions to ministers, against recordings (a sample of each session's list)."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from kildeverk.sources.registry import operations
from kildeverk.sources.stortinget.questions import QuestionsInput

OPS = {op.name: op for op in operations()}


async def call(ctx, **arguments):
    return await OPS["parliament_questions"].invoke(ctx, arguments)


async def test_written_questions_by_word_newest_first(ctx):
    result = await call(ctx, session="2025-2026", query="strøm", limit=5)
    data = result["data"]
    questions = data["questions"]
    assert data["session"] == "2025-2026" and 0 < len(questions) <= 5
    assert all(re.search(r"(?<!\w)strøm", q["question"], re.IGNORECASE) for q in questions)
    dates = [q["asked_on"] for q in questions]
    assert dates == sorted(dates, reverse=True)
    q = questions[0]
    assert q["kind"] == "written" and q["asked_by"].endswith(")") and q["to_minister"]
    assert q["url"].endswith(f"Skriftlig-sporsmal/?qnid={q['id']}")
    assert any("Answers are on each question's page" in n for n in result["notes"])


async def test_interpellations_link_to_their_own_page(ctx):
    questions = (await call(ctx, kind="interpellation", session="2025-2026", limit=3))["data"][
        "questions"
    ]
    assert len(questions) == 3
    assert all("/Interpellasjoner/Interpellasjon/?qnid=" in q["url"] for q in questions)


async def test_by_minister_party_and_answered(ctx):
    questions = (
        await call(ctx, session="2025-2026", minister="helse", party="H", answered=True, limit=5)
    )["data"]["questions"]
    assert questions
    assert all("helse" in q["to_minister"] and q["asked_by"].endswith("(H)") for q in questions)
    assert all(q["answered_on"] is not None for q in questions)


async def test_question_time(ctx):
    result = await call(ctx, kind="question_time", session="2025-2026", query="barnehage")
    assert all(q["kind"] == "question_time" for q in result["data"]["questions"])


def test_input_rules():
    with pytest.raises(ValidationError):
        QuestionsInput(session="2025")
    with pytest.raises(ValidationError):
        QuestionsInput(kind="oral")
