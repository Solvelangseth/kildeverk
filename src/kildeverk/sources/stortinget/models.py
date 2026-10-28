from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Session = Annotated[str, Field(pattern=r"^\d{4}-\d{4}$", description="e.g. '2025-2026'.")]

STATUS = {
    0: "notified",
    1: "dealt_with",
    2: "under_consideration",
    3: "received",
    4: "lapsed",
    5: "withdrawn",
}
CASE_TYPES = {1: "budget", 2: "general", 3: "law"}
DOCUMENT_GROUPS = {
    0: "unspecified",
    1: "proposition",
    2: "white_paper",
    3: "statement",
    4: "members_proposal",
    5: "constitutional_proposal",
    6: "document_series",
    7: "committee_recommendation",
    8: "report",
}


# --- parliament_cases --------------------------------------------------------------


class CasesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: Session | None = Field(default=None, description="Defaults to the current session.")
    query: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Words that must all appear in the title (Norwegian), e.g. 'strømpris'.",
    )
    type: Literal["budget", "general", "law"] | None = None
    status: Literal["dealt_with", "under_consideration", "withdrawn"] | None = Field(
        default=None, description="'dealt_with' means the committee has dealt with it."
    )
    committee: str | None = Field(
        default=None, min_length=2, max_length=20, description="Committee id, e.g. 'FIN'."
    )
    limit: int = Field(default=20, ge=1, le=100)


class Committee(BaseModel):
    id: str
    name: str


class CaseSummary(BaseModel):
    id: int
    title: str
    short_title: str | None
    type: str
    status: str
    document_group: str
    reference: str | None = Field(description="Document references, e.g. 'Prop. 1 S (2025-2026)'.")
    committee: Committee | None
    session: str | None = Field(description="The session it was dealt with in.")
    updated: dt.datetime | None


class CasesOutput(BaseModel):
    session: str
    total_matches: int
    cases: list[CaseSummary] = Field(description="Most recently updated first.")


# --- parliament_case ---------------------------------------------------------------


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: int = Field(ge=1, description="Case id from parliament_cases.")
    party_breakdown: bool = Field(
        default=True, description="For votes recorded by name, count how each party voted."
    )


class PartyVote(BaseModel):
    party: str
    party_name: str | None
    for_votes: int
    against_votes: int
    absent: int


class Vote(BaseModel):
    id: int
    topic: str | None
    time: dt.datetime | None
    adopted: bool | None
    recorded_by_name: bool
    for_count: int | None = Field(description="Null when the vote was not counted.")
    against_count: int | None
    absent_count: int | None
    result_note: str | None = Field(description="e.g. 'Enstemmig vedtatt' (unanimous).")
    parties: list[PartyVote] = Field(description="Only for votes recorded by name.")


class CaseOutput(BaseModel):
    id: int
    title: str
    short_title: str | None
    type: str
    status: str
    document_group: str
    reference: str | None
    committee: Committee | None
    rapporteurs: list[str] = Field(description="Saksordførere: name (party).")
    topics: list[str]
    decision: str | None = Field(description="Kortvedtak or vedtakstekst, as published.")
    recommendation: str | None
    votes: list[Vote]
    page_url: str


# --- parliament_members ------------------------------------------------------------


class MembersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: Annotated[str, Field(pattern=r"^\d{4}-\d{4}$")] | None = Field(
        default=None,
        description="Electoral period, e.g. '2021-2025'. Leave out for the members sitting today.",
    )
    party: str | None = Field(default=None, max_length=10, description="Party id, e.g. 'A', 'H'.")
    constituency: str | None = Field(
        default=None, max_length=40, description="Constituency (county) name, e.g. 'Hordaland'."
    )


class Member(BaseModel):
    id: str
    name: str
    party: str | None
    party_name: str | None
    constituency: str | None
    committees: list[str] = Field(description="Only given for members sitting today.")
    substitute: bool


class MembersOutput(BaseModel):
    period: str | None
    count: int
    by_party: dict[str, int]
    members: list[Member]
