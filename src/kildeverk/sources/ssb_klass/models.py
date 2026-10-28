from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Level = Annotated[
    Literal["municipality", "county"],
    Field(description="'municipality' (kommune) or 'county' (fylke)."),
]
RegionCode = Annotated[
    str,
    Field(
        pattern=r"^\d{2,4}$",
        description="Region code: 4 digits for municipalities, 2 for counties.",
    ),
]


class Region(BaseModel):
    code: str
    name: str


class RegionPeriod(BaseModel):
    code: str
    name: str
    valid_from: dt.date
    valid_to: dt.date | None = Field(
        description="First day it was no longer valid; null if still valid."
    )


# --- regions_list ----------------------------------------------------------------


class ListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Level
    on_date: dt.date | None = Field(default=None, description="Defaults to today.")


class ListOutput(BaseModel):
    level: str
    valid_on: dt.date
    count: int
    regions: list[Region]


# --- regions_resolve -------------------------------------------------------------


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=2,
        max_length=80,
        description="A name or part of one (e.g. 'Tromsø', 'Viken') or a code (e.g. '1902').",
    )
    level: Level | None = Field(default=None, description="Leave out to search both levels.")
    limit: int = Field(default=20, ge=1, le=100)


class Match(BaseModel):
    level: str
    code: str
    name: str
    valid_from: dt.date
    valid_to: dt.date | None
    status: Literal["current", "ended"]
    today: list[Region] = Field(
        description="What this region is part of, or became, under today's borders."
    )
    today_exact: bool = Field(
        description="False if the region was later split, so it maps onto several of today's regions."
    )


class ResolveOutput(BaseModel):
    matches: list[Match]


# --- regions_changes -------------------------------------------------------------


class ChangesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Level
    from_date: dt.date = Field(description="First day to include, e.g. 2019-01-01.")
    to_date: dt.date | None = Field(
        default=None, description="Last day to include; defaults to today."
    )
    code: RegionCode | None = Field(default=None, description="Only changes involving this code.")


class ChangeEvent(BaseModel):
    date: dt.date
    kind: Literal["merge", "split", "renumber", "rename", "renumber_and_rename", "reorganisation"]
    before: list[Region]
    after: list[Region]


class ChangesOutput(BaseModel):
    level: str
    from_date: dt.date
    to_date: dt.date
    events: list[ChangeEvent]


# --- regions_harmonise -----------------------------------------------------------


class SeriesRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: RegionCode
    period: str = Field(
        min_length=4,
        max_length=20,
        pattern=r"^\d{4}",
        description="Starts with a year: '2019', '2019K3', '2019M07'. Only the year is used.",
    )
    value: float | None


class HarmoniseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Level
    target: str = Field(
        pattern=r"^(2020|2024|latest|\d{4}-\d{2}-\d{2})$",
        description="Borders to convert to: '2020' (2020-2023), '2024' (2024 onwards), "
        "'latest' (today), or a date like '2018-01-01'.",
    )
    measure: Literal["additive", "non_additive"] = Field(
        description="'additive' if values can be summed across regions (counts, totals, areas). "
        "'non_additive' for rates, shares, averages and indices: these are only renumbered, "
        "never summed."
    )
    rows: list[SeriesRow] = Field(min_length=1, max_length=20_000)


class HarmonisedRow(BaseModel):
    region: str
    region_name: str
    period: str
    value: float
    method: Literal["unchanged", "renumbered", "summed"]
    sources: list[str] = Field(description="The input region codes this value was made from.")


class CodeMapping(BaseModel):
    code: str
    name: str
    valid: str = Field(description="Years the input code was valid, e.g. '1972-2019' or '2024-'.")
    to: list[Region]
    kind: Literal["unchanged", "renumbered", "merged", "split", "no_successor"]
    exact: bool


class Unconverted(BaseModel):
    region: str | None
    period: str
    reason: str


class HarmoniseOutput(BaseModel):
    level: str
    target_date: dt.date
    measure: str
    rows: list[HarmonisedRow]
    mapping: list[CodeMapping]
    unconverted: list[Unconverted]
    skipped_placeholders: int = Field(
        description="Zero values for codes that did not exist in that period; SSB fills these "
        "in, and they are dropped rather than counted."
    )
    skipped_missing: int = Field(description="Input rows with no value.")
