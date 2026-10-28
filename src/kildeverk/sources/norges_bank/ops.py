"""Exchange rates and the policy rate from Norges Bank's SDMX API."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import Fetched, UpstreamClientError
from kildeverk.sources.norges_bank.models import (
    FREQUENCIES,
    ExchangeRate,
    ExchangeRatesInput,
    ExchangeRatesOutput,
    PolicyRateInput,
    PolicyRateOutput,
    RateChange,
)
from kildeverk.sources.norges_bank.spec import BASE_URL, SPEC

STALE_AFTER = dt.timedelta(days=60)


def _series(
    json: dict[str, Any],
) -> Iterator[tuple[dict[str, str], dict[str, str], list[tuple[str, str]]]]:
    """Each series in an SDMX-JSON message: its dimension values, attributes and observations.

    Dimension and attribute values are given by position into the structure's value lists,
    and observations by position into the time dimension.
    """

    data = json.get("data") or {}
    structure = data.get("structure") or {}
    dims = structure.get("dimensions", {}).get("series") or []
    times = (structure.get("dimensions", {}).get("observation") or [{}])[0].get("values") or []
    attrs = structure.get("attributes", {}).get("series") or []
    for dataset in data.get("dataSets") or []:
        for key, series in (dataset.get("series") or {}).items():
            positions = [int(p) for p in key.split(":")]
            values = {d["id"]: d["values"][p]["id"] for d, p in zip(dims, positions, strict=False)}
            values |= {
                f"{d['id']}_name": d["values"][p].get("name", "")
                for d, p in zip(dims, positions, strict=False)
            }
            attributes = {
                a["id"]: a["values"][p]["id"]
                for a, p in zip(attrs, series.get("attributes") or [], strict=False)
                if p is not None and p < len(a["values"])
            }
            observations = sorted(
                (times[int(i)]["id"], obs[0])
                for i, obs in (series.get("observations") or {}).items()
                if obs and obs[0] not in (None, "", "NaN")
            )
            yield values, attributes, observations


async def _known_currencies(ctx: Context) -> list[str]:
    fetched = await ctx.upstream(SPEC.id).get_json(
        f"{BASE_URL}/EXR/B..NOK.SP",
        params={"format": "sdmx-json", "lastNObservations": 1, "detail": "serieskeysonly"},
        ttl="currencies",
    )
    dims = fetched.json["data"]["structure"]["dimensions"]["series"]
    base = next(d for d in dims if d["id"] == "BASE_CUR")
    return sorted(v["id"] for v in base["values"])


def _ttl(end: dt.date | None) -> str:
    return "historic" if end and end < dt.date.today() - dt.timedelta(days=2) else "recent"


# --- currency_exchange_rates -------------------------------------------------------


async def exchange_rates(ctx: Context, args: ExchangeRatesInput) -> Result[ExchangeRatesOutput]:
    up = ctx.upstream(SPEC.id)
    wanted = list(dict.fromkeys(args.currencies))
    key = f"{FREQUENCIES[args.frequency]}.{'+'.join(wanted)}.NOK.SP"
    params: dict[str, Any] = {"format": "sdmx-json", "locale": "en"}
    if args.start is None:
        params["lastNObservations"] = 1
    else:
        params["startPeriod"] = args.start.isoformat()
        if args.end:
            params["endPeriod"] = args.end.isoformat()
    try:
        fetched = await up.get_json(f"{BASE_URL}/EXR/{key}", params=params, ttl=_ttl(args.end))
    except UpstreamClientError as exc:
        if exc.status != 404:
            raise
        known = await _known_currencies(ctx)
        unknown = [c for c in wanted if c not in known]
        if unknown:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"Norges Bank publishes no rate for {', '.join(unknown)}. "
                f"It publishes: {', '.join(known)}.",
                source_id=SPEC.id,
                upstream_status=404,
            ) from None
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Norges Bank has no {args.frequency} rates for {', '.join(wanted)} in this period.",
            next_call=NextCall(
                tool="currency_exchange_rates",
                arguments={"currencies": wanted, "frequency": args.frequency},
            ),
            source_id=SPEC.id,
            upstream_status=404,
        ) from None

    rows: list[ExchangeRate] = []
    found: dict[str, str] = {}
    truncated = False
    for dims, attrs, observations in _series(fetched.json):
        per = 10 ** int(attrs.get("UNIT_MULT", "0"))
        currency = dims["BASE_CUR"]
        for period, value in observations:
            if len(rows) >= args.max_rows:
                truncated = True
                break
            nok = float(value)
            rows.append(
                ExchangeRate(
                    currency=currency,
                    currency_name=dims.get("BASE_CUR_name") or currency,
                    period=period,
                    nok=nok,
                    per=per,
                    nok_per_unit=round(nok / per, 8),
                )
            )
            found[currency] = max(found.get(currency, ""), period)
    order = {c: i for i, c in enumerate(wanted)}
    rows.sort(key=lambda r: (order.get(r.currency, 99), r.period))

    notes = list(fetched.notes)
    missing = [c for c in wanted if c not in found]
    if missing:
        notes.append(
            f"No rates for {', '.join(missing)}; check the codes against Norges Bank's list."
        )
    if any(r.per != 1 for r in rows):
        notes.append("Some currencies are quoted per 100 units; nok_per_unit is per one unit.")
    if args.frequency == "daily" and args.start is None:
        today = dt.date.today()
        for currency, period in found.items():
            if today - dt.date.fromisoformat(period) > STALE_AFTER:
                notes.append(
                    f"{currency} was last quoted on {period}; Norges Bank no longer publishes it."
                )
    if truncated:
        notes.append(f"Only the first {args.max_rows} rates are included.")
    return Result(
        data=ExchangeRatesOutput(frequency=args.frequency, row_count=len(rows), rows=rows),
        provenance=[up.provenance(fetched, title=f"Norges Bank exchange rates ({args.frequency})")],
        notes=notes,
        truncated=truncated,
    )


# --- rates_policy_rate -------------------------------------------------------------


async def policy_rate(ctx: Context, args: PolicyRateInput) -> Result[PolicyRateOutput]:
    up = ctx.upstream(SPEC.id)
    params = {"format": "sdmx-json", "locale": "en", "startPeriod": args.since.isoformat()}
    try:
        fetched: Fetched = await up.get_json(
            f"{BASE_URL}/IR/B.KPRA.SD.R", params=params, ttl="recent"
        )
    except UpstreamClientError as exc:
        if exc.status != 404:
            raise
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"No policy rate data since {args.since}.",
            source_id=SPEC.id,
            upstream_status=404,
        ) from None

    observations = next((obs for _, _, obs in _series(fetched.json)), [])
    if not observations:
        raise ToolError(
            ErrorCode.UPSTREAM_CHANGED,
            "Norges Bank returned no policy rate observations.",
            source_id=SPEC.id,
        )
    changes: list[RateChange] = []
    previous: float | None = None
    for period, value in observations:
        rate = float(value)
        if rate != previous:
            if previous is not None:
                changes.append(
                    RateChange(
                        effective=dt.date.fromisoformat(period),
                        rate=rate,
                        change_pp=round(rate - previous, 4),
                    )
                )
            previous = rate
    as_of, current = observations[-1]
    notes = list(fetched.notes)
    if not changes:
        notes.append(f"The rate has not changed since {args.since} or earlier.")
    return Result(
        data=PolicyRateOutput(
            rate=float(current),
            as_of=dt.date.fromisoformat(as_of),
            unchanged_since=changes[-1].effective if changes else None,
            changes=changes,
        ),
        provenance=[up.provenance(fetched, title="Norges Bank key policy rate")],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="currency_exchange_rates",
        title="Exchange rates against the krone",
        description=(
            "Norges Bank's exchange rates: how many kroner one unit of a currency costs, for about "
            "40 currencies and the krone's trade-weighted indices. Daily (business days) or as "
            "monthly or annual averages; leave out start for the latest rate."
        ),
        input_model=ExchangeRatesInput,
        output_model=ExchangeRatesOutput,
        handler=exchange_rates,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/currency/rates",
        examples=(
            {},
            {
                "currencies": ["EUR"],
                "frequency": "monthly",
                "start": "2025-01-01",
                "end": "2025-12-31",
            },
        ),
    ),
    Operation(
        name="rates_policy_rate",
        title="Norges Bank's key policy rate",
        description=(
            "The key policy rate set by Norges Bank: its level now, when it took effect, and every "
            "change since a given date (by default the last five years)."
        ),
        input_model=PolicyRateInput,
        output_model=PolicyRateOutput,
        handler=policy_rate,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/rates/policy",
        examples=({}, {"since": "2008-01-01"}),
    ),
)
