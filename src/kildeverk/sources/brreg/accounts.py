"""Key figures from the annual accounts in Regnskapsregisteret, Brreg's open accounts API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.brreg.models import OrgNumber
from kildeverk.sources.brreg.spec import ACCOUNTS, ACCOUNTS_URL, REGISTER_PAGE

KINDS = {"SELSKAP": "company", "KONSERN": "group"}
RULES = {
    "regnskapslovenAlminneligRegler": "NGAAP",
    "IFRS": "IFRS",
    "forenkletAnvendelseIFRS": "simplified IFRS",
}


class AccountsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_number: OrgNumber
    kind: Literal["company", "group", "both"] = Field(
        default="both",
        description="'company' for the entity's own accounts, 'group' for a parent company's "
        "consolidated accounts.",
    )
    year: int | None = Field(
        default=None, ge=2000, le=2100, description="One year; leave out for all that are open."
    )


class Accounts(BaseModel):
    year: int = Field(description="The year the accounting period ends in.")
    kind: Literal["company", "group"]
    period_from: dt.date
    period_to: dt.date
    currency: str
    accounting_rules: str = Field(
        description="NGAAP (the Accounting Act), IFRS, or simplified IFRS."
    )
    small_company: bool | None
    audited: bool | None = Field(description="False when the company opted out of an audit.")
    liquidation_accounts: bool | None
    revenue: float | None = Field(description="Total operating income.")
    sales_revenue: float | None
    operating_costs: float | None
    salary_costs: float | None
    operating_profit: float | None
    net_financial: float | None = Field(description="Financial income minus financial costs.")
    profit_before_tax: float | None
    tax: float | None
    net_result: float | None = Field(description="Profit or loss for the year.")
    total_assets: float | None
    fixed_assets: float | None
    current_assets: float | None
    cash: float | None = Field(description="Bank deposits and cash.")
    equity: float | None
    debt: float | None
    short_term_debt: float | None
    long_term_debt: float | None
    operating_margin_pct: float | None = Field(description="Operating profit over revenue.")
    equity_ratio_pct: float | None = Field(description="Equity over total assets.")
    revenue_change_pct: float | None = Field(
        description="Change from the year before, for the same kind of accounts."
    )


class AccountsOutput(BaseModel):
    org_number: str
    legal_form: str | None
    parent_company: bool | None = Field(description="Whether it files group accounts as a parent.")
    accounts: list[Accounts] = Field(description="Newest first; group before company each year.")
    register_page: str


def _get(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _pct(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole:
        return None
    return round(part / whole * 100, 1)


def _accounts(item: dict[str, Any]) -> Accounts:
    result = item.get("resultatregnskapResultat") or {}
    assets = item.get("eiendeler") or {}
    liabilities = item.get("egenkapitalGjeld") or {}
    audit = item.get("revisjon") or {}
    # Brreg's own spelling: "regnkapsprinsipper".
    rules = item.get("regnkapsprinsipper") or item.get("regnskapsprinsipper") or {}
    revenue = _get(result, "driftsresultat", "driftsinntekter", "sumDriftsinntekter")
    operating = _get(result, "driftsresultat", "driftsresultat")
    total = assets.get("sumEiendeler")
    equity = _get(liabilities, "egenkapital", "sumEgenkapital")
    period_to = dt.date.fromisoformat(item["regnskapsperiode"]["tilDato"])
    audited = None
    if audit:
        audited = not (audit.get("fravalgRevisjon") or audit.get("ikkeRevidertAarsregnskap"))
    return Accounts(
        year=period_to.year,
        kind=KINDS.get(item.get("regnskapstype"), "company"),  # type: ignore[arg-type]
        period_from=dt.date.fromisoformat(item["regnskapsperiode"]["fraDato"]),
        period_to=period_to,
        currency=item.get("valuta") or "NOK",
        accounting_rules=RULES.get(
            rules.get("regnskapsregler"), rules.get("regnskapsregler") or ""
        ),
        small_company=rules.get("smaaForetak"),
        audited=audited,
        liquidation_accounts=item.get("avviklingsregnskap"),
        revenue=revenue,
        sales_revenue=_get(result, "driftsresultat", "driftsinntekter", "salgsinntekter"),
        operating_costs=_get(result, "driftsresultat", "driftskostnad", "sumDriftskostnad"),
        salary_costs=_get(result, "driftsresultat", "driftskostnad", "loennskostnad"),
        operating_profit=operating,
        net_financial=_get(result, "finansresultat", "nettoFinans"),
        profit_before_tax=result.get("ordinaertResultatFoerSkattekostnad"),
        tax=result.get("ordinaertResultatSkattekostnad"),
        net_result=result.get("aarsresultat"),
        total_assets=total,
        fixed_assets=_get(assets, "anleggsmidler", "sumAnleggsmidler"),
        current_assets=_get(assets, "omloepsmidler", "sumOmloepsmidler"),
        cash=assets.get("sumBankinnskuddOgKontanter"),
        equity=equity,
        debt=_get(liabilities, "gjeldOversikt", "sumGjeld"),
        short_term_debt=_get(liabilities, "gjeldOversikt", "kortsiktigGjeld", "sumKortsiktigGjeld"),
        long_term_debt=_get(liabilities, "gjeldOversikt", "langsiktigGjeld", "sumLangsiktigGjeld"),
        operating_margin_pct=_pct(operating, revenue),
        equity_ratio_pct=_pct(equity, total),
        revenue_change_pct=None,
    )


async def accounts(ctx: Context, args: AccountsInput) -> Result[AccountsOutput]:
    up = ctx.upstream(ACCOUNTS.id)
    params: dict[str, Any] = {}
    if args.kind != "both":
        params["regnskapstype"] = {"company": "SELSKAP", "group": "KONSERN"}[args.kind]
    if args.year is not None:
        params["år"] = args.year
    try:
        fetched = await up.get_json(
            f"{ACCOUNTS_URL}/{args.org_number}", params=params or None, ttl="accounts"
        )
    except UpstreamClientError as exc:
        if exc.status not in (400, 404):
            raise
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Regnskapsregisteret has no open accounts for {args.org_number}"
            + (f" for {args.year}" if args.year else "")
            + ". Public bodies, sole proprietorships and others that do not file accounts have "
            "none, and only the last three years are open.",
            next_call=NextCall(tool="companies_get", arguments={"org_number": args.org_number}),
            source_id=ACCOUNTS.id,
            upstream_status=exc.status,
        ) from None

    items = fetched.json if isinstance(fetched.json, list) else []
    rows = [_accounts(item) for item in items if _get(item, "regnskapsperiode", "tilDato")]
    rows.sort(key=lambda a: (a.year, a.kind == "group"), reverse=True)
    by_kind: dict[tuple[str, int], Accounts] = {(a.kind, a.year): a for a in rows}
    for row in rows:
        before = by_kind.get((row.kind, row.year - 1))
        if (
            before
            and before.revenue
            and row.revenue is not None
            and before.currency == row.currency
        ):
            row.revenue_change_pct = round(
                (row.revenue - before.revenue) / abs(before.revenue) * 100, 1
            )

    first = items[0] if items else {}
    notes = list(fetched.notes)
    if not rows:
        notes.append("No accounts match.")
    currencies = sorted({a.currency for a in rows})
    if currencies and currencies != ["NOK"]:
        notes.append(f"Amounts are in {', '.join(currencies)}, as the company reports them.")
    else:
        notes.append("Amounts are in NOK.")
    if any(a.kind == "group" for a in rows) and any(a.kind == "company" for a in rows):
        notes.append(
            "Group accounts include the subsidiaries; company accounts are the entity alone."
        )
    return Result(
        data=AccountsOutput(
            org_number=args.org_number,
            legal_form=_get(first, "virksomhet", "organisasjonsform"),
            parent_company=_get(first, "virksomhet", "morselskap"),
            accounts=rows,
            register_page=REGISTER_PAGE.format(org_number=args.org_number),
        ),
        provenance=[
            up.provenance(
                fetched, title=f"Regnskapsregisteret, annual accounts for {args.org_number}"
            )
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="companies_accounts",
        title="Annual accounts of a company",
        description=(
            "Key figures from the annual accounts a Norwegian company filed, from Brreg's "
            "Regnskapsregisteret, for the last three years: revenue, operating profit, profit "
            "before tax, tax, net result, assets, equity, debt and cash, with the operating "
            "margin, equity ratio and revenue change. Company accounts and, for parent "
            "companies, group accounts. Amounts are in the currency the company reports in."
        ),
        input_model=AccountsInput,
        output_model=AccountsOutput,
        handler=accounts,
        source_ids=(ACCOUNTS.id,),
        http_method="GET",
        http_path="/v1/companies/{org_number}/accounts",
        examples=(
            {"org_number": "923609016"},
            {"org_number": "983974899", "kind": "company", "year": 2025},
        ),
    ),
)
