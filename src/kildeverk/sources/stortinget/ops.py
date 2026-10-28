"""Cases, votes and members from Stortinget's open data service."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from collections import Counter
from typing import Any

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import Fetched, Upstream, UpstreamClientError
from kildeverk.sources.stortinget.models import (
    CASE_TYPES,
    DOCUMENT_GROUPS,
    STATUS,
    CaseInput,
    CaseOutput,
    CasesInput,
    CasesOutput,
    CaseSummary,
    Committee,
    Member,
    MembersInput,
    MembersOutput,
    PartyVote,
    Vote,
)
from kildeverk.sources.stortinget.spec import BASE_URL, SPEC

# How each representative voted, in voteringsresultat.
FOR, AGAINST, ABSENT = 2, 3, 1
CASE_PAGE = "https://www.stortinget.no/no/Saker-og-publikasjoner/Saker/Sak/?p={id}"
_DATE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")


def _date(value: Any) -> dt.datetime | None:
    """Stortinget's '/Date(1781864904800+0200)/': milliseconds since the epoch, and an offset."""

    match = _DATE.fullmatch(value or "") if isinstance(value, str) else None
    if not match:
        return None
    offset = match.group(2) or "+0000"
    tz = dt.timezone(
        (1 if offset[0] == "+" else -1)
        * dt.timedelta(hours=int(offset[1:3]), minutes=int(offset[3:]))
    )
    return dt.datetime.fromtimestamp(int(match.group(1)) / 1000, tz)


def _get(up: Upstream, path: str, ttl: str, **params: Any) -> Any:
    return up.get_json(f"{BASE_URL}/{path}", params={**params, "format": "json"}, ttl=ttl)


def _committee(value: Any) -> Committee | None:
    if isinstance(value, dict) and value.get("id"):
        return Committee(id=value["id"], name=value.get("navn") or value["id"])
    return None


def _person(p: dict[str, Any]) -> str:
    party = (p.get("parti") or {}).get("id")
    name = f"{p.get('fornavn', '')} {p.get('etternavn', '')}".strip()
    return f"{name} ({party})" if party else name


async def _current_session(up: Upstream) -> str:
    fetched = await _get(up, "sesjoner", "sessions")
    return fetched.json["innevaerende_sesjon"]["id"]


# --- parliament_cases --------------------------------------------------------------


async def cases(ctx: Context, args: CasesInput) -> Result[CasesOutput]:
    up = ctx.upstream(SPEC.id)
    session = args.session or await _current_session(up)
    try:
        fetched = await _get(up, "saker", "cases", sesjonid=session)
    except UpstreamClientError:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Stortinget has no session {session}. Sessions run from October to September, "
            "e.g. '2025-2026', and the data starts in the 1990s.",
            next_call=NextCall(tool="parliament_cases", arguments={}),
            source_id=SPEC.id,
        ) from None
    items = fetched.json.get("saker_liste") or []

    words = [w.lower() for w in (args.query or "").split()]
    found: list[CaseSummary] = []
    for item in items:
        title = item.get("tittel") or ""
        haystack = f"{title} {item.get('korttittel') or ''} {item.get('henvisning') or ''}".lower()
        if words and not all(w in haystack for w in words):
            continue
        summary = CaseSummary(
            id=item["id"],
            title=title,
            short_title=item.get("korttittel"),
            type=CASE_TYPES.get(item.get("type"), str(item.get("type"))),
            status=STATUS.get(item.get("status"), str(item.get("status"))),
            document_group=DOCUMENT_GROUPS.get(item.get("dokumentgruppe"), "unspecified"),
            reference=item.get("henvisning"),
            committee=_committee(item.get("komite")),
            session=item.get("behandlet_sesjon_id"),
            updated=_date(item.get("sist_oppdatert_dato")),
        )
        if args.type and summary.type != args.type:
            continue
        if args.status and summary.status != args.status:
            continue
        if args.committee and (
            summary.committee is None or summary.committee.id.lower() != args.committee.lower()
        ):
            continue
        found.append(summary)
    oldest = dt.datetime.min.replace(tzinfo=dt.UTC)
    found.sort(key=lambda c: c.updated or oldest, reverse=True)

    notes = list(fetched.notes)
    if not items:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Stortinget has no cases for session {session}. Sessions run from October to "
            "September, e.g. '2025-2026'.",
            next_call=NextCall(tool="parliament_cases", arguments={}),
            source_id=SPEC.id,
        )
    if not found:
        notes.append("No case matched. Titles are Norwegian; try fewer or Norwegian words.")
    elif len(found) > args.limit:
        notes.append(
            f"{len(found)} cases matched; the {args.limit} most recently updated are included."
        )
    notes.append("Votes and the decision for a case are in parliament_case.")
    return Result(
        data=CasesOutput(session=session, total_matches=len(found), cases=found[: args.limit]),
        provenance=[up.provenance(fetched, title=f"Stortinget cases, session {session}")],
        notes=notes,
        truncated=len(found) > args.limit,
    )


