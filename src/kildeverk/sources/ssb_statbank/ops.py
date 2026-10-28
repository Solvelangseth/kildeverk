"""Statistics tools backed by SSB's PxWebApi v2."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import Fetched, Upstream, UpstreamClientError
from kildeverk.sources.ssb_statbank import jsonstat
from kildeverk.sources.ssb_statbank.models import (
    Codelist,
    Column,
    DescribeTableInput,
    DescribeTableOutput,
    Dimension,
    DimensionValue,
    FromCode,
    GetDataInput,
    GetDataOutput,
    Latest,
    Measure,
    SearchTablesInput,
    SearchTablesOutput,
    TableSummary,
)
from kildeverk.sources.ssb_statbank.spec import BASE_URL, MAX_ROWS, SPEC

# Above this length a data request is sent as POST, because long selections
# would otherwise produce URLs that proxies truncate.
MAX_GET_QUERY = 1800


def _upstream(ctx: Context) -> Upstream:
    return ctx.upstream(SPEC.id)


def _title(value: Any, fallback: str) -> str:
    # SSB titles sometimes carry doubled spaces; citations should not.
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else fallback


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# --- statistics_search_tables -------------------------------------------------


async def search_tables(ctx: Context, args: SearchTablesInput) -> Result[SearchTablesOutput]:
    up = _upstream(ctx)
    params: dict[str, Any] = {
        "query": args.query,
        "lang": args.lang,
        "pageSize": args.limit,
        "pageNumber": args.page,
    }
    if args.updated_within_days:
        params["pastDays"] = args.updated_within_days
    if args.include_discontinued:
        params["includeDiscontinued"] = "true"
    fetched = await up.get_json(f"{BASE_URL}/tables", params=params, ttl="search")

    body = fetched.json
    tables = [
        TableSummary(
            table_id=item["id"],
            title=_title(item.get("label"), item["id"]),
            first_period=item.get("firstPeriod"),
            last_period=item.get("lastPeriod"),
            time_unit=item.get("timeUnit"),
            updated=_parse_time(item.get("updated")),
            variables=item.get("variableNames") or [],
            subject_path=[step["label"] for step in ((item.get("paths") or [[]])[0])],
        )
        for item in body.get("tables") or []
    ]
    page = body.get("page") or {}
    notes = list(fetched.notes)
    if not tables and args.lang == "en":
        notes.append(
            "Nothing matched. English search only sees English titles; try lang='no' with "
            "Norwegian words (e.g. 'befolkning' for population), or fewer words."
        )
    return Result(
        data=SearchTablesOutput(
            total_matches=page.get("totalElements", len(tables)),
            page=page.get("pageNumber", args.page),
            total_pages=page.get("totalPages", 1),
            tables=tables,
        ),
        provenance=[up.provenance(fetched, title=f'Statbank table search for "{args.query}"')],
        notes=notes,
    )


# --- statistics_describe_table ------------------------------------------------


async def _metadata(up: Upstream, table_id: str, lang: str) -> Fetched:
    try:
        return await up.get_json(
            f"{BASE_URL}/tables/{table_id}/metadata", params={"lang": lang}, ttl="metadata"
        )
    except UpstreamClientError as exc:
        if exc.status != 404:
            raise
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"SSB has no table '{table_id}'. Table ids are five characters, usually digits; "
            "search for the right one first.",
            next_call=NextCall(tool="statistics_search_tables", arguments={"query": table_id}),
            source_id=SPEC.id,
            upstream_status=404,
        ) from None


def _measures(dims: list[jsonstat.Dim]) -> list[Measure]:
    measures = []
    for dim in dims:
        if dim.role != "measure":
            continue
        refperiods = dim.extension.get("refperiod") or {}
        kinds = dim.extension.get("measuringType") or {}
        for code in dim.codes:
            unit = dim.units.get(code) or {}
            measures.append(
                Measure(
                    code=code,
                    label=dim.labels.get(code, code),
                    unit=unit.get("base"),
                    decimals=unit.get("decimals"),
                    reference_period=refperiods.get(code),
                    measuring_type=kinds.get(code),
                )
            )
    return measures


def _can_omit(dim: jsonstat.Dim) -> bool:
    return bool(dim.extension.get("elimination", False))


def _example_arguments(table_id: str, dims: list[jsonstat.Dim]) -> dict[str, Any]:
    select: dict[str, Any] = {}
    for dim in dims:
        if dim.role == "time":
            select[dim.code] = {"latest": 1}
        elif dim.role in ("measure", "region") or not _can_omit(dim):
            select[dim.code] = dim.codes[:1]
    return {"table_id": table_id, "select": select}


async def describe_table(ctx: Context, args: DescribeTableInput) -> Result[DescribeTableOutput]:
    up = _upstream(ctx)
    fetched = await _metadata(up, args.table_id, args.lang)
    ds = fetched.json
    dims = jsonstat.dimensions(ds)

    described = []
    needle = args.value_search.casefold() if args.value_search else None
    for dim in dims:
        values = [DimensionValue(code=code, label=dim.labels.get(code, code)) for code in dim.codes]
        if needle is not None:
            values = [
                v for v in values if needle in v.code.casefold() or needle in v.label.casefold()
            ]
            listed = "matching"
        elif len(values) <= args.values_limit:
            listed = "all"
        else:
            listed = "first"
        described.append(
            Dimension(
                code=dim.code,
                label=dim.label,
                role=dim.role,  # type: ignore[arg-type]
                can_omit=_can_omit(dim),
                value_count=len(dim.codes),
                values=values[: args.values_limit],
                values_listed=listed,  # type: ignore[arg-type]
                codelists=[
                    Codelist(id=c["id"], label=c.get("label", c["id"]), kind=c.get("type", ""))
                    for c in dim.extension.get("codelists") or []
                ],
            )
        )

    time_dim = next((d for d in dims if d.role == "time"), None)
    related = ((ds.get("link") or {}).get("related")) or []
    homepage = next(
        (
            link.get("href")
            for link in related
            if (link.get("extension") or {}).get("relation") == "statistics-homepage"
        ),
        None,
    )
    notes = list(fetched.notes)
    if needle is not None and not any(d.values for d in described):
        notes.append(f"No dimension value matched '{args.value_search}'.")
    title = _title(ds.get("label"), args.table_id)
    return Result(
        data=DescribeTableOutput(
            table_id=args.table_id,
            title=title,
            updated=_parse_time(ds.get("updated")),
            first_period=time_dim.codes[0] if time_dim and time_dim.codes else None,
            last_period=time_dim.codes[-1] if time_dim and time_dim.codes else None,
            dimensions=described,
            measures=_measures(dims),
            notes=[n for n in ds.get("note") or [] if isinstance(n, str)],
            statistics_page=homepage,
            example_arguments=_example_arguments(args.table_id, dims),
        ),
        provenance=[up.provenance(fetched, title=f"Statbank table {title} (metadata)")],
        notes=notes,
    )


# --- statistics_get_data ------------------------------------------------------


def _describe_call(args: GetDataInput, value_search: str | None = None) -> NextCall:
    arguments: dict[str, Any] = {"table_id": args.table_id}
    if value_search:
        arguments["value_search"] = value_search
    return NextCall(tool="statistics_describe_table", arguments=arguments)


def _invalid(message: str, args: GetDataInput, value_search: str | None = None) -> ToolError:
    return ToolError(
        ErrorCode.INVALID_ARGUMENT,
        message,
        next_call=_describe_call(args, value_search),
        source_id=SPEC.id,
    )


def _resolve(
    dim: jsonstat.Dim, selection: Any, codes: list[str], *, check: bool, args: GetDataInput
) -> tuple[int, str]:
    """How many values a selection picks, and how SSB spells it."""

    if selection == "*":
        return len(codes), "*"
    if isinstance(selection, Latest):
        return min(selection.latest, len(codes)), f"top({selection.latest})"
    if isinstance(selection, FromCode):
        start = selection.from_
        if start in codes:
            return len(codes) - codes.index(start), f"from({start})"
        if check:
            raise _invalid(
                f"Dimension {dim.code} has no value '{start}' to start from. "
                f"Its values run from '{codes[0]}' to '{codes[-1]}'.",
                args,
            )
        return len(codes), f"from({start})"
    wanted = list(dict.fromkeys(selection))
    if check:
        known = set(codes)
        unknown = [code for code in wanted if code not in known]
        if unknown:
            shown = ", ".join(f"'{code}'" for code in unknown[:5])
            raise _invalid(
                f"Dimension {dim.code} ({dim.label}) has no value {shown}. Values are codes, "
                "not names; look the code up by searching the table's values.",
                args,
                value_search=unknown[0],
            )
    return len(wanted), ",".join(wanted)


async def get_data(ctx: Context, args: GetDataInput) -> Result[GetDataOutput]:
    up = _upstream(ctx)
    meta = await _metadata(up, args.table_id, args.lang)
    dims = jsonstat.dimensions(meta.json)
    by_code = {dim.code: dim for dim in dims}
    provenance: list[Provenance] = []
    notes = list(meta.notes)

    unknown_dims = [code for code in [*args.select, *args.codelists] if code not in by_code]
    if unknown_dims:
        listing = ", ".join(f"{d.code} ({d.label})" for d in dims)
        raise _invalid(
            f"Table {args.table_id} has no dimension '{unknown_dims[0]}'. "
            f"Its dimensions are: {listing}.",
            args,
        )

    codelist_codes: dict[str, list[str]] = {}
    codelist_kinds: dict[str, str] = {}
    for dim_code, codelist_id in args.codelists.items():
        offered = {c["id"]: c for c in by_code[dim_code].extension.get("codelists") or []}
        if codelist_id not in offered:
            options = ", ".join(sorted(offered)) or "none"
            raise _invalid(
                f"Dimension {dim_code} has no codelist '{codelist_id}'. Available: {options}.",
                args,
            )
        listed = await up.get_json(
            f"{BASE_URL}/codeLists/{codelist_id}", params={"lang": args.lang}, ttl="codelist"
        )
        codelist_codes[dim_code] = [v["code"] for v in listed.json.get("values") or []]
        codelist_kinds[dim_code] = offered[codelist_id].get("type", "")
        provenance.append(up.provenance(listed, title=f"Statbank codelist {codelist_id}"))

    cells = 1
    counts: dict[str, int] = {}
    expressions: dict[str, str] = {}
    missing: list[jsonstat.Dim] = []
    for dim in dims:
        codes = codelist_codes.get(dim.code, dim.codes)
        selection = args.select.get(dim.code)
        if selection is None:
            if dim.code in codelist_codes:
                selection = "*"
            elif _can_omit(dim):
                continue
            elif dim.role == "time":
                selection = Latest(latest=1)
                notes.append(
                    f"{dim.code} was not selected, so only its latest value ({codes[-1]}) is returned."
                )
            elif len(codes) == 1:
                selection = codes[:1]
            else:
                missing.append(dim)
                continue
        count, expression = _resolve(
            dim, selection, codes, check=dim.code not in codelist_codes, args=args
        )
        counts[dim.code] = count
        expressions[dim.code] = expression
        cells *= count

    if missing:
        suggested = args.model_dump(by_alias=True, exclude_defaults=True)
        suggested.setdefault("select", {})
        for dim in missing:
            suggested["select"][dim.code] = dim.codes[:1]
        names = ", ".join(f"{d.code} ({d.label})" for d in missing)
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Table {args.table_id} needs a selection for {names}; these cannot be totalled.",
            next_call=NextCall(tool="statistics_get_data", arguments=suggested),
            source_id=SPEC.id,
        )

    if cells > args.max_rows:
        raise _too_large(args, dims, counts, cells)

    params: dict[str, Any] = {"lang": args.lang, "outputFormat": "json-stat2"}
    for dim_code, expression in expressions.items():
        params[f"valueCodes[{dim_code}]"] = expression
    for dim_code, codelist_id in args.codelists.items():
        params[f"codelist[{dim_code}]"] = codelist_id
        params[f"outputValues[{dim_code}]"] = (
            "aggregated" if codelist_kinds[dim_code] == "Aggregation" else "single"
        )

    url = f"{BASE_URL}/tables/{args.table_id}/data"
    updated = str(meta.json.get("updated", ""))
    try:
        if len(urlencode(params)) <= MAX_GET_QUERY:
            fetched = await up.get_json(url, params=params, ttl="data", key_extra=updated)
        else:
            fetched = await up.post_json(
                url,
                params={"lang": args.lang, "outputFormat": "json-stat2"},
                body={"selection": _post_selection(expressions, args, codelist_kinds)},
                ttl="data",
                key_extra=updated,
            )
    except UpstreamClientError as exc:
        raise _invalid(f"SSB rejected the selection: {exc.detail}.", args) from None

    data = fetched.json
    out_dims, rows, truncated = jsonstat.rows(data, limit=args.max_rows)
    columns: list[Column] = []
    for dim in out_dims:
        columns.append(Column(key=dim.code, label=dim.label, role=dim.role))  # type: ignore[arg-type]
        columns.append(
            Column(key=f"{dim.code}_label", label=f"{dim.label} (label)", role=dim.role)  # type: ignore[arg-type]
        )
    columns.append(Column(key="value", label="value", role="value"))
    marks = sorted({row["status"] for row in rows if "status" in row})
    if marks:
        columns.append(Column(key="status", label="status", role="status"))
        meanings = ", ".join(
            f"'{m}' = {jsonstat.STATUS_MEANINGS.get(m, 'see SSB footnotes')}" for m in marks
        )
        notes.append(f"Some values carry an SSB status mark: {meanings}.")
    notes.extend(fetched.notes)
    if truncated:
        notes.append(f"Only the first {args.max_rows} rows are included.")

    title = _title(data.get("label") or meta.json.get("label"), args.table_id)
    provenance.insert(0, up.provenance(fetched, title=f"Statbank table {title}"))
    provenance.append(up.provenance(meta, title=f"Statbank table {args.table_id} (metadata)"))
    return Result(
        data=GetDataOutput(
            table_id=args.table_id,
            title=title,
            updated=_parse_time(data.get("updated")),
            columns=columns,
            rows=rows,
            row_count=len(rows),
            measures=_measures(out_dims),
        ),
        provenance=provenance,
        notes=notes,
        truncated=truncated,
    )


def _post_selection(
    expressions: dict[str, str], args: GetDataInput, kinds: dict[str, str]
) -> list[dict[str, Any]]:
    selection = []
    for dim_code, expression in expressions.items():
        item: dict[str, Any] = {"variableCode": dim_code, "valueCodes": expression.split(",")}
        if dim_code in args.codelists:
            item["codelist"] = args.codelists[dim_code]
            item["outputValues"] = "aggregated" if kinds[dim_code] == "Aggregation" else "single"
        selection.append(item)
    return selection


def _too_large(
    args: GetDataInput, dims: list[jsonstat.Dim], counts: dict[str, int], cells: int
) -> ToolError:
    time_dim = next((d for d in dims if d.role == "time" and counts.get(d.code, 1) > 1), None)
    next_call = None
    if time_dim is not None and cells // counts[time_dim.code] <= args.max_rows:
        narrowed = args.model_dump(by_alias=True, exclude_defaults=True)
        narrowed["select"] = {**narrowed.get("select", {}), time_dim.code: {"latest": 1}}
        next_call = NextCall(tool="statistics_get_data", arguments=narrowed)
        hint = f"Fewer periods would fit, e.g. only the latest {time_dim.code}."
    elif cells <= MAX_ROWS:
        widened = args.model_dump(by_alias=True, exclude_defaults=True)
        widened["max_rows"] = cells
        next_call = NextCall(tool="statistics_get_data", arguments=widened)
        hint = f"Raising max_rows to {cells} would allow it."
    else:
        widest = max(counts, key=lambda code: counts[code])
        hint = f"Select fewer values for {widest}, which has {counts[widest]} selected."
    return ToolError(
        ErrorCode.TOO_LARGE,
        f"That selection is {cells:,} rows and the limit for this call is {args.max_rows:,}. {hint}",
        next_call=next_call,
        source_id=SPEC.id,
    )


OPERATIONS = (
    Operation(
        name="statistics_search_tables",
        title="Search SSB statistics tables",
        description=(
            "Find Statistics Norway (SSB) tables by keyword. Returns table ids, titles, the "
            "period each table covers and when it was last updated. Start here for any question "
            "about Norwegian official statistics (population, prices, employment, housing, trade "
            "and so on), then call statistics_describe_table on a promising table."
        ),
        input_model=SearchTablesInput,
        output_model=SearchTablesOutput,
        handler=search_tables,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/statistics/tables",
        examples=(
            {"query": "population municipality"},
            {"query": "konsumprisindeks", "lang": "no"},
        ),
    ),
    Operation(
        name="statistics_describe_table",
        title="Describe an SSB table",
        description=(
            "Show what an SSB table contains before fetching data: its dimensions and their value "
            "codes, units, available codelists (such as counties or 5-year age groups) and footnotes. "
            "Use value_search to find a code, e.g. the code for a municipality. The answer includes "
            "example_arguments that statistics_get_data accepts as they are."
        ),
        input_model=DescribeTableInput,
        output_model=DescribeTableOutput,
        handler=describe_table,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/statistics/tables/{table_id}",
        examples=({"table_id": "07459"}, {"table_id": "07459", "value_search": "Bergen"}),
    ),
    Operation(
        name="statistics_get_data",
        title="Get data from an SSB table",
        description=(
            "Fetch numbers from an SSB table as labelled rows. Choose values per dimension in "
            "`select` with codes from statistics_describe_table: a list of codes, '*' for all, "
            "{'latest': N} for the last N periods, or {'from': code}. Dimensions you leave out "
            "are totalled where SSB allows it; time defaults to the latest period. "
            "The size is checked before anything is fetched."
        ),
        input_model=GetDataInput,
        output_model=GetDataOutput,
        handler=get_data,
        source_ids=(SPEC.id,),
        http_method="POST",
        http_path="/v1/statistics/data",
        examples=(
            {"table_id": "07459", "select": {"Region": ["0301", "4601"], "Tid": {"latest": 3}}},
            {"table_id": "07459", "codelists": {"Region": "agg_Fylker2024"}},
        ),
    ),
)
