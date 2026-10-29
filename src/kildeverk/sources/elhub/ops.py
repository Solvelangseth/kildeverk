"""Electricity consumption and production from Elhub, the national metering data hub."""

from __future__ import annotations

import asyncio
import datetime as dt
from collections import defaultdict
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import Fetched
from kildeverk.sources.elhub.spec import BASE_URL, SPEC
from kildeverk.sources.nve_reservoirs.ops import AREA_NAMES
from kildeverk.sources.ssb_klass.names import MUNICIPALITY_PATTERN

OSLO = ZoneInfo("Europe/Oslo")
FIRST_DAY = dt.date(2021, 1, 1)
MAX_DAYS = 31
MAX_HOURLY_DAYS = 3
# Price-area requests may span at most one calendar month; 28 days always fits.
CHUNK_DAYS = 28
KINDS = ("hydro", "wind", "solar", "thermal", "nuclear", "other")

GROUPS_NOTE = (
    "Consumption groups are Elhub's: private is homes and cabins, business is services (NACE "
    "sections G-U, and consumption with no industry code), industry is primary industry and "
    "industry (sections A-F)."
)
AREA_GROUPS_NOTE = (
    "Consumption groups are Elhub's: household, cabin, primary (agriculture, forestry, fishing), "
    "secondary (industry, NACE sections B-F) and tertiary (services, sections G-U, and "
    "consumption with no industry code)."
)


def _today() -> dt.date:
    return dt.datetime.now(OSLO).date()


def _window(first: dt.date, last: dt.date) -> dict[str, str]:
    """Elhub's dates are inclusive and in Norwegian time, with the offset spelled out."""

    return {
        "startDate": dt.datetime.combine(first, dt.time(0), OSLO).isoformat(),
        "endDate": dt.datetime.combine(last, dt.time(23, 59, 59), OSLO).isoformat(),
    }


def _ttl(last: dt.date) -> str:
    return "recent" if last >= _today() - dt.timedelta(days=3) else "past"


def _period(
    from_date: dt.date | None, to_date: dt.date | None, retry: tuple[str, dict[str, Any]]
) -> tuple[dt.date, dt.date, list[str]]:
    """The days asked for, by default the last seven full ones, checked against Elhub's limits."""

    today = _today()
    yesterday = today - dt.timedelta(days=1)
    if to_date is None:
        to_date = min(from_date + dt.timedelta(days=6), yesterday) if from_date else yesterday
    if from_date is None:
        from_date = to_date - dt.timedelta(days=6)
    tool, arguments = retry

    def invalid(message: str) -> ToolError:
        return ToolError(
            ErrorCode.INVALID_ARGUMENT, message, next_call=NextCall(tool=tool, arguments=arguments)
        )

    if to_date > today:
        raise invalid(f"to_date {to_date} is in the future; Elhub has figures up to yesterday.")
    if from_date > to_date:
        raise invalid("from_date must not be after to_date.")
    if from_date < FIRST_DAY:
        raise invalid("Elhub's figures start on 2021-01-01.")
    if (to_date - from_date).days + 1 > MAX_DAYS:
        raise invalid(
            f"Ask for at most {MAX_DAYS} days at a time; split a longer period into several calls."
        )
    notes = []
    if to_date == today:
        notes.append("Today is still being metered, so its figures are incomplete.")
    if to_date >= today - dt.timedelta(days=3):
        notes.append("The last few days may still be revised as late meter readings arrive.")
    return from_date, to_date, notes


def _days(first: dt.date, last: dt.date) -> list[dt.date]:
    return [first + dt.timedelta(days=n) for n in range((last - first).days + 1)]


def _attributes(fetched: Fetched) -> dict[str, Any] | None:
    """The one entity in a JSON:API answer; `data` is a list even when an id is given."""

    data = (fetched.json or {}).get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    return data.get("attributes") if isinstance(data, dict) else None


def _mwh(kwh: float) -> float:
    return round(kwh / 1000, 3)