# --- parliament_case ---------------------------------------------------------------


def _parties(results: list[dict[str, Any]]) -> list[PartyVote]:
    counts: Counter[tuple[str, int]] = Counter()
    names: dict[str, str | None] = {}
    for r in results:
        party = (r.get("representant") or {}).get("parti") or {}
        pid = party.get("id") or "?"
        names[pid] = party.get("navn")
        counts[(pid, r.get("votering"))] += 1
    parties = sorted(names, key=lambda p: -sum(counts[(p, v)] for v in (FOR, AGAINST, ABSENT)))
    return [
        PartyVote(
            party=p,
            party_name=names[p],
            for_votes=counts[(p, FOR)],
            against_votes=counts[(p, AGAINST)],
            absent=counts[(p, ABSENT)],
        )
        for p in parties
    ]


async def case(ctx: Context, args: CaseInput) -> Result[CaseOutput]:
    up = ctx.upstream(SPEC.id)
    try:
        detail, votes = await asyncio.gather(
            _get(up, "sak", "case", sakid=args.case_id),
            _get(up, "voteringer", "case", sakid=args.case_id),
        )
    except ToolError as exc:
        # Stortinget answers an unknown case id with HTTP 500 rather than 404.
        if exc.body.upstream_status != 500:
            raise
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Stortinget could not return case {args.case_id}. The id probably does not exist "
            "(Stortinget answers unknown ids with an error); case ids come from parliament_cases.",
            next_call=NextCall(tool="parliament_cases", arguments={}),
            source_id=SPEC.id,
            upstream_status=500,
        ) from None
    body = detail.json or {}
    if not body.get("id"):
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Stortinget has no case {args.case_id}. Case ids come from parliament_cases.",
            next_call=NextCall(tool="parliament_cases", arguments={}),
            source_id=SPEC.id,
        )

    provenance = [
        up.provenance(detail, title=f"Stortinget case {args.case_id}"),
        up.provenance(votes, title=f"Stortinget votes on case {args.case_id}"),
    ]
    vote_items = votes.json.get("sak_votering_liste") or []
    named = [v for v in vote_items if v.get("personlig_votering")] if args.party_breakdown else []
    results: dict[int, Fetched] = {}
    if named:
        fetched = await asyncio.gather(
            *(_get(up, "voteringsresultat", "case", voteringid=v["votering_id"]) for v in named)
        )
        results = {v["votering_id"]: f for v, f in zip(named, fetched, strict=True)}
        provenance.extend(
            up.provenance(f, title=f"Stortinget vote {vid}, by representative")
            for vid, f in results.items()
        )

    def counted(value: Any) -> int | None:
        return value if isinstance(value, int) and value >= 0 else None

    vote_rows = [
        Vote(
            id=v["votering_id"],
            topic=v.get("votering_tema"),
            time=_date(v.get("votering_tid")),
            adopted=v.get("vedtatt"),
            recorded_by_name=bool(v.get("personlig_votering")),
            for_count=counted(v.get("antall_for")),
            against_count=counted(v.get("antall_mot")),
            absent_count=counted(v.get("antall_ikke_tilstede")),
            result_note=v.get("votering_resultat_type_tekst"),
            parties=_parties(results[v["votering_id"]].json.get("voteringsresultat_liste") or [])
            if v["votering_id"] in results
            else [],
        )
        for v in vote_items
    ]
    publications = body.get("publikasjon_referanse_liste") or []
    notes = [*detail.notes, *votes.notes]
    if not vote_rows:
        notes.append("Stortinget has not voted on this case, or its votes are not published yet.")
    elif not any(v.for_count is not None for v in vote_rows):
        notes.append("The votes were not counted: decided without a recorded division.")
    return Result(
        data=CaseOutput(
            id=body["id"],
            title=body.get("tittel") or "",
            short_title=body.get("korttittel"),
            type=CASE_TYPES.get(body.get("type"), str(body.get("type"))),
            status=STATUS.get(body.get("status"), str(body.get("status"))),
            document_group=DOCUMENT_GROUPS.get(body.get("dokumentgruppe"), "unspecified"),
            reference=body.get("henvisning")
            or ", ".join(p.get("lenke_tekst") for p in publications if p.get("lenke_tekst"))
            or None,
            committee=_committee(body.get("komite")),
            rapporteurs=[_person(p) for p in body.get("saksordfoerer_liste") or []],
            topics=[t.get("navn") for t in body.get("emne_liste") or [] if t.get("navn")],
            decision=body.get("kortvedtak") or body.get("vedtakstekst"),
            recommendation=body.get("innstillingstekst"),
            votes=vote_rows,
            page_url=CASE_PAGE.format(id=body["id"]),
        ),
        provenance=provenance,
        notes=notes,
    )


