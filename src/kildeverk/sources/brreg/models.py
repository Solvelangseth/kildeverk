from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def _org_number_ok(value: str) -> bool:
    """Organisation numbers carry a modulus-11 check digit."""

    weights = (3, 2, 7, 6, 5, 4, 3, 2)
    remainder = sum(int(d) * w for d, w in zip(value[:8], weights, strict=True)) % 11
    check = 0 if remainder == 0 else 11 - remainder
    return check != 10 and check == int(value[8])


def _org_number(value: object) -> object:
    if isinstance(value, str):
        value = value.replace(" ", "")
        if len(value) == 9 and value.isdigit() and not _org_number_ok(value):
            raise ValueError("not a valid organisation number (the check digit does not match)")
    return value


def _comma_list(value: object) -> object:
    # REST query strings arrive as one comma-separated string; MCP sends a list.
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


OrgNumber = Annotated[
    str,
    BeforeValidator(_org_number),
    Field(pattern=r"^\d{9}$", description="Nine-digit organisation number, e.g. '923609016'."),
]
CodeList = Annotated[list[str] | None, BeforeValidator(_comma_list)]


class Coded(BaseModel):
    code: str
    description: str | None


class Address(BaseModel):
    lines: list[str]
    postcode: str | None
    place: str | None
    municipality_code: str | None
    municipality: str | None
    country_code: str | None


# --- companies_search -------------------------------------------------------------


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None, min_length=1, max_length=180, description="Words in the entity's name."
    )
    municipality: CodeList = Field(
        default=None,
        description="Municipality codes (4 digits) or names, matched on business or postal "
        "address. Names are resolved to today's codes.",
        max_length=50,
    )
    industry: CodeList = Field(
        default=None,
        description="Industry codes (SN2025, the Norwegian NACE), or their leading digits: "
        "'62' finds all IT services, '62.200' one class. Matches any of an entity's up to "
        "three industry codes, not only its main one.",
        max_length=50,
    )
    legal_form: CodeList = Field(
        default=None,
        description="Legal form codes, e.g. AS (limited company), ASA (public limited), "
        "ENK (sole proprietorship), STI (foundation), FLI (association).",
        max_length=20,
    )
    min_employees: int | None = Field(
        default=None,
        ge=0,
        description="At least this many employees. Brreg accepts 0, 1, or 5 and above.",
    )
    registered_from: dt.date | None = Field(
        default=None, description="Registered in the Central Coordinating Register on or after."
    )
    registered_to: dt.date | None = Field(default=None, description="Registered on or before.")
    include_bankrupt: bool = Field(default=False, description="Also return bankrupt entities.")
    sort: Literal["default", "most_employees", "newest"] = "default"
    limit: int = Field(default=20, ge=1, le=100)
    page: int = Field(default=0, ge=0, description="Page number, starting at 0.")

    @field_validator("min_employees")
    @classmethod
    def _brreg_buckets(cls, value: int | None) -> int | None:
        if value is not None and 1 < value < 5:
            raise ValueError("Brreg only filters on 0, 1, or 5 and above")
        return value

    @field_validator("municipality")
    @classmethod
    def _four_digits(cls, value: list[str] | None) -> list[str] | None:
        if value and not all(
            (code.isdigit() and len(code) == 4) or not code[:1].isdigit() for code in value
        ):
            raise ValueError("municipality codes have 4 digits, e.g. '0301'; names work too")
        return value


class CompanySummary(BaseModel):
    org_number: str
    name: str
    legal_form: Coded | None
    industry: Coded | None = Field(description="Main industry (SN2025).")
    municipality: Coded | None = Field(
        description="From the business address, else the postal address."
    )
    employees: int | None = Field(description="Null when not reported (often for small entities).")
    registered_on: dt.date | None
    bankrupt: bool
    being_wound_up: bool
    deleted_on: dt.date | None = None


class SearchOutput(BaseModel):
    total_matches: int
    page: int
    total_pages: int
    companies: list[CompanySummary]


# --- companies_get ----------------------------------------------------------------


class GetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_number: OrgNumber
    include_subunits: bool = Field(
        default=False, description="Also list the entity's establishments (sub-units)."
    )
    subunits_limit: int = Field(default=20, ge=1, le=100)


class Registers(BaseModel):
    business_register: bool = Field(description="Foretaksregisteret.")
    vat_register: bool = Field(description="Merverdiavgiftsregisteret.")
    voluntary_organisations: bool = Field(description="Frivillighetsregisteret.")
    foundations: bool = Field(description="Stiftelsesregisteret.")
    political_parties: bool = Field(description="Partiregisteret.")


class Capital(BaseModel):
    amount: float | None
    currency: str | None
    kind: str | None
    shares: int | None


class FormerName(BaseModel):
    name: str
    from_: dt.date | None = Field(alias="from")
    to: dt.date | None

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class Subunit(BaseModel):
    org_number: str
    name: str
    municipality: Coded | None
    employees: int | None
    started_on: dt.date | None
    closed_on: dt.date | None


class Subunits(BaseModel):
    total: int
    items: list[Subunit]


class Company(CompanySummary):
    kind: Literal["main_unit", "subunit"]
    parent_org_number: str | None = Field(
        description="For a sub-unit, its main unit; for a public body, the body above it."
    )
    industries: list[Coded]
    sector: Coded | None
    business_address: Address | None
    postal_address: Address | None
    website: str | None
    founded_on: dt.date | None
    purpose: str | None
    activity: str | None
    registers: Registers | None
    share_capital: Capital | None
    part_of_group: bool | None
    last_annual_accounts: str | None
    former_names: list[FormerName]
    register_page: str
    subunits: Subunits | None = None
