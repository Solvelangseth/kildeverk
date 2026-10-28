"""Turn any result's provenance into references: BibTeX and CSL-JSON.

Runs locally on the provenance it is given; it calls no upstream.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Result
from kildeverk.core.operation import Operation


class CiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: list[Provenance] = Field(
        min_length=1,
        max_length=200,
        description="The `provenance` list of any Kildeverk result, as it came back.",
    )
    style: Literal["bibtex", "csl_json", "both"] = "both"


class CiteOutput(BaseModel):
    references: int = Field(description="Distinct references, after merging repeated requests.")
    bibtex: str | None
    csl_json: list[dict[str, Any]] | None


NORWEGIAN = str.maketrans({"æ": "ae", "ø": "o", "å": "aa", "Æ": "Ae", "Ø": "O", "Å": "Aa"})


def _ascii(text: str) -> str:
    # NFKD splits é into e and an accent, but leaves ø and æ whole, so those go first.
    return (
        unicodedata.normalize("NFKD", text.translate(NORWEGIAN)).encode("ascii", "ignore").decode()
    )


def _key(p: Provenance, used: set[str]) -> str:
    acronym = re.search(r"\(([A-Za-zÆØÅæøå]{2,})\)", p.publisher)
    stem = _ascii(acronym.group(1) if acronym else p.publisher.split()[0]).lower()
    base = f"{re.sub(r'[^a-z0-9]', '', stem) or 'source'}{p.retrieved_at:%Y}"
    key, n = base, 1
    while key in used:
        n += 1
        key = f"{base}{chr(ord('a') + n - 2)}"
    used.add(key)
    return key


def _bib(text: str) -> str:
    return (
        text.replace("\\", "\\textbackslash{}")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("#", "\\#")
    )


async def cite(ctx: Context, args: CiteInput) -> Result[CiteOutput]:
    # The same upstream request appearing twice (e.g. via two tools) is one reference.
    unique: dict[tuple[str, str], Provenance] = {}
    for p in args.provenance:
        unique.setdefault((p.publisher, p.request.url), p)
    used: set[str] = set()
    bib_entries, csl = [], []
    for p in unique.values():
        key = _key(p, used)
        title = p.title or p.source_name
        accessed = p.retrieved_at
        if args.style in ("bibtex", "both"):
            bib_entries.append(
                f"@misc{{{key},\n"
                f"  author       = {{{{{_bib(p.publisher)}}}}},\n"
                f"  title        = {{{_bib(title)}}},\n"
                f"  howpublished = {{{_bib(p.source_name)}}},\n"
                f"  year         = {{{accessed:%Y}}},\n"
                f"  url          = {{{p.request.url}}},\n"
                f"  urldate      = {{{accessed:%Y-%m-%d}}},\n"
                f"  note         = {{Licence: {_bib(p.licence.name)}. Retrieved via Kildeverk.}}\n"
                "}"
            )
        if args.style in ("csl_json", "both"):
            csl.append(
                {
                    "id": key,
                    "type": "dataset",
                    "author": [{"literal": p.publisher}],
                    "title": title,
                    "container-title": p.source_name,
                    "publisher": p.publisher,
                    "URL": p.request.url,
                    "accessed": {"date-parts": [[accessed.year, accessed.month, accessed.day]]},
                    "license": p.licence.url,
                    "note": f"Licence: {p.licence.name}. Retrieved via Kildeverk.",
                }
            )
    return Result(
        data=CiteOutput(
            references=len(unique),
            bibtex="\n\n".join(bib_entries) if bib_entries else None,
            csl_json=csl if csl else None,
        ),
        provenance=[],
        notes=["Publishers are cited as corporate authors; check your style's rules for datasets."],
    )


OPERATIONS = (
    Operation(
        name="cite_sources",
        title="Citations for a result",
        description=(
            "Turn the `provenance` of any Kildeverk result into references: BibTeX entries and "
            "CSL-JSON (for Zotero, Pandoc and citation processors). Repeated requests are merged. "
            "Runs locally; it fetches nothing."
        ),
        input_model=CiteInput,
        output_model=CiteOutput,
        handler=cite,
        source_ids=(),
        http_method="POST",
        http_path="/v1/cite",
        examples=(
            {
                "provenance": [
                    {
                        "source_id": "ssb_statbank",
                        "source_name": "SSB Statbank",
                        "publisher": "Statistics Norway (SSB)",
                        "title": "Statbank table 07459: Population, by region and year",
                        "licence": {
                            "id": "CC-BY-4.0",
                            "name": "Creative Commons Attribution 4.0 International",
                            "url": "https://creativecommons.org/licenses/by/4.0/",
                        },
                        "request": {
                            "method": "GET",
                            "url": "https://data.ssb.no/api/pxwebapi/v2/tables/07459/data?lang=en",
                            "body": None,
                        },
                        "retrieved_at": "2026-10-28T07:02:11Z",
                        "cache": {"hit": False, "age_s": 0.0, "stale": False},
                        "citation": "Statistics Norway (SSB): Statbank table 07459. Retrieved 2026-10-28.",
                    }
                ],
                "style": "bibtex",
            },
        ),
    ),
)
