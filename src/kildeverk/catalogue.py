"""The machine-readable catalogue the website is built from."""

from __future__ import annotations

from typing import Any

from kildeverk import __version__
from kildeverk.sources.meta import source_infos
from kildeverk.sources.registry import operations


def build_catalogue() -> dict[str, Any]:
    return {
        "version": __version__,
        "sources": [info.model_dump(mode="json") for info in source_infos()],
        "tools": [
            {
                "name": op.name,
                "title": op.title,
                "description": op.description,
                "sources": list(op.source_ids),
                "http": {"method": op.http_method, "path": op.http_path},
                "input_schema": op.input_schema(),
                "examples": list(op.examples),
            }
            for op in operations()
        ],
    }
