from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.sources.ssb_statbank.spec import MAX_ROWS

Lang = Annotated[
    Literal["en", "no"],
    Field(description="Language of titles and labels. Codes are the same in both."),
]
TableId = Annotated[
    str,
    Field(
        pattern=r"^[0-9A-Za-z]{3,12}$",
        description="SSB table id, e.g. '07459'. Find ids with statistics_search_tables.",
        examples=["07459"],
    ),
]


# --- statistics_search_tables -------------------------------------------------


class SearchTablesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1,
        max_length=200,
        description="Words to look for in table titles, e.g. 'population municipality'.",
    )
    lang: Lang = "en"
    updated_within_days: int | None = Field(
        default=None, ge=1, le=3650, description="Only tables updated in the last N days."
    )
    include_discontinued: bool = Field(
        default=False, description="Also return tables SSB no longer updates."
    )
    limit: int = Field(default=10, ge=1, le=50)
    page: int = Field(default=1, ge=1, le=100)


class TableSummary(BaseModel):
    table_id: str
    title: str
    first_period: str | None
    last_period: str | None
    time_unit: str | None
    updated: datetime | None
    variables: list[str] = Field(description="Names of the table's dimensions.")
    subject_path: list[str] = Field(description="Where the table sits in SSB's subject tree.")


class SearchTablesOutput(BaseModel):
    total_matches: int
    page: int
    total_pages: int
    tables: list[TableSummary]


# --- statistics_describe_table ------------------------------------------------


class DescribeTableInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: TableId
    lang: Lang = "en"
    value_search: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Only list dimension values whose code or label contains this text, "
        "e.g. 'Bergen'. Use it to find the code for a place or category.",
    )
    values_limit: int = Field(
        default=25, ge=0, le=1000, description="Most values to list per dimension."
    )


class DimensionValue(BaseModel):
    code: str
    label: str


class Codelist(BaseModel):
    id: str
    label: str
    kind: str = Field(
        description="'Aggregation' groups values (e.g. counties); 'Valueset' picks a subset."
    )


class Dimension(BaseModel):
    code: str = Field(description="Use this as a key in statistics_get_data's `select`.")
    label: str
    role: Literal["time", "region", "measure", "other"]
    can_omit: bool = Field(
        description="If true and left out of `select`, SSB returns the total over this dimension."
    )
    value_count: int
    values: list[DimensionValue]
    values_listed: Literal["all", "first", "matching"] = Field(
        description="'all' lists every value; 'first' only the first values_limit; "
        "'matching' only those matching value_search."
    )
    codelists: list[Codelist]


class Measure(BaseModel):
    code: str
    label: str
    unit: str | None
    decimals: int | None
    reference_period: str | None = None
    measuring_type: str | None = Field(
        default=None, description="'Stock' (a level at a point in time) or 'Flow' (over a period)."
    )


class DescribeTableOutput(BaseModel):
    table_id: str
    title: str
    updated: datetime | None
    first_period: str | None
    last_period: str | None
    dimensions: list[Dimension]
    measures: list[Measure]
    notes: list[str]
    statistics_page: str | None
    example_arguments: dict[str, Any] = Field(
        description="A small, valid argument set for statistics_get_data on this table."
    )


# --- statistics_get_data ------------------------------------------------------


class Latest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latest: int = Field(ge=1, le=1000, description="The last N values, e.g. the latest 5 years.")


class FromCode(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from", description="This value and every one after it.")


Selection = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=40)]] | Literal["*"] | Latest | FromCode,
    Field(
        description="A list of value codes, '*' for all values, {'latest': N}, or {'from': code}."
    ),
]


class GetDataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: TableId
    select: dict[str, Selection] = Field(
        default_factory=dict,
        description="Values to fetch per dimension code. A time dimension left out gets its "
        "latest value; other dimensions that can be omitted are totalled.",
        examples=[{"Region": ["0301", "4601"], "Tid": {"latest": 3}}],
    )
    codelists: dict[str, str] = Field(
        default_factory=dict,
        description="Optional codelist per dimension, e.g. {'Region': 'agg_Fylker2024'} "
        "to get counties. Codes in `select` then refer to that codelist.",
    )
    lang: Lang = "en"
    max_rows: int = Field(default=1000, ge=1, le=MAX_ROWS)


class Column(BaseModel):
    key: str
    label: str
    role: Literal["time", "region", "measure", "other", "value", "status"]


class GetDataOutput(BaseModel):
    table_id: str
    title: str
    updated: datetime | None
    columns: list[Column]
    rows: list[dict[str, str | int | float | None]] = Field(
        description="One row per cell. Each dimension gives `<code>` and `<code>_label`, then "
        "`value`; `status` appears only where SSB marks a value (e.g. '..' not available)."
    )
    row_count: int
    measures: list[Measure]
