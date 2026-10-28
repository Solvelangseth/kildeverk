"""Turn a municipality or county name into today's code, for tools that filter by code.

Codes pass through untouched, so a tool given a code behaves exactly as before. A name is
looked up in Klass's history (already cached for the region tools): a current name gives
its code; a former municipality that became exactly one of today's gives that one's code;
anything else is an error that says what would work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Summary
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.sources.ssb_klass.history import Unit
from kildeverk.sources.ssb_klass.ops import _history, _today

Level = Literal["municipality", "county"]
CODE_LENGTH = {"municipality": 4, "county": 2}

# Field descriptions for tools that accept either.
MUNICIPALITY_HELP = (
    "Municipality code ('4601') or name ('Bergen'); names are resolved to today's code."
)
COUNTY_HELP = "County number ('46') or name ('Vestland'); names are resolved to today's number."
MUNICIPALITY_PATTERN = r"^(\d{4}|[^\d].{1,59})$"
COUNTY_PATTERN = r"^(\d{2}|[^\d].{1,59})$"


@dataclass
class Resolved:
    code: str
    note: str | None = None
    provenance: list[Provenance] = field(default_factory=list)


def _names(unit: Unit) -> set[str]:
    """'Trondheim - Tråante' answers to the whole name and to each part."""

    full = unit.name.casefold()
    return {full, *(part.strip() for part in full.split(" - "))}


async def resolve_region(ctx: Context, value: str, level: Level) -> Resolved:
    value = value.strip()
    if value.isdigit():
        return Resolved(code=value)

    history, provenance, _ = await _history(ctx, level)
    needle = value.casefold()
    today = _today()
    current = history.units_at(today)

    exact = {u.code: u for u in current if needle in _names(u)}
    if not exact:
        exact = {u.code: u for u in current if needle in u.name.casefold()}
    if len(exact) == 1:
        unit = next(iter(exact.values()))
        note = None if needle in _names(unit) else f"'{value}' was read as {unit.code} {unit.name}."
        return Resolved(code=unit.code, note=note, provenance=provenance)
    if len(exact) > 1:
        options = ", ".join(
            f"{u.code} {u.name}" for u in sorted(exact.values(), key=lambda u: u.code)
        )
        raise ToolError(
            ErrorCode.AMBIGUOUS,
            f"'{value}' fits several {level} names: {options}. Give the code.",
            next_call=NextCall(tool="regions_resolve", arguments={"query": value, "level": level}),
        )

    # A former name: follow it to today's map if it lands on exactly one region.
    targets = set()
    for unit in (u for u in history.search(value) if needle in _names(u)):
        mapping = history.map_to(unit, today)
        if mapping.exact:
            targets |= set(mapping.targets)
    if len(targets) == 1:
        unit = targets.pop()
        return Resolved(
            code=unit.code,
            note=f"{value} is today part of {unit.code} {unit.name}; results are for all of it.",
            provenance=provenance,
        )
    if targets:
        options = ", ".join(f"{u.code} {u.name}" for u in sorted(targets, key=lambda u: u.code))
        raise ToolError(
            ErrorCode.AMBIGUOUS,
            f"'{value}' was the name of {level} that are now in different places: {options}. "
            "Give the code.",
            next_call=NextCall(tool="regions_resolve", arguments={"query": value, "level": level}),
        )
    raise ToolError(
        ErrorCode.NOT_FOUND,
        f"No {level}, past or present, is called '{value}', or it was later divided.",
        next_call=NextCall(tool="regions_resolve", arguments={"query": value, "level": level}),
    )


async def resolve_fields(
    ctx: Context, args: object, fields: dict[str, Level]
) -> tuple[list[str], list[Provenance]]:
    """Replace names with codes in `args` (in place), for each field that is set.

    List fields (e.g. several municipalities) are resolved item by item. Returns notes for
    the result and the Klass provenance, when a name was looked up.
    """

    notes: list[str] = []
    provenance: list[Provenance] = []
    for name, level in fields.items():
        value = getattr(args, name, None)
        if not value:
            continue
        values = value if isinstance(value, list) else [value]
        codes = []
        for item in values:
            resolved = await resolve_region(ctx, item, level)
            codes.append(resolved.code)
            if resolved.note:
                notes.append(resolved.note)
            if resolved.provenance and not provenance:
                provenance = resolved.provenance
        setattr(args, name, codes if isinstance(value, list) else codes[0])
    return notes, provenance


def with_region_names(fields: dict[str, Level]):
    """Wrap a handler so the given fields accept names as well as codes."""

    def wrap(handler):
        async def resolving(ctx: Context, args):
            notes, provenance = await resolve_fields(ctx, args, fields)
            result = await handler(ctx, args)
            if notes or provenance:
                result.provenance = [*provenance, *result.provenance]
                result.notes = [*result.notes, *notes]
                result.summary = Summary.of(result.provenance)
            return result

        resolving.__name__ = handler.__name__
        return resolving

    return wrap
