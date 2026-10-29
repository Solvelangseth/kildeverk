"""Company tools backed by the Central Coordinating Register for Legal Entities (Enhetsregisteret)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import Fetched, Upstream, UpstreamClientError
from kildeverk.sources.brreg.models import (
    Address,
    Capital,
    Coded,
    Company,
    CompanySummary,
    FormerName,
    GetInput,
    Registers,
    SearchInput,
    SearchOutput,
    Subunit,
    Subunits,
)
from kildeverk.sources.brreg.spec import (
    ACCEPT_SUBUNIT,
    ACCEPT_UNIT,
    BASE_URL,
    MAX_RESULT_WINDOW,
    REGISTER_PAGE,
    SPEC,
)
from kildeverk.sources.ssb_klass.names import with_region_names

SORTS = {
    "most_employees": "antallAnsatte,DESC",
    "newest": "registreringsdatoEnhetsregisteret,DESC",
}


def _upstream(ctx: Context) -> Upstream:
    return ctx.upstream(SPEC.id)


def _date(value: Any) -> dt.date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _coded(value: Any) -> Coded | None:
    if not isinstance(value, dict) or not value.get("kode"):
        return None
    return Coded(code=value["kode"], description=value.get("beskrivelse"))


def _address(value: Any) -> Address | None:
    if not isinstance(value, dict):
        return None
    return Address(
        lines=[line for line in value.get("adresse") or [] if line],
        postcode=value.get("postnummer"),
        place=value.get("poststed"),
        municipality_code=value.get("kommunenummer"),
        municipality=value.get("kommune"),
        country_code=value.get("landkode"),
    )


def _municipality(unit: dict[str, Any]) -> Coded | None:
    for field in ("forretningsadresse", "beliggenhetsadresse", "postadresse"):
        address = unit.get(field)
        if isinstance(address, dict) and address.get("kommunenummer"):
            return Coded(code=address["kommunenummer"], description=address.get("kommune"))
    return None


def _summary_fields(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "org_number": unit["organisasjonsnummer"],
        "name": unit.get("navn") or unit["organisasjonsnummer"],
        "legal_form": _coded(unit.get("organisasjonsform")),
        "industry": _coded(unit.get("naeringskode1")),
        "municipality": _municipality(unit),
        "employees": unit.get("antallAnsatte") if unit.get("harRegistrertAntallAnsatte") else None,
        "registered_on": _date(unit.get("registreringsdatoEnhetsregisteret")),
        "bankrupt": bool(unit.get("konkurs")),
        "being_wound_up": bool(
            unit.get("underAvvikling") or unit.get("underTvangsavviklingEllerTvangsopplosning")
        ),
        "deleted_on": _date(unit.get("slettedato")),
    }


# --- companies_search -------------------------------------------------------------


async def search(ctx: Context, args: SearchInput) -> Result[SearchOutput]:
    filters = [args.name, args.municipality, args.industry, args.legal_form]
    filters += [args.min_employees, args.registered_from, args.registered_to]
    if all(f is None or f == [] for f in filters):
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            "Give at least one filter: name, municipality, industry, legal_form, min_employees "
            "or a registration date. An unfiltered search would page through 1.2 million entities.",
            next_call=NextCall(tool="companies_search", arguments={"name": "equinor"}),
            source_id=SPEC.id,
        )
    if (args.page + 1) * args.limit > MAX_RESULT_WINDOW:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Brreg pages through at most {MAX_RESULT_WINDOW:,} results per search. "
            "Narrow the filters instead of paging further.",
            source_id=SPEC.id,
        )

    params: dict[str, Any] = {"size": args.limit, "page": args.page}
    if args.name:
        params["navn"] = args.name
    if args.municipality:
        params["kommunenummer"] = ",".join(args.municipality)
    if args.industry:
        params["naeringskode"] = ",".join(args.industry)
    if args.legal_form:
        params["organisasjonsform"] = ",".join(code.upper() for code in args.legal_form)
    if args.min_employees is not None:
        params["fraAntallAnsatte"] = args.min_employees
    if args.registered_from:
        params["fraRegistreringsdatoEnhetsregisteret"] = args.registered_from.isoformat()
    if args.registered_to:
        params["tilRegistreringsdatoEnhetsregisteret"] = args.registered_to.isoformat()
    if not args.include_bankrupt:
        params["konkurs"] = "false"
    if args.sort in SORTS:
        params["sort"] = SORTS[args.sort]

    up = _upstream(ctx)
    try:
        fetched = await up.get_json(
            f"{BASE_URL}/enheter", params=params, ttl="search", accept=ACCEPT_UNIT
        )
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Brreg rejected the search: {exc.detail}.",
            source_id=SPEC.id,
            upstream_status=exc.status,
        ) from None

    body = fetched.json
    page = body.get("page") or {}
    units = (body.get("_embedded") or {}).get("enheter") or []
    notes = list(fetched.notes)
    if not units and args.industry and any("." in code for code in args.industry):
        notes.append(
            "No match. Industry codes changed to SN2025 in 2025; try the two-digit division "
            "(e.g. '62') to catch both old and new class numbers."
        )
    return Result(
        data=SearchOutput(
            total_matches=page.get("totalElements", len(units)),
            page=page.get("number", args.page),
            total_pages=page.get("totalPages", 1),
            companies=[CompanySummary(**_summary_fields(unit)) for unit in units],
        ),
        provenance=[up.provenance(fetched, title="Enhetsregisteret search")],
        notes=notes,
    )


# --- companies_get ----------------------------------------------------------------


async def _lookup(up: Upstream, org_number: str) -> tuple[Fetched, str]:
    """The entity as a main unit, or failing that as a sub-unit."""

    for path, accept, kind in (
        ("enheter", ACCEPT_UNIT, "main_unit"),
        ("underenheter", ACCEPT_SUBUNIT, "subunit"),
    ):
        try:
            fetched = await up.get_json(
                f"{BASE_URL}/{path}/{org_number}", ttl="unit", accept=accept
            )
            return fetched, kind
        except UpstreamClientError as exc:
            if exc.status == 410:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"{org_number} has been withdrawn from Brreg's open data, for legal reasons. "
                    "It cannot be shown.",
                    source_id=SPEC.id,
                    upstream_status=410,
                ) from None
            if exc.status != 404:
                raise
    raise ToolError(
        ErrorCode.NOT_FOUND,
        f"No entity or sub-unit has organisation number {org_number}. Search by name with "
        "companies_search to find the right number.",
        source_id=SPEC.id,
        upstream_status=404,
    )


def _text(value: Any) -> str | None:
    if isinstance(value, list):
        value = " ".join(part.strip() for part in value if isinstance(part, str))
    return value.strip() or None if isinstance(value, str) else None


def _company(unit: dict[str, Any], kind: str) -> Company:
    capital = unit.get("kapital")
    accounts = unit.get("sisteInnsendteAarsregnskap")
    return Company(
        **_summary_fields(unit),
        kind=kind,  # type: ignore[arg-type]
        parent_org_number=unit.get("overordnetEnhet"),
        industries=[
            coded
            for coded in (_coded(unit.get(f"naeringskode{i}")) for i in (1, 2, 3))
            if coded is not None
        ],
        sector=_coded(unit.get("institusjonellSektorkode")),
        business_address=_address(
            unit.get("forretningsadresse") or unit.get("beliggenhetsadresse")
        ),
        postal_address=_address(unit.get("postadresse")),
        website=unit.get("hjemmeside"),
        founded_on=_date(unit.get("stiftelsesdato") or unit.get("oppstartsdato")),
        purpose=_text(unit.get("vedtektsfestetFormaal")),
        activity=_text(unit.get("aktivitet")),
        registers=Registers(
            business_register=bool(unit.get("registrertIForetaksregisteret")),
            vat_register=bool(unit.get("registrertIMvaregisteret")),
            voluntary_organisations=bool(unit.get("registrertIFrivillighetsregisteret")),
            foundations=bool(unit.get("registrertIStiftelsesregisteret")),
            political_parties=bool(unit.get("registrertIPartiregisteret")),
        )
        if kind == "main_unit"
        else None,
        share_capital=Capital(
            amount=capital.get("belop"),
            currency=capital.get("valuta"),
            kind=capital.get("type"),
            shares=capital.get("antallAksjer"),
        )
        if isinstance(capital, dict)
        else None,
        part_of_group=unit.get("erIKonsern"),
        last_annual_accounts=str(accounts) if accounts else None,
        former_names=[
            FormerName(name=n["navn"], from_=_date(n.get("fraDato")), to=_date(n.get("tilDato")))
            for n in unit.get("historiskeNavn") or []
            if n.get("navn")
        ],
        register_page=REGISTER_PAGE.format(org_number=unit["organisasjonsnummer"]),
    )


async def get(ctx: Context, args: GetInput) -> Result[Company]:
    up = _upstream(ctx)
    fetched, kind = await _lookup(up, args.org_number)
    company = _company(fetched.json, kind)
    provenance = [
        up.provenance(fetched, title=f"Enhetsregisteret, {company.name} ({company.org_number})")
    ]
    notes = list(fetched.notes)
    if company.deleted_on:
        notes.append(f"This entity was deleted from the register on {company.deleted_on}.")
    if company.last_annual_accounts:
        notes.append(
            f"Its last filed accounts are for {company.last_annual_accounts}; companies_accounts "
            "gives the key figures."
        )

    if args.include_subunits and kind == "main_unit":
        listed = await up.get_json(
            f"{BASE_URL}/underenheter",
            params={"overordnetEnhet": args.org_number, "size": args.subunits_limit},
            ttl="unit",
            accept=ACCEPT_SUBUNIT,
        )
        items = (listed.json.get("_embedded") or {}).get("underenheter") or []
        company.subunits = Subunits(
            total=(listed.json.get("page") or {}).get("totalElements", len(items)),
            items=[
                Subunit(
                    org_number=item["organisasjonsnummer"],
                    name=item.get("navn") or item["organisasjonsnummer"],
                    municipality=_municipality(item),
                    employees=item.get("antallAnsatte")
                    if item.get("harRegistrertAntallAnsatte")
                    else None,
                    started_on=_date(item.get("oppstartsdato")),
                    closed_on=_date(item.get("nedleggelsesdato")),
                )
                for item in items
            ],
        )
        provenance.append(
            up.provenance(listed, title=f"Enhetsregisteret, sub-units of {args.org_number}")
        )
        if company.subunits.total > len(items):
            notes.append(
                f"Showing {len(items)} of {company.subunits.total} sub-units; raise subunits_limit "
                "(up to 100) for more."
            )
    return Result(data=company, provenance=provenance, notes=notes)


OPERATIONS = (
    Operation(
        name="companies_search",
        title="Search Norwegian legal entities",
        description=(
            "Search the Central Coordinating Register for Legal Entities (Enhetsregisteret): "
            "companies, sole proprietorships, associations and public bodies. Filter by name, "
            "municipality, industry (SN2025 code or its leading digits), legal form, minimum "
            "employees and registration date. Bankrupt entities are excluded unless asked for."
        ),
        input_model=SearchInput,
        output_model=SearchOutput,
        handler=with_region_names({"municipality": "municipality"})(search),
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/companies",
        examples=(
            {"name": "equinor"},
            {"municipality": ["4601"], "industry": ["62"], "sort": "most_employees", "limit": 10},
        ),
    ),
    Operation(
        name="companies_get",
        title="Look up a legal entity",
        description=(
            "Get one entity by its nine-digit organisation number: name, legal form, industries, "
            "addresses, employees, share capital, register memberships, bankruptcy and "
            "liquidation status, former names, and optionally its sub-units. Works for sub-units "
            "too. Roles and contact details are not included; for revenue and results, use "
            "companies_accounts."
        ),
        input_model=GetInput,
        output_model=Company,
        handler=get,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/companies/{org_number}",
        examples=(
            {"org_number": "923609016"},
            {"org_number": "923609016", "include_subunits": True},
        ),
    ),
)
