"""Search Norway's national data catalogue on data.norge.no."""

from __future__ import annotations

import datetime as dt
from typing import Any

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.datanorge.models import (
    THEMES,
    CatalogEntry,
    CatalogSearchInput,
    CatalogSearchOutput,
    Publisher,
)
from kildeverk.sources.datanorge.spec import SEARCH_URL, SPEC

LANGUAGES = ("en", "nb", "no", "nn")
PATHS = {"datasets": "datasets", "data_services": "data-services"}
PAGES = {"DATASET": "datasets", "DATA_SERVICE": "data-services"}
DESCRIPTION_CHARS = 500


def _localised(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    for language in LANGUAGES:
        if value.get(language):
            return str(value[language]).strip()
    return next((str(v).strip() for v in value.values() if v), None)


def _short(text: str | None) -> str | None:
    if not text or len(text) <= DESCRIPTION_CHARS:
        return text
    return text[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + " …"


def _time(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except (AttributeError, ValueError):
        return None


def _format(value: str) -> str:
    return f"MEDIA_TYPE {value}" if "/" in value else f"FILE_TYPE {value.upper()}"


def _entry(hit: dict[str, Any]) -> CatalogEntry:
    org = hit.get("organization") or {}
    metadata = hit.get("metadata") or {}
    kind = "data_service" if hit.get("searchType") == "DATA_SERVICE" else "dataset"
    path = org.get("orgPath")
    return CatalogEntry(
        id=hit["id"],
        kind=kind,
        title=_localised(hit.get("title")) or hit["id"],
        description=_short(_localised(hit.get("description"))),
        publisher=Publisher(
            name=_localised(org.get("prefLabel")) or org.get("name"),
            org_number=org.get("id"),
            path=path,
        ),
        open_data=hit.get("isOpenData"),
        access=(hit.get("accessRights") or {}).get("prefLabel", {}).get("en"),
        themes=[t["code"] for t in hit.get("dataTheme") or [] if t.get("code")],
        formats=sorted(
            {
                f.removeprefix("FILE_TYPE ")
                for f in hit.get("fdkFormatPrefixed") or []
                if f.startswith("FILE_TYPE ")
            }
        ),
        keywords=[k for k in (_localised(k) for k in hit.get("keyword") or []) if k][:15],
        page_url=f"https://data.norge.no/{PAGES.get(hit.get('searchType'), 'datasets')}/{hit['id']}",
        source_url=hit.get("uri"),
        first_harvested=_time(metadata.get("firstHarvested")),
        modified=_time(metadata.get("modified")),
    )


async def catalog_search(ctx: Context, args: CatalogSearchInput) -> Result[CatalogSearchOutput]:
    up = ctx.upstream(SPEC.id)
    filters: dict[str, Any] = {}
    if args.open_data_only:
        filters["openData"] = {"value": True}
    if args.themes:
        filters["dataTheme"] = {"value": args.themes}
    if args.publisher:
        filters["orgPath"] = {"value": [args.publisher]}
    if args.formats:
        filters["formats"] = {"value": [_format(f) for f in args.formats]}
    if args.modified_within_days:
        filters["lastXDaysModified"] = {"value": args.modified_within_days}
    body: dict[str, Any] = {"pagination": {"size": args.limit, "page": args.page}}
    if args.query:
        body["query"] = args.query
    if filters:
        body["filters"] = filters
    if not args.query:
        # Without words to rank by, the newest entries first is the useful order.
        body["sort"] = {"field": "FIRST_HARVESTED", "direction": "DESC"}
    try:
        fetched = await up.post_json(f"{SEARCH_URL}/{PATHS[args.kind]}", body=body, ttl="search")
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"The data.norge.no search rejected the request: {exc.detail}",
            source_id=SPEC.id,
            upstream_status=exc.status,
        ) from None

    entries = [_entry(h) for h in fetched.json.get("hits") or []]
    page = fetched.json.get("page") or {}
    total = page.get("totalElements", len(entries))
    pages = page.get("totalPages", 1)
    notes = list(fetched.notes)
    if not entries:
        notes.append(
            "Nothing matched. Try Norwegian words, fewer filters, or kind="
            + ("'datasets'." if args.kind == "data_services" else "'data_services'.")
            if total == 0
            else "This page is past the last one."
        )
    elif args.page + 1 < pages:
        notes.append(f"{total} entries matched; ask for page={args.page + 1} for more.")
    if args.themes:
        notes.append("Themes: " + "; ".join(f"{t} = {THEMES[t]}" for t in args.themes) + ".")
    notes.append("Each entry's own licence is on its data.norge.no page.")
    return Result(
        data=CatalogSearchOutput(total_matches=total, page=args.page, pages=pages, entries=entries),
        provenance=[up.provenance(fetched, title="data.norge.no catalogue search")],
        notes=notes,
        truncated=args.page + 1 < pages,
    )


OPERATIONS = (
    Operation(
        name="catalog_search",
        title="Search Norway's data catalogue",
        description=(
            "Search data.norge.no, the national catalogue where Norwegian public bodies describe "
            "their datasets and APIs. Filter by EU theme, publisher, file format, open data, or "
            "recent change. Finds where data lives and who publishes it, with links; it does not "
            "return the data itself. Use it when no other tool covers a topic."
        ),
        input_model=CatalogSearchInput,
        output_model=CatalogSearchOutput,
        handler=catalog_search,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/catalog/search",
        examples=(
            {"query": "befolkning", "open_data_only": True},
            {"query": "vær", "kind": "data_services"},
            {"themes": ["TRAN"], "formats": ["CSV"], "limit": 5},
        ),
    ),
)