# --- parliament_members ------------------------------------------------------------


async def members(ctx: Context, args: MembersInput) -> Result[MembersOutput]:
    up = ctx.upstream(SPEC.id)
    if args.period:
        fetched = await _get(up, "representanter", "people", stortingsperiodeid=args.period)
        items = fetched.json.get("representanter_liste") or []
    else:
        fetched = await _get(up, "dagensrepresentanter", "people")
        items = fetched.json.get("dagensrepresentanter_liste") or []
    if args.period and not items:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"No members for period {args.period}. Periods are four years, e.g. '2021-2025'.",
            source_id=SPEC.id,
        )

    rows: list[Member] = []
    for p in items:
        party = p.get("parti") or {}
        county = p.get("fylke") or {}
        member = Member(
            id=p["id"],
            name=f"{p.get('fornavn', '')} {p.get('etternavn', '')}".strip(),
            party=party.get("id"),
            party_name=party.get("navn"),
            constituency=county.get("navn"),
            committees=[c.get("navn") for c in p.get("komiteer_liste") or [] if c.get("navn")],
            substitute=bool(p.get("vara_representant")),
        )
        if args.party and (member.party or "").lower() != args.party.lower():
            continue
        if args.constituency and (member.constituency or "").lower() != args.constituency.lower():
            continue
        rows.append(member)
    rows.sort(key=lambda m: (m.party or "", m.name))
    by_party = dict(Counter(m.party or "?" for m in rows).most_common())
    notes = list(fetched.notes)
    if not rows:
        notes.append("No member matched. Party ids are short, e.g. 'A', 'H', 'FrP', 'SV'.")
    return Result(
        data=MembersOutput(period=args.period, count=len(rows), by_party=by_party, members=rows),
        provenance=[up.provenance(fetched, title="Stortinget members")],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="parliament_cases",
        title="Search Stortinget's cases",
        description=(
            "Cases before the Norwegian parliament in a session (by default the current one): "
            "bills, budgets, members' proposals and more, filtered by words in the title, type, "
            "status or committee. Titles are in Norwegian. Use parliament_case for the decision "
            "and how the parties voted."
        ),
        input_model=CasesInput,
        output_model=CasesOutput,
        handler=cases,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/parliament/cases",
        examples=({"query": "energipriser", "session": "2025-2026"}, {"type": "law", "limit": 5}),
    ),
    Operation(
        name="parliament_case",
        title="A Stortinget case and its votes",
        description=(
            "One case in the Norwegian parliament: title, committee, rapporteurs, the decision, "
            "and every vote on it with the result, the counts, and how each party voted when "
            "votes were recorded by name."
        ),
        input_model=CaseInput,
        output_model=CaseOutput,
        handler=case,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/parliament/cases/{case_id}",
        examples=({"case_id": 200084},),
    ),
    Operation(
        name="parliament_members",
        title="Members of Stortinget",
        description=(
            "The members of the Norwegian parliament sitting today, or for an electoral period: "
            "party, constituency and committees, with a count per party. Filter by party or "
            "constituency."
        ),
        input_model=MembersInput,
        output_model=MembersOutput,
        handler=members,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/parliament/members",
        examples=({}, {"period": "2021-2025", "party": "SV"}),
    ),
)
