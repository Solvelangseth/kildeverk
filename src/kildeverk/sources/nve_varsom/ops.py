"""Flood, landslide and avalanche warnings from NVE's Varsom APIs."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any
from zoneinfo import ZoneInfo

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.nve_varsom.models import (
    AVALANCHE_LEVEL_NAMES,
    LEVEL_NAMES,
    Area,
    AvalancheForecast,
    AvalancheInput,
    AvalancheOutput,
    AvalancheProblem,
    FloodLandslideInput,
    FloodLandslideOutput,
    Warning,
)
from kildeverk.sources.nve_varsom.spec import AVALANCHE_URL, FLOOD_URL, LANDSLIDE_URL, SPEC
from kildeverk.sources.ssb_klass.names import with_region_names

OSLO = ZoneInfo("Europe/Oslo")
ENGLISH = 2
ASPECTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
BASES = {"flood": FLOOD_URL, "landslide": LANDSLIDE_URL}


def _period(start: dt.date | None, end: dt.date | None) -> tuple[dt.date, dt.date]:
    if start is None:
        start = dt.datetime.now(OSLO).date()
        return start, start + dt.timedelta(days=2)
    return start, end or start


def _ttl(end: dt.date) -> str:
    return "historic" if end < dt.datetime.now(OSLO).date() - dt.timedelta(days=1) else "current"


def _time(value: Any) -> dt.datetime | None:
    """NVE gives local times without an offset, sometimes with seven fractional digits."""

    if not isinstance(value, str) or not value:
        return None
    value = re.sub(r"(\.\d{6})\d+", r"\1", value)
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=OSLO)


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


# --- hazards_flood_landslide -------------------------------------------------------


def _warning(kind: str, item: dict[str, Any]) -> Warning:
    level = int(item.get("ActivityLevel") or 0)
    return Warning(
        kind=kind,  # type: ignore[arg-type]
        level=level,
        level_name=LEVEL_NAMES.get(level, str(level)),
        valid_from=_time(item["ValidFrom"]),  # type: ignore[arg-type]
        valid_to=_time(item["ValidTo"]),  # type: ignore[arg-type]
        published=_time(item.get("PublishTime")),
        title=_text(item.get("MainText")),
        warning=_text(item.get("WarningText")),
        consequences=_text(item.get("ConsequenceText")),
        advice=_text(item.get("AdviceText")),
        causes=[c["Name"] for c in item.get("CauseList") or [] if c.get("Name")],
        counties=[Area(code=c["Id"], name=c["Name"]) for c in item.get("CountyList") or []],
        municipalities=[
            Area(code=m["Id"], name=m["Name"]) for m in item.get("MunicipalityList") or []
        ],
        id=str(item.get("Id") or ""),
    )


async def flood_landslide(ctx: Context, args: FloodLandslideInput) -> Result[FloodLandslideOutput]:
    up = ctx.upstream(SPEC.id)
    start, end = _period(args.start, args.end)
    dates = f"{ENGLISH}/{start.isoformat()}/{end.isoformat()}"
    if args.municipality:
        path = f"Warning/Municipality/{args.municipality}/{dates}"
    elif args.county:
        path = f"Warning/County/{args.county}/{dates}"
    else:
        # Nationwide, NVE only lists warnings above green.
        path = f"Warning/{dates}"

    warnings: list[Warning] = []
    provenance = []
    notes: list[str] = []
    for kind in args.kinds:
        try:
            fetched = await up.get_json(f"{BASES[kind]}/{path}", ttl=_ttl(end))
        except UpstreamClientError as exc:
            if exc.status == 404:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"NVE has no {kind} warnings for that area. Municipality and county codes "
                    "must be current ones (since 2024).",
                    source_id=SPEC.id,
                    upstream_status=404,
                ) from None
            raise
        provenance.append(up.provenance(fetched, title=f"NVE {kind} warnings ({start} to {end})"))
        notes.extend(fetched.notes)
        # County queries repeat one warning per municipality; merge them by id.
        merged: dict[str, Warning] = {}
        for item in fetched.json or []:
            w = _warning(kind, item)
            if w.level < args.min_level:
                continue
            key = w.id or f"{w.valid_from}-{len(merged)}"
            if key not in merged:
                merged[key] = w
                continue
            same = merged[key]
            for field in ("municipalities", "counties"):
                known = {a.code for a in getattr(same, field)}
                getattr(same, field).extend(a for a in getattr(w, field) if a.code not in known)
        warnings.extend(merged.values())
    warnings.sort(key=lambda w: (-w.level, w.valid_from, w.kind))

    area = (
        f"municipality {args.municipality}"
        if args.municipality
        else f"county {args.county}"
        if args.county
        else "Norway"
    )
    if not warnings:
        notes.append(
            f"No {' or '.join(args.kinds)} warning at level {LEVEL_NAMES[args.min_level]} or "
            f"above for {area} from {start} to {end}."
        )
    if args.min_level == 1 and not (args.municipality or args.county):
        notes.append("Nationwide, NVE only lists warnings above green; ask for a municipality.")
    notes.append("Warnings from varsom.no. Check varsom.no before acting on them.")
    return Result(
        data=FloodLandslideOutput(warnings=warnings),
        provenance=provenance,
        notes=notes,
    )


# --- hazards_avalanche -------------------------------------------------------------


async def _regions(ctx: Context) -> dict[int, str]:
    fetched = await ctx.upstream(SPEC.id).get_json(f"{AVALANCHE_URL}/Region", ttl="regions")
    return {r["Id"]: r["Name"] for r in fetched.json or []}


def _heights(problem: dict[str, Any]) -> str | None:
    h1, h2 = problem.get("ExposedHeight1"), problem.get("ExposedHeight2")
    fill = problem.get("ExposedHeightFill")
    if not h1 or fill not in (1, 2, 3, 4):
        return None
    low, high = sorted((h1, h2 or h1))
    return {
        1: f"above {h1} m",
        2: f"below {h1} m",
        3: f"between {low} and {high} m",
        4: f"below {low} m and above {high} m",
    }[fill]


def _problem(p: dict[str, Any]) -> AvalancheProblem:
    expositions = p.get("ValidExpositions") or ""
    return AvalancheProblem(
        type=_text(p.get("AvalancheProblemTypeName")),
        cause=_text(p.get("AvalCauseName")),
        probability=_text(p.get("AvalProbabilityName")),
        trigger=_text(p.get("AvalTriggerSimpleName")),
        size=_text(p.get("DestructiveSizeExtName")),
        distribution=_text(p.get("AvalPropagationName")),
        aspects=[a for a, on in zip(ASPECTS, expositions, strict=False) if on == "1"],
        heights=_heights(p),
        summary=_text(p.get("TriggerSenitivityPropagationDestuctiveSizeText")),
    )


def _forecast(item: dict[str, Any]) -> AvalancheForecast:
    level = int(item.get("DangerLevel") or 0)
    return AvalancheForecast(
        region_id=item["RegionId"],
        region=item.get("RegionName") or str(item["RegionId"]),
        region_type=item.get("RegionTypeName"),
        date=_time(item["ValidFrom"]).date(),  # type: ignore[union-attr]
        level=level,
        level_name=AVALANCHE_LEVEL_NAMES.get(level, str(level)),
        summary=_text(item.get("MainText")),
        published=_time(item.get("PublishTime")) if level else None,
        problems=[_problem(p) for p in item.get("AvalancheProblems") or []],
        advice=[
            a["Text"].strip() for a in item.get("AvalancheAdvices") or [] if _text(a.get("Text"))
        ],
        danger_assessment=_text(item.get("AvalancheDanger")),
    )


async def avalanche(ctx: Context, args: AvalancheInput) -> Result[AvalancheOutput]:
    up = ctx.upstream(SPEC.id)
    start, end = _period(args.start, args.end)
    dates = f"{ENGLISH}/{start.isoformat()}/{end.isoformat()}"
    if args.region is not None:
        regions = await _regions(ctx)
        if args.region not in regions:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"There is no avalanche region {args.region}. Regions run from "
                f"{min(regions)} to {max(regions)}; a call without region lists them all.",
                next_call=NextCall(tool="hazards_avalanche", arguments={}),
                source_id=SPEC.id,
            )
        url = f"{AVALANCHE_URL}/AvalancheWarningByRegion/Detail/{args.region}/{dates}"
    elif args.lat is not None:
        url = (
            f"{AVALANCHE_URL}/AvalancheWarningByCoordinates/Detail/"
            f"{round(args.lat, 4)}/{round(args.lon, 4)}/{dates}"  # type: ignore[arg-type]
        )
    else:
        url = f"{AVALANCHE_URL}/RegionSummary/Simple/{dates}"
    fetched = await up.get_json(url, ttl=_ttl(end))

    items = fetched.json or []
    if items and "AvalancheWarningList" in items[0]:
        items = [w for region in items for w in region.get("AvalancheWarningList") or []]
    forecasts = sorted((_forecast(i) for i in items), key=lambda f: (f.date, -f.level, f.region_id))
    notes = list(fetched.notes)
    if not forecasts and args.lat is not None:
        notes.append("That point is in no avalanche forecasting region.")
    elif forecasts and all(f.level == 0 for f in forecasts):
        notes.append("No rating: avalanche forecasts are published from about December to June.")
    if any(f.danger_assessment for f in forecasts):
        notes.append("The danger assessment text may be in Norwegian; the summary is English.")
    notes.append("Forecasts from varsom.no. Check varsom.no before going into avalanche terrain.")
    return Result(
        data=AvalancheOutput(forecasts=forecasts),
        provenance=[up.provenance(fetched, title=f"NVE avalanche forecast ({start} to {end})")],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="hazards_flood_landslide",
        title="Flood and landslide warnings",
        description=(
            "NVE's flood and landslide warnings from varsom.no, for Norway, a county or a "
            "municipality: level (green, yellow, orange, red), when it applies, what to expect, "
            "the causes, consequences and advice. Defaults to today and the next two days, "
            "yellow and above; any past period works too."
        ),
        input_model=FloodLandslideInput,
        output_model=FloodLandslideOutput,
        handler=with_region_names({"municipality": "municipality", "county": "county"})(
            flood_landslide
        ),
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/hazards/flood-landslide",
        examples=(
            {},
            {"municipality": "3305", "start": "2023-08-08", "end": "2023-08-09"},
        ),
    ),
    Operation(
        name="hazards_avalanche",
        title="Avalanche forecasts",
        description=(
            "NVE's avalanche forecasts from varsom.no: danger level 1-5 per forecasting region, "
            "with avalanche problems (type, aspects, heights, size), advice and the forecaster's "
            "assessment. Ask by region id or by point; with neither, every region's level and id. "
            "Forecasts are published in winter and spring."
        ),
        input_model=AvalancheInput,
        output_model=AvalancheOutput,
        handler=avalanche,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/hazards/avalanche",
        examples=(
            {},
            {"region": 3011, "start": "2026-03-10"},
            {"lat": 69.65, "lon": 18.96},
        ),
    ),
)
