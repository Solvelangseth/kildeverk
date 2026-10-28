"""Schools from Udir's National School Register (NSR)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.udir_nsr.spec import BASE_URL, SPEC

OrgNumber = Field(
    pattern=r"^[0-9U]\d{8}$",
    description="The school's organisation number, from schools_search.",
)


def _levels(item: dict[str, Any]) -> list[str]:
    levels = []
    if item.get("ErGrunnskole"):
        levels.append("primary")
    if item.get("ErVideregaaendeSkole"):
        levels.append("secondary")
    return levels


def _ownership(item: dict[str, Any]) -> str | None:
    if item.get("ErPrivatskole"):
        return "private"
    if item.get("ErOffentligSkole"):
        return "public"
    return None


# --- schools_search ----------------------------------------------------------------


class SchoolsSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=80)
    municipality: str | None = Field(default=None, pattern=r"^\d{4}$")
    county: str | None = Field(default=None, pattern=r"^\d{2}$")
    level: Literal["primary", "secondary"] | None = Field(
        default=None,
        description="'primary' for grunnskole (years 1-10), 'secondary' for videregående.",
    )
    ownership: Literal["public", "private"] | None = None
    include_closed: bool = False
    limit: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="after")
    def _some_filter(self) -> SchoolsSearchInput:
        if not any([self.name, self.municipality, self.county]):
            raise ValueError("give name, municipality or county")
        return self


class SchoolSummary(BaseModel):
    org_number: str
    name: str
    municipality_code: str | None
    county_code: str | None
    levels: list[str]
    ownership: str | None
    special_school: bool
    active: bool
    categories: list[str] = Field(description="NSR's categories, in Norwegian.")


class SchoolsSearchOutput(BaseModel):
    total_matches: int
    schools: list[SchoolSummary]


async def schools_search(ctx: Context, args: SchoolsSearchInput) -> Result[SchoolsSearchOutput]:
    up = ctx.upstream(SPEC.id)
    body: dict[str, Any] = {
        "InkluderSkoler": True,
        "InkluderEiere": False,
        "InkluderAndreEnheter": False,
        "InkluderAktive": True,
        "InkluderNedlagte": args.include_closed,
    }
    if args.name:
        body["FritekstSoek"] = args.name
    if args.municipality:
        body["Kommunenummer"] = args.municipality
    if args.county:
        body["Fylkesnummer"] = args.county
    try:
        fetched = await up.post_json(f"{BASE_URL}/enheter/sok", body=body, ttl="search")
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"The school register rejected the search: {exc.detail}",
            source_id=SPEC.id,
            upstream_status=exc.status,
        ) from None

    schools = []
    for item in fetched.json.get("EnhetListe") or []:
        if not item.get("ErSkole"):
            continue
        school = SchoolSummary(
            org_number=item["Organisasjonsnummer"],
            name=item.get("Navn") or item["Organisasjonsnummer"],
            municipality_code=item.get("Kommunenummer"),
            county_code=item.get("Fylkesnummer"),
            levels=_levels(item),
            ownership=_ownership(item),
            special_school=bool(item.get("ErSpesialskole")),
            active=bool(item.get("ErAktiv")),
            categories=[c["Navn"] for c in item.get("Skolekategorier") or [] if c.get("Navn")],
        )
        if args.level and args.level not in school.levels:
            continue
        if args.ownership and school.ownership != args.ownership:
            continue
        schools.append(school)
    schools.sort(key=lambda s: (not s.active, s.name))

    notes = list(fetched.notes)
    if not schools:
        notes.append("No school matched. Try part of the name, or fewer filters.")
    elif len(schools) > args.limit:
        notes.append(f"{len(schools)} schools matched; the first {args.limit} are included.")
    notes.append("Pupil numbers, grades and address are in schools_get.")
    return Result(
        data=SchoolsSearchOutput(total_matches=len(schools), schools=schools[: args.limit]),
        provenance=[up.provenance(fetched, title="National School Register search")],
        notes=notes,
        truncated=len(schools) > args.limit,
    )


# --- schools_get -------------------------------------------------------------------


class SchoolGetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_number: str = OrgNumber


class School(BaseModel):
    org_number: str
    name: str
    full_name: str | None
    municipality_code: str | None
    municipality: str | None
    county_code: str | None
    county: str | None
    levels: list[str]
    ownership: str | None
    owner: str | None = Field(description="The school owner, e.g. the municipality.")
    special_school: bool
    active: bool
    pupils: int | None
    staff: str | None = Field(description="As the register gives it, often a range.")
    grades: str | None = Field(description="e.g. '1-7' or 'Vg1-Vg3'.")
    language_form: str | None = Field(description="Bokmål or Nynorsk.")
    address: str | None
    lat: float | None
    lon: float | None
    website: str | None
    founded: dt.date | None
    closed: dt.date | None
    categories: list[str]
    industry_codes: list[str]


def _date(value: Any) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(value).date() if value else None
    except (TypeError, ValueError):
        return None


def _grades(item: dict[str, Any]) -> str | None:
    gs = item.get("SkoletrinnGSFra"), item.get("SkoletrinnGSTil")
    vgs = item.get("SkoletrinnVGSFra"), item.get("SkoletrinnVGSTil")
    parts = []
    if gs[0] is not None and gs[1] is not None and gs[1]:
        parts.append(f"{gs[0]}-{gs[1]}")
    if vgs[0] is not None and vgs[1] is not None and vgs[1]:
        parts.append(f"Vg{vgs[0]}-Vg{vgs[1]}")
    return ", ".join(parts) or None


def _address(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    street = value.get("Adress") or value.get("Adresse")
    place = " ".join(
        p for p in (value.get("Postnr") or value.get("Postnummer"), value.get("Poststed")) if p
    )
    return ", ".join(p for p in (street, place) if p) or None


async def schools_get(ctx: Context, args: SchoolGetInput) -> Result[School]:
    up = ctx.upstream(SPEC.id)
    try:
        fetched = await up.get_json(f"{BASE_URL}/enhet/{args.org_number}", ttl="school")
    except UpstreamClientError as exc:
        if exc.status not in (400, 404):
            raise
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"The school register has no unit {args.org_number}.",
            next_call=NextCall(tool="schools_search", arguments={"name": "skole", "county": "03"}),
            source_id=SPEC.id,
            upstream_status=exc.status,
        ) from None
    item = fetched.json or {}
    municipality = item.get("Kommune") or {}
    county = item.get("Fylke") or {}
    coordinate = item.get("Koordinat") or {}
    owners = [
        (r.get("Enhet") or {}).get("Navn")
        for r in item.get("ForeldreRelasjoner") or []
        if (r.get("Enhet") or {}).get("Navn")
    ]
    staff = item.get("AntallAnsatte")
    notes = list(fetched.notes)
    if not item.get("ErSkole"):
        notes.append("This unit is in the register but is not itself a school (e.g. an owner).")
    return Result(
        data=School(
            org_number=item.get("Organisasjonsnummer") or args.org_number,
            name=item.get("Navn") or args.org_number,
            full_name=item.get("FulltNavn"),
            municipality_code=municipality.get("Kommunenummer"),
            municipality=municipality.get("Navn"),
            county_code=county.get("Fylkesnummer"),
            county=county.get("Navn"),
            levels=_levels(item),
            ownership=_ownership(item),
            owner=owners[0] if owners else None,
            special_school=bool(item.get("ErSpesialskole")),
            active=bool(item.get("ErAktiv")),
            pupils=item.get("Elevtall"),
            staff=str(staff) if staff not in (None, "") else None,
            grades=_grades(item),
            language_form=(item.get("Maalform") or {}).get("Navn"),
            address=_address(item.get("Beliggenhetsadresse")),
            lat=coordinate.get("Breddegrad"),
            lon=coordinate.get("Lengdegrad"),
            website=item.get("Internettadresse"),
            founded=_date(item.get("OppstartsEllerStiftelsesdato")),
            closed=_date(item.get("UtgaattDato")),
            categories=[c["Navn"] for c in item.get("Skolekategorier") or [] if c.get("Navn")],
            industry_codes=[
                f"{c['Kode']} {c.get('Navn', '')}".strip()
                for c in item.get("Naeringskoder") or []
                if c.get("Kode")
            ],
        ),
        provenance=[up.provenance(fetched, title=f"National School Register, {args.org_number}")],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="schools_search",
        title="Find schools",
        description=(
            "Find Norwegian primary and secondary schools, public and private, in Udir's National "
            "School Register, by name, municipality or county, optionally only one level or kind "
            "of ownership. Use schools_get for pupil numbers, grades and address."
        ),
        input_model=SchoolsSearchInput,
        output_model=SchoolsSearchOutput,
        handler=schools_search,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/schools",
        examples=(
            {"municipality": "4601", "level": "secondary"},
            {"name": "Alvøen"},
        ),
    ),
    Operation(
        name="schools_get",
        title="One school",
        description=(
            "One school from the National School Register: pupils, staff, grades, owner, "
            "Bokmål or Nynorsk, address, position, website, and when it opened or closed."
        ),
        input_model=SchoolGetInput,
        output_model=School,
        handler=schools_get,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/schools/{org_number}",
        examples=({"org_number": "874738352"},),
    ),
)