def _updated(rows: list[dict[str, Any]], current: dt.datetime | None) -> dt.datetime | None:
    stamps = [
        dt.datetime.fromisoformat(r["lastUpdatedTime"]) for r in rows if r.get("lastUpdatedTime")
    ]
    return max([*stamps, *([current] if current else [])], default=None)


# --- electricity_municipality ------------------------------------------------------


class MunicipalityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    municipality: str = Field(
        min_length=2,
        max_length=60,
        pattern=MUNICIPALITY_PATTERN,
        description="A municipality code, old or current ('1201', '4601'), or a name ('Bergen').",
    )
    from_date: dt.date | None = Field(
        default=None,
        description="First day, in Norwegian time, from 2021-01-01. Leave out both dates for the "
        "last seven full days.",
    )
    to_date: dt.date | None = Field(
        default=None, description="Last day, inclusive; at most 31 days from from_date."
    )
    resolution: Literal["day", "hour"] = Field(
        default="day", description="'hour' adds every hour, for periods of up to 3 days."
    )


Group = Literal["private", "business", "industry"]


class GroupUse(BaseModel):
    group: Group
    mwh: float
    share_pct: float
    metering_points: int | None = Field(description="Metering points in the group, last count.")


class Use(BaseModel):
    total_mwh: float
    private_mwh: float
    business_mwh: float
    industry_mwh: float


class DayUse(Use):
    date: dt.date


class HourUse(Use):
    start: dt.datetime


class Capacity(BaseModel):
    kind: str = Field(description="hydro, wind, solar, thermal, other, or not_specified.")
    mw: float
    prosumer_mw: float = Field(
        description="The part on metering points that both use and produce, such as rooftop solar."
    )


class MunicipalityOutput(BaseModel):
    code: str
    name: str
    from_date: dt.date
    to_date: dt.date
    days_with_figures: int
    total_mwh: float
    average_mwh_per_day: float | None
    by_group: list[GroupUse] = Field(description="Largest first.")
    days: list[DayUse]
    hours: list[HourUse] = Field(description="Only with resolution 'hour'.")
    capacity_date: dt.date
    capacity_mw: float
    capacity: list[Capacity] = Field(description="Installed production capacity, largest first.")
    last_updated: dt.datetime | None = Field(description="When Elhub last revised any row used.")


def _use(groups: dict[str, float]) -> dict[str, float]:
    return {
        "total_mwh": _mwh(sum(groups.values())),
        "private_mwh": _mwh(groups.get("private", 0.0)),
        "business_mwh": _mwh(groups.get("business", 0.0)),
        "industry_mwh": _mwh(groups.get("industry", 0.0)),
    }


