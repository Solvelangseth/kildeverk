"""Reading JSON-stat 2.0, the format SSB returns for both metadata and data."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

ROLE_NAMES = {"time": "time", "geo": "region", "metric": "measure"}

# SSB's markers for cells without a number.
STATUS_MEANINGS = {
    ".": "not applicable",
    "..": "not available",
    "...": "not yet available",
    ":": "confidential",
    "-": "nil",
}


@dataclass(frozen=True)
class Dim:
    code: str
    label: str
    role: str
    codes: list[str]
    labels: dict[str, str]
    extension: dict[str, Any]
    units: dict[str, Any]


def dimensions(ds: dict[str, Any]) -> list[Dim]:
    roles: dict[str, str] = {}
    for role, codes in (ds.get("role") or {}).items():
        for code in codes:
            roles[code] = ROLE_NAMES.get(role, "other")
    dims = []
    for code in ds["id"]:
        raw = ds["dimension"][code]
        category = raw.get("category") or {}
        dims.append(
            Dim(
                code=code,
                label=raw.get("label") or code,
                role=roles.get(code, "other"),
                codes=_ordered_codes(category),
                labels=category.get("label") or {},
                extension=raw.get("extension") or {},
                units=category.get("unit") or {},
            )
        )
    return dims


def _ordered_codes(category: dict[str, Any]) -> list[str]:
    index = category.get("index")
    if isinstance(index, list):
        return [str(code) for code in index]
    if isinstance(index, dict):
        return [code for code, _ in sorted(index.items(), key=lambda item: item[1])]
    # A single-value dimension may omit the index.
    return list((category.get("label") or {}).keys())


def _at(container: Any, i: int) -> Any:
    if container is None:
        return None
    if isinstance(container, list):
        return container[i] if i < len(container) else None
    if isinstance(container, dict):
        return container.get(str(i))
    # A single string applies to every cell.
    return container


def rows(ds: dict[str, Any], *, limit: int) -> tuple[list[Dim], list[dict[str, Any]], bool]:
    """Every cell as a flat row, in JSON-stat order (last dimension fastest)."""

    dims = dimensions(ds)
    values = ds.get("value")
    status = ds.get("status")
    out: list[dict[str, Any]] = []
    total = 1
    for dim in dims:
        total *= len(dim.codes)
    for i, combo in enumerate(itertools.product(*(dim.codes for dim in dims))):
        if i >= limit:
            return dims, out, total > limit
        row: dict[str, Any] = {}
        for dim, code in zip(dims, combo, strict=True):
            row[dim.code] = code
            row[f"{dim.code}_label"] = dim.labels.get(code, code)
        row["value"] = _at(values, i)
        if (mark := _at(status, i)) is not None:
            row["status"] = mark
        out.append(row)
    return dims, out, False
