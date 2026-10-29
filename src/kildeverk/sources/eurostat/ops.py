"""Search Eurostat's datasets and read slices of them, for comparing Norway with Europe."""

from __future__ import annotations

import csv
import io
import itertools
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.eurostat.spec import (
    DATA_URL,
    EFTA_AND_CANDIDATES,
    OPEN_GEO_PREFIXES,
    SPEC,
    TOC_URL,
)

NORDICS_AND_EU = ["NO", "SE", "DK", "FI", "IS", "EU27_2020"]
EU27 = {
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "EL",
    "ES",
    "FI",
    "FR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
}
MAX_ROWS = 2000
DATASET = re.compile(r"^[A-Za-z0-9_$]{3,40}$")


# --- eurostat_search ---------------------------------------------------------------


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=100, description="Words in the dataset's title.")
    limit: int = Field(default=10, ge=1, le=30)


class Dataset(BaseModel):
    code: str
    title: str
    updated: str | None
    data_start: str | None
    data_end: str | None


class SearchOutput(BaseModel):
    total_matches: int
    datasets: list[Dataset] = Field(description="Best match first, then the most recent data.")


def _catalogue(text: str) -> list[Dataset]:
    rows = csv.reader(io.StringIO(text), delimiter="\t")
    next(rows, None)
    out = []
    for row in rows:
        if len(row) < 7 or row[2] not in ("table", "dataset"):
            continue
        out.append(
            Dataset(
                code=row[1].strip(),
                title=" ".join(row[0].split()),
                updated=row[3].strip() or None,
                data_start=row[5].strip() or None,
                data_end=row[6].strip() or None,
            )
        )
    return out


async def search(ctx: Context, args: SearchInput) -> Result[SearchOutput]:
    up = ctx.upstream(SPEC.id)
    fetched = await up.get_text(TOC_URL, params={"lang": "en"}, ttl="catalogue")
    datasets = ctx.memo.get(("eurostat_toc", fetched.retrieved_at))
    if datasets is None:
        datasets = {d.code: d for d in _catalogue(fetched.json)}  # tables appear in several folders
        ctx.memo[("eurostat_toc", fetched.retrieved_at)] = datasets
    words = [re.compile(rf"(?<!\w){re.escape(w)}", re.IGNORECASE) for w in args.query.split()]
    # Every word, or failing that most of them: titles word things differently ('unemployment
    # rate' is 'Unemployment by sex and age' in une_rt_a).
    scored = [(sum(bool(w.search(d.title)) for w in words), d) for d in datasets.values()]
    need = len(words) if any(n == len(words) for n, _ in scored) else max(1, len(words) - 1)
    found = [(n, d) for n, d in scored if n >= need]
    # Best match first, then the datasets whose data reach furthest.
    found.sort(key=lambda x: (-x[0], -int((x[1].data_end or "0")[:4] or 0)))
    datasets_found = [d for _, d in found]
    notes = list(fetched.notes)
    if not datasets_found:
        notes.append("No dataset titles match the words. Try fewer or broader words.")
    elif need < len(words):
        notes.append("No title has every word; these have all but one.")
    notes.append("Read a dataset with eurostat_data; its dimensions and codes come back with it.")
    return Result(
        data=SearchOutput(total_matches=len(datasets_found), datasets=datasets_found[: args.limit]),
        provenance=[up.provenance(fetched, title="Eurostat table of contents")],
        notes=notes,
    )


# --- eurostat_data -----------------------------------------------------------------


class DataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(description="A dataset code from eurostat_search, e.g. 'une_rt_a'.")
    geo: list[str] = Field(
        default=NORDICS_AND_EU,
        min_length=1,
        max_length=40,
        description="Country or region codes: 'NO', 'SE', 'EU27_2020', or NUTS regions such as "
        "'NO08'. Eurostat writes Greece as 'EL'. Default: the Nordic countries and the EU.",
    )
    filters: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Codes to keep per dimension, e.g. {'sex': ['T'], 'age': ['Y15-74']}. Leave a "
        "dimension out to get all its values; the result lists each dimension's codes.",
    )
    since: str | None = Field(
        default=None, max_length=10, description="First period, e.g. '2015' or '2020-01'."
    )
    last_periods: int | None = Field(
        default=None, ge=1, le=50, description="Only the last N periods. Default 5 without since."
    )


class Dimension(BaseModel):
    id: str
    label: str
    values: dict[str, str] = Field(description="Code to label, for the values in this result.")


class Row(BaseModel):
    geo: str
    geo_label: str
    period: str
    value: float | None
    flag: str | None = Field(description="Eurostat's flag: p provisional, e estimated, b break …")
    other: dict[str, str] = Field(description="The other dimensions' codes for this value.")


class DataOutput(BaseModel):
    dataset: str
    title: str
    updated: str | None
    dimensions: list[Dimension]
    rows: list[Row] = Field(description="By geo as asked, then period.")
    restricted_geo: list[str] = Field(
        description="Countries outside the EU, EFTA and candidate countries: their data are for "
        "non-commercial use only."
    )


def _codes(category: dict[str, Any]) -> list[str]:
    index = category.get("index") or {}
    if isinstance(index, list):
        return list(index)
    return [code for code, _ in sorted(index.items(), key=lambda item: item[1])]


def _open(geo: str) -> bool:
    return (
        geo in EU27
        or geo in EFTA_AND_CANDIDATES
        or geo.startswith(OPEN_GEO_PREFIXES)
        or (len(geo) > 2 and geo[:2] in EU27 | EFTA_AND_CANDIDATES)
    )


