"""Norway's region history as a graph, built from Klass codes and code changes.

A code is not an identity. `0712` was Skoger until 1964 and Larvik from 2018, and
`1103` Stavanger after 2020 covers more ground than `1103` before it. So the
graph's nodes are *units*: one code over one stretch of time during which its
territory, as far as Klass records it, did not change. A unit ends wherever its
code appears in a change, even a change that keeps the code (Stavanger absorbing
Finnøy is recorded as 1103 -> 1103). Edges run from the units that ended on a
date to the units that began on it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Any

from kildeverk.core.errors import ErrorCode, ToolError


@dataclass(frozen=True)
class Unit:
    code: str
    name: str
    valid_from: date
    valid_to: date | None  # exclusive; None while still valid

    def valid_at(self, when: date) -> bool:
        return self.valid_from <= when and (self.valid_to is None or when < self.valid_to)

    def overlaps_year(self, year: int) -> bool:
        return self.valid_from < date(year + 1, 1, 1) and (
            self.valid_to is None or self.valid_to > date(year, 1, 1)
        )

    def distance_to_year(self, year: int) -> int:
        start, end = date(year, 1, 1), date(year + 1, 1, 1)
        if self.valid_to is not None and self.valid_to <= start:
            return (start - self.valid_to).days
        if self.valid_from >= end:
            return (self.valid_from - end).days
        return 0

    @property
    def span(self) -> str:
        end = "" if self.valid_to is None else str(self.valid_to.year - 1)
        return f"{self.valid_from.year}-{end}"


@dataclass(frozen=True)
class Change:
    when: date
    old_code: str
    old_name: str
    new_code: str
    new_name: str


@dataclass(frozen=True)
class Mapping:
    targets: frozenset[Unit]
    split: bool  # some step divided one unit into several, so values cannot follow exactly

    @property
    def exact(self) -> bool:
        return len(self.targets) == 1 and not self.split


def _day(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


class RegionHistory:
    def __init__(self, codes: dict[str, Any], changes: dict[str, Any], *, requested_to: date):
        self.changes = sorted(
            (
                Change(
                    _day(c["changeOccurred"]),  # type: ignore[arg-type]
                    c["oldCode"],
                    c.get("oldName") or c["oldCode"],
                    c["newCode"],
                    c.get("newName") or c["newCode"],
                )
                for c in changes.get("codeChanges") or []
            ),
            key=lambda c: c.when,
        )
        cuts: dict[str, set[date]] = defaultdict(set)
        for change in self.changes:
            cuts[change.old_code].add(change.when)
            cuts[change.new_code].add(change.when)

        # Contiguous entries for one code (Klass splits them on renames) become one
        # period, then each period is cut at every change its code took part in.
        periods: dict[str, list[tuple[date, date | None, list[tuple[date, str]]]]] = defaultdict(
            list
        )
        for entry in sorted(
            codes.get("codes") or [], key=lambda e: (e["code"], e["validFromInRequestedRange"])
        ):
            start = _day(entry["validFromInRequestedRange"])
            end = _day(entry["validToInRequestedRange"])
            end = None if end is not None and end >= requested_to else end
            names = periods[entry["code"]]
            if names and names[-1][1] == start:
                prev_start, _, prev_names = names[-1]
                names[-1] = (prev_start, end, [*prev_names, (start, entry["name"])])
            else:
                names.append((start, end, [(start, entry["name"])]))

        self.units: dict[str, list[Unit]] = defaultdict(list)
        for code, code_periods in periods.items():
            for start, end, names in code_periods:
                inner = sorted(
                    d for d in cuts.get(code, ()) if start < d and (end is None or d < end)
                )
                bounds = [start, *inner, end]
                for seg_start, seg_end in pairwise(bounds):
                    name = [n for since, n in names if since <= seg_start][-1]
                    self.units[code].append(Unit(code, name, seg_start, seg_end))

        self.forward: dict[Unit, list[Unit]] = defaultdict(list)
        self.backward: dict[Unit, list[Unit]] = defaultdict(list)
        for change in self.changes:
            old = self._ending(change.old_code, change.when)
            new = self.unit_at(change.new_code, change.when)
            if old is None or new is None or old == new:
                continue
            if new not in self.forward[old]:
                self.forward[old].append(new)
                self.backward[new].append(old)

    # --- lookup -------------------------------------------------------------

    def _ending(self, code: str, when: date) -> Unit | None:
        return next((u for u in self.units.get(code, ()) if u.valid_to == when), None)

    def unit_at(self, code: str, when: date) -> Unit | None:
        return next((u for u in self.units.get(code, ()) if u.valid_at(when)), None)

    def units_at(self, when: date) -> list[Unit]:
        return sorted(
            (u for units in self.units.values() for u in units if u.valid_at(when)),
            key=lambda u: u.code,
        )

    def unit_for_year(self, code: str, year: int) -> tuple[Unit | None, bool]:
        """The unit a value for `year` belongs to, and whether the code was valid then."""

        units = self.units.get(code, [])
        overlapping = [u for u in units if u.overlaps_year(year)]
        if overlapping:
            return overlapping[-1], True
        if not units:
            return None, False
        return min(units, key=lambda u: u.distance_to_year(year)), False

    def search(self, text: str) -> list[Unit]:
        needle = text.casefold().strip()
        if needle.isdigit():
            return list(self.units.get(needle, []))
        return [u for units in self.units.values() for u in units if needle in u.name.casefold()]

    # --- mapping ------------------------------------------------------------

    def map_to(self, unit: Unit, target: date) -> Mapping:
        """Follow the change graph from `unit` until every branch is valid on `target`."""

        frontier = {unit}
        split = False
        for _ in range(200):  # one step per change date at most; this bound is never reached
            following: set[Unit] = set()
            moved = False
            for current in frontier:
                if current.valid_at(target):
                    following.add(current)
                    continue
                if current.valid_to is not None and current.valid_to <= target:
                    nxt = self.forward.get(current, [])
                else:
                    nxt = self.backward.get(current, [])
                if not nxt:
                    # Ended without a recorded successor (or began without a predecessor).
                    following.add(current)
                    continue
                split = split or len(nxt) > 1
                following.update(nxt)
                moved = True
            frontier = following
            if not moved:
                break
        return Mapping(frozenset(u for u in frontier if u.valid_at(target)), split)


def target_date(target: str, today: date) -> date:
    if target == "latest":
        return today
    if target in ("2020", "2024"):
        return date(int(target), 1, 1)
    when = date.fromisoformat(target)
    if when > today:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"The target date {target} is in the future; borders are only known up to today.",
        )
    return when
