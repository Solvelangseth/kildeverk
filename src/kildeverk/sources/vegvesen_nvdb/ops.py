"""The road at a point, from the national road database (NVDB)."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.core.operation import Operation
from kildeverk.sources.met.models import Latitude, Longitude
from kildeverk.sources.vegvesen_nvdb.spec import BASE_URL, SPEC

CATEGORIES = {
    "E": "European road",
    "R": "national road",
    "F": "county road",
    "K": "municipal road",
    "P": "private road",
    "S": "forest road",
}
SPEED, TRAFFIC, HEIGHT, BRIDGE, TUNNEL = 105, 540, 591, 60, 67


class RoadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: Latitude
    lon: Longitude
    max_distance_m: int = Field(default=50, ge=1, le=300, description="How far to look for a road.")


class Road(BaseModel):
    reference: str = Field(description="NVDB's road reference, e.g. 'EV39 S78D1 m454'.")
    category: str | None = Field(description="European, national, county, municipal, private …")
    number: int | None
    distance_m: float
    municipality_code: str | None


class Traffic(BaseModel):
    vehicles_per_day: int | None = Field(description="Annual average daily traffic (ÅDT).")
    long_vehicles_pct: float | None
    year: int | None


class RoadOutput(BaseModel):
    road: Road
    speed_limit_kmh: int | None
    traffic: Traffic | None
    height_limit_m: float | None = Field(description="Signed height, where there is a limit.")
    bridge: str | None = Field(description="The bridge's name, when the point is on one.")
    tunnel: str | None = Field(description="The tunnel's name, when the point is in one.")


def _values(obj: dict[str, Any]) -> dict[str, Any]:
    return {e.get("navn"): e.get("verdi") for e in obj.get("egenskaper") or []}


def _first(fetched: Any) -> dict[str, Any] | None:
    objects = (fetched.json or {}).get("objekter") or []
    return _values(objects[0]) if objects else None


async def road_at_point(ctx: Context, args: RoadInput) -> Result[RoadOutput]:
    up = ctx.upstream(SPEC.id)
    found = await up.get_json(
        f"{BASE_URL}/posisjon",
        params={
            "lat": round(args.lat, 5),
            "lon": round(args.lon, 5),
            "srid": 4326,
            "maks_avstand": args.max_distance_m,
            "maks_antall": 10,
        },
        ttl="position",
    )
    hits = found.json if isinstance(found.json, list) else []
    # The nearest road that carries vehicles; footpaths and cycle paths carry group 'G'.
    hit = next(
        (
            h
            for h in sorted(hits, key=lambda h: h.get("avstand") or 0)
            if ((h.get("vegsystemreferanse") or {}).get("strekning") or {}).get("trafikantgruppe")
            == "K"
        ),
        None,
    )
    if hit is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"No road for vehicles within {args.max_distance_m} m of the point. Raise "
            "max_distance_m (up to 300), or give a point on the road.",
            source_id=SPEC.id,
        )
    reference = hit["vegsystemreferanse"]
    system = reference.get("vegsystem") or {}
    position = hit["veglenkesekvens"]["kortform"]
    speed, traffic, height, bridge, tunnel = await asyncio.gather(
        *(
            up.get_json(
                f"{BASE_URL}/vegobjekter/{t}",
                params={"veglenkesekvens": position, "inkluder": "egenskaper", "antall": 3},
                ttl="objects",
            )
            for t in (SPEED, TRAFFIC, HEIGHT, BRIDGE, TUNNEL)
        )
    )
    speed_v, traffic_v, height_v, bridge_v, tunnel_v = (
        _first(f) for f in (speed, traffic, height, bridge, tunnel)
    )
    category = system.get("vegkategori")
    notes = list(found.notes)
    if speed_v is None:
        notes.append("NVDB records no speed limit here; the general limit (50 or 80 km/h) applies.")
    return Result(
        data=RoadOutput(
            road=Road(
                reference=reference.get("kortform") or position,
                category=CATEGORIES.get(category or "", category),
                number=system.get("nummer"),
                distance_m=round(hit.get("avstand") or 0, 1),
                municipality_code=str(hit["kommune"]).zfill(4) if hit.get("kommune") else None,
            ),
            speed_limit_kmh=(speed_v or {}).get("Fartsgrense"),
            traffic=Traffic(
                vehicles_per_day=traffic_v.get("ÅDT, total"),
                long_vehicles_pct=traffic_v.get("ÅDT, andel lange kjøretøy"),
                year=traffic_v.get("År, gjelder for"),
            )
            if traffic_v
            else None,
            height_limit_m=(height_v or {}).get("Skilta høyde"),
            bridge=(bridge_v or {}).get("Navn") if bridge_v else None,
            tunnel=(tunnel_v or {}).get("Navn") if tunnel_v else None,
        ),
        provenance=[
            up.provenance(found, title="NVDB road position"),
            *(
                up.provenance(f, title=f"NVDB {name} at {reference.get('kortform') or position}")
                for f, name in (
                    (speed, "speed limit"),
                    (traffic, "traffic volume"),
                    (height, "height limit"),
                    (bridge, "bridge"),
                    (tunnel, "tunnel"),
                )
            ),
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="road_at_point",
        title="The road at a point",
        description=(
            "The road nearest a point in Norway, from Statens vegvesen's national road database "
            "(NVDB): its reference and category (European, national, county, municipal or "
            "private road), the speed limit, the annual average daily traffic, any signed height "
            "limit, and the bridge or tunnel it is on. Footpaths and cycle paths are skipped. "
            "For traffic counts over time, use traffic_find_points."
        ),
        input_model=RoadInput,
        output_model=RoadOutput,
        handler=road_at_point,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/roads/at-point",
        examples=(
            {"lat": 60.3790, "lon": 5.3388},
            {"lat": 59.9127, "lon": 10.7461, "max_distance_m": 100},
        ),
    ),
)