async def municipality_electricity(
    ctx: Context, args: MunicipalityInput
) -> Result[MunicipalityOutput]:
    from kildeverk.sources import composite  # late: composite reaches tools through the registry

    code, level, region_note = await composite._region_for_series(ctx, args.municipality)
    if level != "municipality":
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"'{args.municipality}' is a county, and this tool takes a municipality. For larger "
            "areas, ask for the electricity price areas.",
            next_call=NextCall(tool="electricity_price_areas", arguments={}),
        )
    first, last, notes = _period(
        args.from_date, args.to_date, ("electricity_municipality", {"municipality": code})
    )
    if args.resolution == "hour" and (last - first).days + 1 > MAX_HOURLY_DAYS:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"Hourly figures are given for at most {MAX_HOURLY_DAYS} days; ask for days instead, "
            "or a shorter period.",
            next_call=NextCall(
                tool="electricity_municipality",
                arguments={
                    "municipality": code,
                    "from_date": first.isoformat(),
                    "to_date": last.isoformat(),
                },
            ),
        )

    up = ctx.upstream(SPEC.id)
    url = f"{BASE_URL}/municipalities/{code}"
    days = _days(first, last)
    *consumption, capacity = await asyncio.gather(
        *(
            up.get_json(
                url,
                params={"dataset": "CONSUMPTION_PER_GROUP_MUNICIPALITY_HOUR", **_window(d, d)},
                ttl=_ttl(d),
            )
            for d in days
        ),
        up.get_json(
            url,
            params={
                "dataset": "INSTALLED_CAPACITY_PER_METERING_POINT_TYPE_GROUP_MUNICIPALITY_DAILY",
                # Daily rows are stamped at midnight, so the window runs to the next one.
                "startDate": _window(last, last)["startDate"],
                "endDate": _window(last + dt.timedelta(days=1), last)["startDate"],
            },
            ttl=_ttl(last),
        ),
    )

    name: str | None = None
    updated: dt.datetime | None = None
    hours: dict[dt.datetime, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    points: dict[str, int] = {}
    for fetched in consumption:
        attrs = _attributes(fetched)
        if attrs is None:
            continue
        name = attrs.get("name") or name
        rows = attrs.get("consumptionPerGroupMunicipalityHour") or []
        updated = _updated(rows, updated)
        for row in rows:
            # Kept in Elhub's own offset: converted to Oslo time, the two 02:00 hours of the
            # autumn clock change would compare equal and merge.
            start = dt.datetime.fromisoformat(row["startTime"])
            hours[start][row["consumptionGroup"]] += row["quantityKwh"] or 0.0
            if row.get("meteringPointCount") is not None:
                points[row["consumptionGroup"]] = row["meteringPointCount"]
    if name is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"Elhub has no figures for municipality {code}.",
            next_call=NextCall(
                tool="regions_resolve",
                arguments={"query": args.municipality, "level": "municipality"},
            ),
        )

    by_day: dict[dt.date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for start, groups in hours.items():
        for group, kwh in groups.items():
            by_day[start.date()][group] += kwh
    totals: dict[str, float] = defaultdict(float)
    for groups in by_day.values():
        for group, kwh in groups.items():
            totals[group] += kwh
    grand = sum(totals.values())
    by_group = sorted(
        (
            GroupUse(
                group=group,  # type: ignore[arg-type]
                mwh=_mwh(kwh),
                share_pct=round(kwh / grand * 100, 1) if grand else 0.0,
                metering_points=points.get(group),
            )
            for group, kwh in totals.items()
            if group in ("private", "business", "industry")
        ),
        key=lambda g: g.mwh,
        reverse=True,
    )
    missing = [d for d in days if d not in by_day]
    if missing:
        notes.append(f"No figures for {', '.join(d.isoformat() for d in missing)}.")

    kinds: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    cap_rows = (_attributes(capacity) or {}).get(
        "installedCapacityPerMeteringPointTypeGroupMunicipalityDaily"
    ) or []
    stamp = int(last.strftime("%Y%m%d"))
    for row in cap_rows:
        if row.get("usageDateId") != stamp:
            continue
        kind = row.get("productionGroup")
        kind = kind if kind in KINDS else "not_specified"
        kinds[kind][0] += row.get("installedCapacity") or 0.0
        if row.get("meteringPointTypeCode") == "E19":
            kinds[kind][1] += row.get("installedCapacity") or 0.0
    capacity_rows = sorted(
        (Capacity(kind=k, mw=_mwh(kw), prosumer_mw=_mwh(pro)) for k, (kw, pro) in kinds.items()),
        key=lambda c: c.mw,
        reverse=True,
    )

    notes.append(GROUPS_NOTE)
    if capacity_rows:
        notes.append(
            f"Capacity is installed production capacity on {last}. not_specified is capacity "
            "Elhub reports without a kind."
        )
    if region_note:
        notes.insert(0, region_note)
    counted = len(by_day)
    provenance = [
        up.provenance(f, title=f"Elhub: electricity consumption in {name} on {d}")
        for f, d in zip(consumption, days, strict=True)
    ]
    provenance.append(
        up.provenance(capacity, title=f"Elhub: installed production capacity in {name} on {last}")
    )
    return Result(
        data=MunicipalityOutput(
            code=code,
            name=name,
            from_date=first,
            to_date=last,
            days_with_figures=counted,
            total_mwh=_mwh(grand),
            average_mwh_per_day=_mwh(grand / counted) if counted else None,
            by_group=by_group,
            days=[DayUse(date=d, **_use(g)) for d, g in sorted(by_day.items())],
            hours=[HourUse(start=h, **_use(g)) for h, g in sorted(hours.items())]
            if args.resolution == "hour"
            else [],
            capacity_date=last,
            capacity_mw=round(sum(c.mw for c in capacity_rows), 3),
            capacity=capacity_rows,
            last_updated=updated,
        ),
        provenance=provenance,
        notes=notes,
    )


# --- electricity_price_areas -------------------------------------------------------

PriceArea = Literal["NO1", "NO2", "NO3", "NO4", "NO5"]
ALL_AREAS: list[PriceArea] = ["NO1", "NO2", "NO3", "NO4", "NO5"]


class PriceAreasInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    areas: list[PriceArea] = Field(
        default=ALL_AREAS,
        min_length=1,
        description="Electricity price areas; with all five, a total for Norway is added.",
    )
    from_date: dt.date | None = Field(
        default=None,
        description="First day, in Norwegian time, from 2021-01-01. Leave out both dates for the "
        "last seven full days.",
    )
    to_date: dt.date | None = Field(
        default=None, description="Last day, inclusive; at most 31 days from from_date."
    )


class AreaDay(BaseModel):
    area: str
    date: dt.date
    consumption_mwh: float
    production_mwh: float
    net_mwh: float = Field(description="Production minus consumption.")


class AreaTotal(BaseModel):
    area: str = Field(description="NO1-NO5, or NO for the sum of all five.")
    area_name: str
    consumption_mwh: float
    consumption_by_group: dict[str, float] = Field(
        description="MWh for household, cabin, primary, secondary and tertiary."
    )
    production_mwh: float
    production_by_kind: dict[str, float] = Field(
        description="MWh for hydro, wind, solar, thermal and other."
    )
    net_mwh: float = Field(description="Production minus consumption over the period.")


class PriceAreasOutput(BaseModel):
    from_date: dt.date
    to_date: dt.date
    totals: list[AreaTotal]
    days: list[AreaDay] = Field(description="By area, then day.")
    last_updated: dt.datetime | None


DATASETS = {
    "consumption": (
        "CONSUMPTION_PER_GROUP_MBA_HOUR",
        "consumptionPerGroupMbaHour",
        "consumptionGroup",
    ),
    "production": ("PRODUCTION_PER_GROUP_MBA_HOUR", "productionPerGroupMbaHour", "productionGroup"),
}


async def price_areas(ctx: Context, args: PriceAreasInput) -> Result[PriceAreasOutput]:
    first, last, notes = _period(args.from_date, args.to_date, ("electricity_price_areas", {}))
    areas = list(dict.fromkeys(args.areas))
    chunks = []
    start = first
    while start <= last:
        end = min(start + dt.timedelta(days=CHUNK_DAYS - 1), last)
        chunks.append((start, end))
        start = end + dt.timedelta(days=1)

    up = ctx.upstream(SPEC.id)
    jobs = [(area, measure, chunk) for area in areas for measure in DATASETS for chunk in chunks]
    fetched = await asyncio.gather(
        *(
            up.get_json(
                f"{BASE_URL}/price-areas/{area}",
                params={"dataset": DATASETS[measure][0], **_window(*chunk)},
                ttl=_ttl(chunk[1]),
            )
            for area, measure, chunk in jobs
        )
    )

    # area -> measure -> day -> group -> kWh
    sums: dict[str, dict[str, dict[dt.date, dict[str, float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    )
    updated: dt.datetime | None = None
    provenance: list[Provenance] = []
    for (area, measure, chunk), result in zip(jobs, fetched, strict=True):
        _, key, group_field = DATASETS[measure]
        rows = (_attributes(result) or {}).get(key) or []
        updated = _updated(rows, updated)
        for row in rows:
            day = dt.datetime.fromisoformat(row["startTime"]).date()
            group = row.get(group_field) or "not_specified"
            group = "not_specified" if group == "*" else group
            sums[area][measure][day][group] += row.get("quantityKwh") or 0.0
        provenance.append(
            up.provenance(
                result, title=f"Elhub: electricity {measure} in {area}, {chunk[0]} to {chunk[1]}"
            )
        )

    days: list[AreaDay] = []
    totals: list[AreaTotal] = []
    for area in areas:
        consumed, produced = sums[area]["consumption"], sums[area]["production"]
        for day in sorted(set(consumed) | set(produced)):
            c, p = sum(consumed[day].values()), sum(produced[day].values())
            days.append(
                AreaDay(
                    area=area,
                    date=day,
                    consumption_mwh=_mwh(c),
                    production_mwh=_mwh(p),
                    net_mwh=_mwh(p - c),
                )
            )
        totals.append(_area_total(area, consumed, produced))
    if len(areas) == len(ALL_AREAS):
        country_c: dict[dt.date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        country_p: dict[dt.date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for area in areas:
            for target, measure in ((country_c, "consumption"), (country_p, "production")):
                for day, groups in sums[area][measure].items():
                    for group, kwh in groups.items():
                        target[day][group] += kwh
        totals.append(_area_total("NO", country_c, country_p))

    if not days:
        notes.append("Elhub has no figures for this period.")
    notes += [
        AREA_GROUPS_NOTE,
        (
            "net_mwh is production minus metered consumption. Grid losses are in neither, so it is a "
            "rough sign of whether an area produced more than it used, not the exchange with its "
            "neighbours."
        ),
    ]
    return Result(
        data=PriceAreasOutput(
            from_date=first, to_date=last, totals=totals, days=days, last_updated=updated
        ),
        provenance=provenance,
        notes=notes,
    )


def _area_total(
    area: str,
    consumed: dict[dt.date, dict[str, float]],
    produced: dict[dt.date, dict[str, float]],
) -> AreaTotal:
    def by_group(days: dict[dt.date, dict[str, float]]) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for groups in days.values():
            for group, kwh in groups.items():
                out[group] += kwh
        return {g: _mwh(kwh) for g, kwh in sorted(out.items(), key=lambda x: -x[1])}

    c, p = by_group(consumed), by_group(produced)
    return AreaTotal(
        area=area,
        area_name=AREA_NAMES.get(area, area),
        consumption_mwh=round(sum(c.values()), 3),
        consumption_by_group=c,
        production_mwh=round(sum(p.values()), 3),
        production_by_kind=p,
        net_mwh=round(sum(p.values()) - sum(c.values()), 3),
    )


OPERATIONS = (
    Operation(
        name="electricity_municipality",
        title="Electricity use in a municipality",
        description=(
            "Electricity consumption in one Norwegian municipality from Elhub, the national "
            "metering data hub: MWh per day (or per hour) for private customers (homes and "
            "cabins), business (services) and industry, each group's share and number of "
            "metering points, and the production capacity installed in the municipality by kind "
            "(hydro, wind, solar, thermal). Any period of up to 31 days since 2021; by default "
            "the last seven full days. Accepts codes, old or current, and names."
        ),
        input_model=MunicipalityInput,
        output_model=MunicipalityOutput,
        handler=municipality_electricity,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/electricity/municipalities/{municipality}",
        examples=(
            {"municipality": "Bergen"},
            {"municipality": "0301", "from_date": "2026-01-05", "to_date": "2026-01-11"},
            {
                "municipality": "Tromsø",
                "from_date": "2026-10-01",
                "to_date": "2026-10-01",
                "resolution": "hour",
            },
        ),
    ),
    Operation(
        name="electricity_price_areas",
        title="Electricity by price area",
        description=(
            "Electricity consumption and production in Norway's five price areas (NO1-NO5) from "
            "Elhub: MWh per day and for the period, consumption by households, cabins and "
            "primary, secondary and tertiary industry, production by hydro, wind, solar, thermal "
            "and other, and production minus consumption. With all five areas, a total for "
            "Norway is added. Any period of up to 31 days since 2021; by default the last seven "
            "full days."
        ),
        input_model=PriceAreasInput,
        output_model=PriceAreasOutput,
        handler=price_areas,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/electricity/price-areas",
        examples=({}, {"areas": ["NO2"], "from_date": "2026-01-01", "to_date": "2026-01-31"}),
    ),
)