async def data(ctx: Context, args: DataInput) -> Result[DataOutput]:
    if not DATASET.match(args.dataset):
        raise ToolError(ErrorCode.INVALID_ARGUMENT, f"'{args.dataset}' is not a dataset code.")
    geos = list(dict.fromkeys(g.strip().upper() for g in args.geo))
    params: list[tuple[str, Any]] = [("geo", g) for g in geos]
    for dimension, codes in args.filters.items():
        params += [(dimension, c) for c in codes]
    if args.since:
        params.append(("sinceTimePeriod", args.since))
    if args.last_periods or not args.since:
        params.append(("lastTimePeriod", args.last_periods or 5))
    up = ctx.upstream(SPEC.id)
    try:
        fetched = await up.get_json(f"{DATA_URL}/{args.dataset}", params=params, ttl="data")
    except UpstreamClientError as exc:
        found = exc.status == 404
        raise ToolError(
            ErrorCode.NOT_FOUND if found else ErrorCode.INVALID_ARGUMENT,
            f"Eurostat has no dataset '{args.dataset}'; search for one."
            if found
            else f"Eurostat refused the query: {exc.detail}",
            next_call=NextCall(tool="eurostat_search", arguments={"query": args.dataset})
            if found
            else None,
            source_id=SPEC.id,
            upstream_status=exc.status,
        ) from None

    body = fetched.json
    ids: list[str] = body.get("id") or []
    sizes: list[int] = body.get("size") or []
    dims = body.get("dimension") or {}
    codes = {d: _codes(dims[d]["category"]) for d in ids}
    labels = {d: dims[d]["category"].get("label") or {} for d in ids}
    values = body.get("value") or {}
    status = body.get("status") or {}
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values) if v is not None}

    rows: list[Row] = []
    truncated = False
    for flat, position in enumerate(itertools.product(*(range(n) for n in sizes))):
        key = str(flat)
        if key not in values and key not in status:
            continue
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        point = {d: codes[d][i] for d, i in zip(ids, position, strict=True)}
        geo = point.get("geo", "")
        rows.append(
            Row(
                geo=geo,
                geo_label=labels.get("geo", {}).get(geo, geo),
                period=point.get("time", ""),
                value=values.get(key),
                flag=status.get(key) if isinstance(status, dict) else None,
                other={d: c for d, c in point.items() if d not in ("geo", "time", "freq")},
            )
        )
    order = {g: i for i, g in enumerate(geos)}
    rows.sort(key=lambda r: (order.get(r.geo, len(order)), r.period))
    dimensions = [
        Dimension(
            id=d, label=dims[d].get("label") or d, values={c: labels[d].get(c, c) for c in codes[d]}
        )
        for d in ids
        if d not in ("geo", "time")
    ]
    restricted = [g for g in geos if not _open(g)]
    notes = list(fetched.notes)
    if truncated:
        notes.append(f"Cut at {MAX_ROWS} rows; filter more dimensions for the rest.")
    varied = [d.id for d in dimensions if len(d.values) > 1]
    if varied:
        notes.append(
            f"Several values for {', '.join(varied)}; pick codes in filters to keep one series."
        )
    if restricted:
        notes.append(
            f"{', '.join(restricted)} {'is' if len(restricted) == 1 else 'are'} outside the EU, "
            "EFTA and candidate countries; Eurostat allows their data for non-commercial use only."
        )
    if any(r.flag for r in rows):
        notes.append(
            "Flags: p provisional, e estimated, b break in series, u low reliability, : not available."
        )
    return Result(
        data=DataOutput(
            dataset=args.dataset,
            title=body.get("label") or args.dataset,
            updated=body.get("updated"),
            dimensions=dimensions,
            rows=rows,
            restricted_geo=restricted,
        ),
        provenance=[up.provenance(fetched, title=f"Eurostat {args.dataset}: {body.get('label')}")],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="eurostat_search",
        title="Search Eurostat's datasets",
        description=(
            "Find Eurostat datasets by words in their titles: code, title, last update and the "
            "periods covered. Eurostat covers EU and EFTA countries, Norway included, so it "
            "compares Norway with Europe. Read a dataset with eurostat_data."
        ),
        input_model=SearchInput,
        output_model=SearchOutput,
        handler=search,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/eurostat/datasets",
        examples=({"query": "unemployment rate annual"}, {"query": "electricity prices household"}),
    ),
    Operation(
        name="eurostat_data",
        title="Read a Eurostat dataset",
        description=(
            "A slice of a Eurostat dataset as labelled rows: by default the last five periods for "
            "Norway, Sweden, Denmark, Finland, Iceland and the EU. Filter any dimension by its "
            "codes; the result lists every dimension's codes and labels, so a first call shows "
            "how to narrow the next. Values carry Eurostat's flags (provisional, estimated …)."
        ),
        input_model=DataInput,
        output_model=DataOutput,
        handler=data,
        source_ids=(SPEC.id,),
        http_method="POST",
        http_path="/v1/eurostat/data",
        examples=(
            {
                "dataset": "une_rt_a",
                "filters": {"age": ["Y15-74"], "unit": ["PC_ACT"], "sex": ["T"]},
            },
            {
                "dataset": "demo_r_pjangrp3",
                "geo": ["NO08", "NO09"],
                "filters": {"sex": ["T"], "age": ["TOTAL"]},
                "last_periods": 1,
            },
        ),
    ),
)
