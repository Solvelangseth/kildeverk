"""Region tools backed by SSB Klass: codes, their history, and converting series between borders."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.sources.ssb_klass.history import Mapping, RegionHistory, Unit, target_date
from kildeverk.sources.ssb_klass.models import (
    ChangeEvent,
    ChangesInput,
    ChangesOutput,
    CodeMapping,
    HarmonisedRow,
    HarmoniseInput,
    HarmoniseOutput,
    ListInput,
    ListOutput,
    Match,
    Region,
    ResolveInput,
    ResolveOutput,
    Unconverted,
)
from kildeverk.sources.ssb_klass.spec import (
    BASE_URL,
    CLASSIFICATIONS,
    HISTORY_FROM,
    HISTORY_TO,
    SPEC,
)

EARLIEST = date.fromisoformat(HISTORY_FROM)
MAX_UNCONVERTED_LISTED = 200
LEVEL_NAMES = {"municipality": "municipalities", "county": "counties"}


def _today() -> date:
    return datetime.now(UTC).date()


async def _history(ctx: Context, level: str) -> tuple[RegionHistory, list[Provenance], list[str]]:
    up = ctx.upstream(SPEC.id)
    classification = CLASSIFICATIONS[level]
    params = {"from": HISTORY_FROM, "to": HISTORY_TO}
    base = f"{BASE_URL}/classifications/{classification}"
    codes = await up.get_json(f"{base}/codes", params=params, ttl="history")
    changes = await up.get_json(f"{base}/changes", params=params, ttl="history")

    # Building the graph takes a moment; reuse it until either response is refreshed.
    key = ("klass_history", level, codes.retrieved_at, changes.retrieved_at)
    history = ctx.memo.get(key)
    if history is None:
        history = RegionHistory(
            codes.json, changes.json, requested_to=date.fromisoformat(HISTORY_TO)
        )
        ctx.memo = {k: v for k, v in ctx.memo.items() if k[:2] != key[:2]}
        ctx.memo[key] = history

    names = LEVEL_NAMES[level]
    provenance = [
        up.provenance(codes, title=f"Klass classification {classification} ({names}), codes"),
        up.provenance(changes, title=f"Klass classification {classification} ({names}), changes"),
    ]
    return history, provenance, [*codes.notes, *changes.notes]


def _check_date(when: date, field: str) -> None:
    if when < EARLIEST:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"{field} {when} is before {HISTORY_FROM}; region history is only known from then.",
        )


# --- regions_list ----------------------------------------------------------------


async def regions_list(ctx: Context, args: ListInput) -> Result[ListOutput]:
    when = args.on_date or _today()
    _check_date(when, "on_date")
    history, provenance, notes = await _history(ctx, args.level)
    regions = [Region(code=u.code, name=u.name) for u in history.units_at(when)]
    return Result(
        data=ListOutput(level=args.level, valid_on=when, count=len(regions), regions=regions),
        provenance=provenance,
        notes=notes,
    )


# --- regions_resolve -------------------------------------------------------------


def _rank(unit: Unit, needle: str) -> int:
    if needle == unit.code:
        return 0
    parts = [part.strip().casefold() for part in unit.name.split(" - ")]
    if needle in parts:
        return 0
    if any(part.startswith(needle) for part in parts):
        return 1
    return 2


async def regions_resolve(ctx: Context, args: ResolveInput) -> Result[ResolveOutput]:
    today = _today()
    needle = args.query.casefold().strip()
    levels = [args.level] if args.level else ["municipality", "county"]
    found: list[tuple[tuple[int, int, int], Match]] = []
    provenance: list[Provenance] = []
    notes: list[str] = []
    for level in levels:
        history, level_provenance, level_notes = await _history(ctx, level)
        provenance += level_provenance
        notes += level_notes
        for unit in history.search(needle):
            mapping = history.map_to(unit, today)
            match = Match(
                level=level,
                code=unit.code,
                name=unit.name,
                valid_from=unit.valid_from,
                valid_to=unit.valid_to,
                status="current" if unit.valid_to is None else "ended",
                today=[
                    Region(code=u.code, name=u.name)
                    for u in sorted(mapping.targets, key=lambda u: u.code)
                ],
                today_exact=mapping.exact,
            )
            order = (
                _rank(unit, needle),
                0 if unit.valid_to is None else 1,
                -unit.valid_from.toordinal(),
            )
            found.append((order, match))
    found.sort(key=lambda item: item[0])
    if not found:
        notes.append(f"No region name or code since {HISTORY_FROM} contains '{args.query}'.")
    return Result(
        data=ResolveOutput(matches=[m for _, m in found[: args.limit]]),
        provenance=provenance,
        notes=notes,
    )


# --- regions_changes -------------------------------------------------------------


def _root(parent: dict[str, str], node: str) -> str:
    while parent.setdefault(node, node) != node:
        node = parent[node]
    return node


def _event_kind(before: list[Region], after: list[Region]) -> str | None:
    if len(before) == 1 and len(after) == 1:
        old, new = before[0], after[0]
        if old.code == new.code:
            return "rename" if old.name != new.name else None
        return "renumber" if old.name == new.name else "renumber_and_rename"
    if len(after) == 1:
        return "merge"
    if len(before) == 1:
        return "split"
    return "reorganisation"


async def regions_changes(ctx: Context, args: ChangesInput) -> Result[ChangesOutput]:
    to_date = args.to_date or _today()
    _check_date(args.from_date, "from_date")
    if to_date < args.from_date:
        raise ToolError(ErrorCode.INVALID_ARGUMENT, "to_date is before from_date.")
    history, provenance, notes = await _history(ctx, args.level)

    by_date = defaultdict(list)
    for change in history.changes:
        if args.from_date <= change.when <= to_date:
            by_date[change.when].append(change)

    events: list[ChangeEvent] = []
    for when in sorted(by_date):
        # Changes on one date that share a code belong to one event.
        parent: dict[str, str] = {}
        for change in by_date[when]:
            parent[_root(parent, "old:" + change.old_code)] = _root(
                parent, "new:" + change.new_code
            )
        groups = defaultdict(list)
        for change in by_date[when]:
            groups[_root(parent, "new:" + change.new_code)].append(change)

        for changes in groups.values():
            codes = {c.old_code for c in changes} | {c.new_code for c in changes}
            if args.code and args.code not in codes:
                continue
            before = list(
                {c.old_code: Region(code=c.old_code, name=c.old_name) for c in changes}.values()
            )
            after = list(
                {c.new_code: Region(code=c.new_code, name=c.new_name) for c in changes}.values()
            )
            kind = _event_kind(before, after)
            if kind is not None:
                events.append(ChangeEvent(date=when, kind=kind, before=before, after=after))

    return Result(
        data=ChangesOutput(
            level=args.level, from_date=args.from_date, to_date=to_date, events=events
        ),
        provenance=provenance,
        notes=notes,
    )


# --- regions_harmonise -----------------------------------------------------------


class _Graph:
    """Mappings and target compositions, each computed once per call."""

    def __init__(self, history: RegionHistory, target: date) -> None:
        self.history = history
        self.target = target
        self._maps: dict[Unit, Mapping] = {}
        self._compositions: dict[date, dict[Unit, list[Unit]]] = {}

    def map(self, unit: Unit) -> Mapping:
        if unit not in self._maps:
            self._maps[unit] = self.history.map_to(unit, self.target)
        return self._maps[unit]

    def pieces(self, snapshot: date, target: Unit) -> list[Unit]:
        """Every unit valid on `snapshot` that maps wholly or partly onto `target`."""

        if snapshot not in self._compositions:
            composition: dict[Unit, list[Unit]] = defaultdict(list)
            for unit in self.history.units_at(snapshot):
                for reached in self.map(unit).targets:
                    composition[reached].append(unit)
            self._compositions[snapshot] = composition
        return self._compositions[snapshot].get(target, [])


def _label(unit: Unit) -> str:
    return f"{unit.code} {unit.name}"


def _kind(graph: _Graph, unit: Unit, mapping: Mapping) -> str:
    if not mapping.targets:
        return "no_successor"
    if not mapping.exact:
        return "split"
    target = next(iter(mapping.targets))
    last_day = unit.valid_from if unit.valid_to is None else unit.valid_to - timedelta(days=1)
    if len(graph.pieces(max(unit.valid_from, last_day), target)) > 1:
        return "merged"
    return "unchanged" if target.code == unit.code else "renumbered"


async def regions_harmonise(ctx: Context, args: HarmoniseInput) -> Result[HarmoniseOutput]:
    target = target_date(args.target, _today())
    _check_date(target, "target")
    history, provenance, notes = await _history(ctx, args.level)
    graph = _Graph(history, target)

    unconverted: list[Unconverted] = []
    skipped_placeholders = skipped_missing = 0
    outside: set[str] = set()
    seen_units: dict[Unit, None] = {}
    groups: dict[tuple[Unit, str], list[tuple[Unit, float]]] = defaultdict(list)

    for row in args.rows:
        if row.value is None:
            skipped_missing += 1
            continue
        year = int(row.period[:4])
        unit, in_validity = history.unit_for_year(row.region, year)
        if unit is None:
            unconverted.append(
                Unconverted(
                    region=row.region,
                    period=row.period,
                    reason=f"Klass has no {args.level} code {row.region} valid since {HISTORY_FROM}.",
                )
            )
            continue
        if not in_validity:
            if row.value == 0:
                skipped_placeholders += 1
                continue
            outside.add(row.region)
        seen_units[unit] = None
        mapping = graph.map(unit)
        if not mapping.targets:
            reason = f"{_label(unit)} ({unit.span}) has no successor recorded in Klass."
        elif not mapping.exact:
            parts = ", ".join(_label(u) for u in sorted(mapping.targets, key=lambda u: u.code))
            direction = (
                "was split into"
                if unit.valid_to is not None and unit.valid_to <= target
                else "was formed from"
            )
            reason = (
                f"{_label(unit)} ({unit.span}) {direction} {parts}. Klass does not say how values "
                "divided between them, so this cannot be converted exactly."
            )
        else:
            groups[(next(iter(mapping.targets)), row.period)].append((unit, row.value))
            continue
        unconverted.append(Unconverted(region=row.region, period=row.period, reason=reason))

    rows: list[HarmonisedRow] = []
    for (goal, period), contributions in groups.items():
        units = [unit for unit, _ in contributions]
        reason = _group_problem(graph, goal, period, units, args.measure)
        if reason:
            unconverted.append(Unconverted(region=goal.code, period=period, reason=reason))
            continue
        method = (
            "summed"
            if len(units) > 1
            else ("unchanged" if units[0].code == goal.code else "renumbered")
        )
        rows.append(
            HarmonisedRow(
                region=goal.code,
                region_name=goal.name,
                period=period,
                value=sum(value for _, value in contributions),
                method=method,  # type: ignore[arg-type]
                sources=sorted(unit.code for unit in units),
            )
        )
    rows.sort(key=lambda r: (r.region, r.period))

    if not rows and unconverted:
        first_year = min(int(row.period[:4]) for row in args.rows)
        first = "; ".join(sorted({u.reason for u in unconverted})[:3])
        raise ToolError(
            ErrorCode.NOT_CONVERTIBLE,
            f"None of the rows could be converted to the {target} borders. {first}",
            next_call=NextCall(
                tool="regions_changes",
                arguments={
                    "level": args.level,
                    "from_date": f"{max(first_year, EARLIEST.year)}-01-01",
                },
            ),
            source_id=SPEC.id,
        )

    if outside:
        listed = ", ".join(sorted(outside)[:10])
        notes.append(
            f"Some codes had values for years when they did not exist ({listed}). SSB sometimes "
            "back-casts a series to newer borders; these values were used as given."
        )
    if len(unconverted) > MAX_UNCONVERTED_LISTED:
        notes.append(
            f"{len(unconverted)} rows could not be converted; the first {MAX_UNCONVERTED_LISTED} are listed."
        )
    notes.append(
        "Klass records code changes, not small boundary adjustments between municipalities that "
        "kept their codes; those are not reflected."
    )

    mapping = [
        CodeMapping(
            code=unit.code,
            name=unit.name,
            valid=unit.span,
            to=[
                Region(code=u.code, name=u.name)
                for u in sorted(graph.map(unit).targets, key=lambda u: u.code)
            ],
            kind=_kind(graph, unit, graph.map(unit)),  # type: ignore[arg-type]
            exact=graph.map(unit).exact,
        )
        for unit in sorted(seen_units, key=lambda u: (u.code, u.valid_from))
    ]
    return Result(
        data=HarmoniseOutput(
            level=args.level,
            target_date=target,
            measure=args.measure,
            rows=rows,
            mapping=mapping,
            unconverted=unconverted[:MAX_UNCONVERTED_LISTED],
            skipped_placeholders=skipped_placeholders,
            skipped_missing=skipped_missing,
        ),
        provenance=provenance,
        notes=notes,
        truncated=len(unconverted) > MAX_UNCONVERTED_LISTED,
    )


def _group_problem(
    graph: _Graph, goal: Unit, period: str, units: list[Unit], measure: str
) -> str | None:
    """Why the values for one target region and period cannot be combined, if they cannot."""

    if len(set(units)) != len(units):
        return f"More than one input row for the same region and period maps to {_label(goal)}."
    year = int(period[:4])
    latest_start = max(u.valid_from for u in units)
    snapshot = max(latest_start, date(year, 1, 1))
    if not all(u.valid_at(snapshot) for u in units):
        snapshot = latest_start
        if not all(u.valid_at(snapshot) for u in units):
            spans = ", ".join(f"{_label(u)} ({u.span})" for u in units)
            return (
                f"Values from different border vintages map to {_label(goal)}: {spans}. "
                "Give one vintage per period, or they would be counted twice."
            )
    pieces = graph.pieces(snapshot, goal)
    partial = [p for p in pieces if not graph.map(p).exact]
    if partial:
        return (
            f"{_label(goal)} includes part of {', '.join(_label(p) for p in partial)}, which was "
            "split; that part's value is unknown."
        )
    if len(pieces) > 1 and measure == "non_additive":
        return (
            f"{_label(goal)} is made of {', '.join(_label(p) for p in pieces)}, and non-additive "
            "values (rates, averages) cannot be combined without weights."
        )
    missing = [p for p in pieces if p not in units]
    if missing:
        return (
            f"{_label(goal)} also includes {', '.join(_label(p) for p in missing)}; values for "
            "those are needed too."
        )
    return None


OPERATIONS = (
    Operation(
        name="regions_list",
        title="List municipalities or counties",
        description=(
            "List every Norwegian municipality or county with its code and name, as of today or "
            "any date since 1960. Use it to get the current codes, or the codes that applied in "
            "a past year."
        ),
        input_model=ListInput,
        output_model=ListOutput,
        handler=regions_list,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/regions",
        examples=({"level": "county"}, {"level": "municipality", "on_date": "2019-06-30"}),
    ),
    Operation(
        name="regions_resolve",
        title="Find a municipality or county",
        description=(
            "Look up a Norwegian municipality or county by name or code, including former ones. "
            "Each match shows when the code was valid and what it is part of today, so 'Tromsø' "
            "returns 1902 (until 2019), 5401 (2020-2023) and 5501 (from 2024)."
        ),
        input_model=ResolveInput,
        output_model=ResolveOutput,
        handler=regions_resolve,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/regions/search",
        examples=({"query": "Tromsø"}, {"query": "Viken", "level": "county"}),
    ),
    Operation(
        name="regions_changes",
        title="Region changes over time",
        description=(
            "List the mergers, splits, renumberings and renamings of Norwegian municipalities or "
            "counties between two dates, grouped into events. Filter by code to see one "
            "region's history."
        ),
        input_model=ChangesInput,
        output_model=ChangesOutput,
        handler=regions_changes,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/regions/changes",
        examples=(
            {"level": "county", "from_date": "2019-01-01"},
            {"level": "municipality", "from_date": "2019-01-01", "code": "1507"},
        ),
    ),
    Operation(
        name="regions_harmonise",
        title="Convert a regional series to other borders",
        description=(
            "Convert values by municipality or county to the borders of another date, so a series "
            "spanning the 2020 and 2024 reforms lines up. Mergers are summed for additive values "
            "and renumberings are followed. Anything that cannot be converted exactly (a split, a "
            "missing piece, a rate that would need weights) is listed in `unconverted` with the "
            "reason, never estimated. Rows usually come from statistics_get_data: pass "
            "{region, period, value}."
        ),
        input_model=HarmoniseInput,
        output_model=HarmoniseOutput,
        handler=regions_harmonise,
        source_ids=(SPEC.id,),
        http_method="POST",
        http_path="/v1/regions/harmonise",
        examples=(
            {
                "level": "municipality",
                "target": "2024",
                "measure": "additive",
                "rows": [
                    {"region": "1201", "period": "2019", "value": 281190},
                    {"region": "4601", "period": "2023", "value": 289330},
                ],
            },
        ),
    ),
)
