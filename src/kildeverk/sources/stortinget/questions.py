"""Questions from members of Stortinget to ministers."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.operation import Operation
from kildeverk.sources.stortinget.ops import _current_session, _date, _get
from kildeverk.sources.stortinget.spec import SPEC

PAGES = "https://www.stortinget.no/no/Saker-og-publikasjoner/Sporsmal"
KINDS = {
    "written": (
        "skriftligesporsmal",
        f"{PAGES}/Skriftlige-sporsmal-og-svar/Skriftlig-sporsmal/?qnid={{id}}",
    ),
    "question_time": (
        "sporretimesporsmal",
        f"{PAGES}/Skriftlige-sporsmal-og-svar/Skriftlig-sporsmal/?qnid={{id}}",
    ),
    "interpellation": ("interpellasjoner", f"{PAGES}/Interpellasjoner/Interpellasjon/?qnid={{id}}"),
}


class QuestionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["written", "question_time", "interpellation"] = Field(
        default="written",
        description="'written' (skriftlige spørsmål), 'question_time' (spørretimen) or "
        "'interpellation'.",
    )
    session: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{4}$", description="e.g. '2025-2026'; default the current."
    )
    query: str | None = Field(
        default=None,
        max_length=100,
        description="Words that must all be in the question; each matches from the start of a "
        "word, so 'strøm' also finds 'strømpris'.",
    )
    minister: str | None = Field(
        default=None,
        max_length=60,
        description="Part of the minister's title, e.g. 'energi' or 'helse', or their name.",
    )
    party: str | None = Field(
        default=None, max_length=10, description="The asker's party, e.g. 'FrP', 'H', 'SV'."
    )
    answered: bool | None = Field(default=None, description="Only answered (true) or unanswered.")
    limit: int = Field(default=20, ge=1, le=100)


class Question(BaseModel):
    id: int
    kind: str
    number: int | None
    asked_on: dt.datetime | None
    asked_by: str | None = Field(description="The member, with party.")
    county: str | None = Field(description="The member's constituency.")
    to_minister: str | None = Field(description="The minister's title, e.g. 'energiministeren'.")
    to_minister_name: str | None
    question: str = Field(description="For written questions, the question in full.")
    answered_on: dt.datetime | None
    answered_by: str | None = Field(description="The title of the minister who answered.")
    url: str = Field(
        description="The question, and the answer once there is one, on stortinget.no."
    )


class QuestionsOutput(BaseModel):
    session: str
    total_matches: int
    questions: list[Question] = Field(description="Newest first.")


def _name(person: dict[str, Any] | None) -> str | None:
    if not person:
        return None
    name = f"{person.get('fornavn', '')} {person.get('etternavn', '')}".strip()
    party = (person.get("parti") or {}).get("id")
    return f"{name} ({party})" if party and name else name or None


async def questions(ctx: Context, args: QuestionsInput) -> Result[QuestionsOutput]:
    up = ctx.upstream(SPEC.id)
    session = args.session or await _current_session(up)
    path, page = KINDS[args.kind]
    fetched = await _get(up, path, "questions", sesjonid=session)
    # Each word matches from the start of a word: 'strøm' finds 'strømpris', 'ulv' not 'skulle'.
    words = [
        re.compile(rf"(?<!\w){re.escape(w)}", re.IGNORECASE) for w in (args.query or "").split()
    ]
    minister = (args.minister or "").casefold()
    rows: list[Question] = []
    for q in fetched.json.get("sporsmal_liste") or []:
        text = q.get("tittel") or ""
        asker = q.get("sporsmal_fra") or {}
        to = q.get("sporsmal_til") or {}
        to_name = f"{to.get('fornavn', '')} {to.get('etternavn', '')}".strip() or None
        to_title = q.get("sporsmal_til_minister_tittel")
        if words and not all(w.search(text) for w in words):
            continue
        if minister and minister not in f"{to_title} {to_name}".casefold():
            continue
        if (
            args.party
            and (asker.get("parti") or {}).get("id", "").casefold() != args.party.casefold()
        ):
            continue
        answered_on = _date(q.get("besvart_dato"))
        if args.answered is not None and (answered_on is not None) != args.answered:
            continue
        rows.append(
            Question(
                id=q["id"],
                kind=args.kind,
                number=q.get("sporsmal_nummer"),
                asked_on=_date(q.get("datert_dato")) or _date(q.get("sendt_dato")),
                asked_by=_name(asker),
                county=(asker.get("fylke") or {}).get("navn"),
                to_minister=to_title,
                to_minister_name=to_name,
                question=" ".join(text.split()),
                answered_on=answered_on,
                answered_by=q.get("besvart_av_minister_tittel"),
                url=page.format(id=q["id"]),
            )
        )
    rows.sort(key=lambda r: r.asked_on or dt.datetime.min.replace(tzinfo=dt.UTC), reverse=True)
    notes = list(fetched.notes)
    if len(rows) > args.limit:
        notes.append(
            f"Showing the newest {args.limit} of {len(rows)}; narrow the search or raise limit."
        )
    if not rows:
        notes.append("No questions match. Try fewer words, another session or another kind.")
    notes.append(
        "Answers are on each question's page; Stortinget's API does not serve answer texts "
        "reliably for current questions."
    )
    return Result(
        data=QuestionsOutput(
            session=session, total_matches=len(rows), questions=rows[: args.limit]
        ),
        provenance=[
            up.provenance(
                fetched, title=f"Stortinget {args.kind.replace('_', ' ')} questions {session}"
            )
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="parliament_questions",
        title="Questions to ministers",
        description=(
            "Questions members of Stortinget have put to ministers in a session (by default the "
            "current one): written questions (in full), questions from question time, or "
            "interpellations, filtered by words in the question, the minister, the asker's party, "
            "and whether it has been answered. Each has the asker, the minister, the dates and a "
            "link to the question and its answer on stortinget.no. Questions are in Norwegian."
        ),
        input_model=QuestionsInput,
        output_model=QuestionsOutput,
        handler=questions,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/parliament/questions",
        examples=(
            {"query": "strøm", "limit": 5},
            {"kind": "interpellation", "session": "2025-2026"},
            {
                "minister": "helse",
                "party": "H",
                "answered": True,
                "session": "2025-2026",
                "limit": 5,
            },
        ),
    ),
)
