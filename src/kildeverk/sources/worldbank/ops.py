"""Country indicators from the World Bank's World Development Indicators."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.sources.worldbank.spec import BASE_URL, SPEC, WDI_SOURCE

# Common indicators by a plain name; any WDI code works too.
ALIASES = {
    "gdp": "NY.GDP.MKTP.CD",
    "gdp_per_capita": "NY.GDP.PCAP.CD",
    "gdp_per_capita_ppp": "NY.GDP.PCAP.PP.CD",
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",
    "population": "SP.POP.TOTL",
    "life_expectancy": "SP.DYN.LE00.IN",
    "fertility_rate": "SP.DYN.TFRT.IN",
    "unemployment": "SL.UEM.TOTL.ZS",
    "inflation": "FP.CPI.TOTL.ZG",
    "co2_per_capita": "EN.GHG.CO2.PC.CE.AR5",
    "renewable_energy_share": "EG.FEC.RNEW.ZS",
    "internet_users": "IT.NET.USER.ZS",
    "government_debt": "GC.DOD.TOTL.GD.ZS",
    "gini": "SI.POV.GINI",
    "military_spending": "MS.MIL.XPND.GD.ZS",
    "research_spending": "GB.XPD.RSDV.GD.ZS",
    "education_spending": "SE.XPD.TOTL.GD.ZS",
    "health_spending": "SH.XPD.CHEX.GD.ZS",
}
NORDICS = ["NOR", "SWE", "DNK", "FIN", "ISL"]
CODE = re.compile(r"^[A-Z0-9]{2,3}$")
MAX_NOTE = 500


class IndicatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator: str = Field(
        min_length=2,
        max_length=40,
        description=f"A WDI code ('NY.GDP.PCAP.CD') or one of: {', '.join(ALIASES)}.",
    )
    countries: list[str] = Field(
        default=NORDICS,
        min_length=1,
        max_length=20,
        description="ISO country codes ('NOR', 'SE') or World Bank aggregates ('WLD' for the "
        "world, 'EUU' for the EU, 'OED' for the OECD). Default: the Nordic countries.",
    )
    from_year: int | None = Field(
        default=None, ge=1960, le=2100, description="Leave out both years for the latest value."
    )
    to_year: int | None = Field(default=None, ge=1960, le=2100)

    @model_validator(mode="after")
    def _check(self) -> IndicatorInput:
        self.countries = [c.strip().upper() for c in self.countries]
        bad = [c for c in self.countries if not CODE.match(c)]
        if bad:
            raise ValueError(f"not ISO country codes: {', '.join(bad)}")
        if self.from_year and self.to_year and self.to_year < self.from_year:
            raise ValueError("to_year must not be before from_year")
        return self


class Value(BaseModel):
    country_code: str
    country: str
    year: int
    value: float


class Ranked(BaseModel):
    rank: int
    country_code: str
    country: str
    year: int
    value: float


class IndicatorOutput(BaseModel):
    code: str
    name: str
    definition: str | None = Field(description="The World Bank's note, shortened.")
    source_organisation: str | None
    values: list[Value] = Field(description="By country as asked, then year.")
    latest: list[Ranked] = Field(description="Each country's latest value, highest first.")
    missing: list[str] = Field(description="Countries asked for with no value.")


async def indicator(ctx: Context, args: IndicatorInput) -> Result[IndicatorOutput]:
    code = ALIASES.get(args.indicator.strip().lower(), args.indicator.strip().upper())
    up = ctx.upstream(SPEC.id)
    params: dict[str, Any] = {"format": "json", "per_page": 1000}
    if args.from_year or args.to_year:
        params["date"] = f"{args.from_year or 1960}:{args.to_year or 2100}"
    else:
        # The most recent year with a value, per country.
        params["mrnev"] = 1
    countries = list(dict.fromkeys(args.countries))

    def fetch(codes: list[str]) -> Any:
        return up.get_json(
            f"{BASE_URL}/country/{';'.join(codes)}/indicator/{code}", params=params, ttl="data"
        )

    def records(fetched: Any) -> list[dict[str, Any]] | None:
        body = fetched.json
        if isinstance(body, list) and len(body) > 1 and isinstance(body[1], list):
            return body[1]
        return None

    meta, data = await asyncio.gather(
        up.get_json(f"{BASE_URL}/indicator/{code}", params={"format": "json"}, ttl="indicator"),
        fetch(countries),
    )
    fetches = [data]
    unknown: list[str] = []
    if records(data) is None and len(countries) > 1:
        # One unknown code fails the whole request, so ask country by country.
        fetches = list(await asyncio.gather(*(fetch([c]) for c in countries)))
        unknown = [c for c, f in zip(countries, fetches, strict=True) if records(f) is None]

    described = records(meta)
    if not described:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"The World Bank has no indicator '{args.indicator}'. Give a WDI code such as "
            f"'NY.GDP.PCAP.CD', or one of: {', '.join(ALIASES)}.",
            source_id=SPEC.id,
        )
    info = described[0]
    if (info.get("source") or {}).get("id") != WDI_SOURCE:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"{code} belongs to '{(info.get('source') or {}).get('value')}', not the World "
            "Development Indicators, and only WDI's licence (CC BY 4.0) is known here. Most "
            "archived indicators have a current WDI code; the common ones are listed under "
            "indicator.",
            next_call=NextCall(tool="world_indicators", arguments={"indicator": "co2_per_capita"})
            if "CO2" in code
            else None,
            source_id=SPEC.id,
        )
    rows = [r for f in fetches for r in records(f) or []]
    order = {c: i for i, c in enumerate(countries)}
    # Rows are ordered as asked, whichever code the country was asked by.
    for r in rows:
        for code_asked in (r["country"]["id"], r.get("countryiso3code")):
            if code_asked in order:
                order.setdefault(r.get("countryiso3code") or r["country"]["id"], order[code_asked])
    values = sorted(
        (
            Value(
                country_code=r.get("countryiso3code") or r["country"]["id"],
                country=r["country"]["value"],
                year=int(r["date"]),
                value=r["value"],
            )
            for r in rows
            if r.get("value") is not None and str(r.get("date", "")).isdigit()
        ),
        key=lambda v: (order.get(v.country_code, len(order)), v.year),
    )
    latest_by: dict[str, Value] = {}
    for v in values:
        if v.country_code not in latest_by or v.year > latest_by[v.country_code].year:
            latest_by[v.country_code] = v
    ranked = sorted(latest_by.values(), key=lambda v: v.value, reverse=True)
    # Asked as 'SE' or 'SWE', a country's rows carry both codes.
    iso3 = {r["country"]["id"]: r.get("countryiso3code") or r["country"]["id"] for r in rows}
    iso3 |= {v: v for v in iso3.values()}
    missing = [c for c in order if iso3.get(c, c) not in latest_by]
    notes = list(data.notes)
    if unknown:
        notes.append(f"Not World Bank country codes: {', '.join(unknown)}.")
    empty = [c for c in missing if c not in unknown]
    if empty:
        notes.append(f"No value for {', '.join(empty)} in this period.")
    if len({v.year for v in latest_by.values()}) > 1:
        notes.append("The latest year differs between countries; compare with care.")
    note = info.get("sourceNote") or None
    if note and len(note) > MAX_NOTE:
        note = note[: MAX_NOTE - 1].rstrip() + "…"
    return Result(
        data=IndicatorOutput(
            code=code,
            name=info.get("name") or code,
            definition=note,
            source_organisation=info.get("sourceOrganization") or None,
            values=values,
            latest=[
                Ranked(
                    rank=i,
                    country_code=v.country_code,
                    country=v.country,
                    year=v.year,
                    value=v.value,
                )
                for i, v in enumerate(ranked, start=1)
            ],
            missing=missing,
        ),
        provenance=[
            *(
                up.provenance(f, title=f"World Development Indicators: {info.get('name') or code}")
                for f in fetches
                if records(f) is not None
            ),
            up.provenance(meta, title=f"World Development Indicators: definition of {code}"),
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="world_indicators",
        title="Compare Norway with other countries",
        description=(
            "A World Bank World Development Indicator for Norway and other countries or regions: "
            "the latest value per country, ranked, or every year in a range. Use a WDI code or a "
            f"common name ({', '.join(list(ALIASES)[:8])}, …). By default the Nordic countries. "
            "For figures inside Norway, use SSB's statistics tools instead."
        ),
        input_model=IndicatorInput,
        output_model=IndicatorOutput,
        handler=indicator,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/world/indicators",
        examples=(
            {"indicator": "gdp_per_capita"},
            {
                "indicator": "SP.DYN.LE00.IN",
                "countries": ["NOR", "WLD", "EUU"],
                "from_year": 2015,
                "to_year": 2020,
            },
        ),
    ),
)
