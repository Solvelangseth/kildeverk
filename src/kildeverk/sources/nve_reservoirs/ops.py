"""Weekly hydropower reservoir fill from NVE's reservoir statistics."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.operation import Operation
from kildeverk.sources.nve_reservoirs.spec import BASE_URL, SPEC

Area = Literal["NO", "NO1", "NO2", "NO3", "NO4", "NO5", "VASS1", "VASS2", "VASS3", "VASS4"]
AREAS: dict[tuple[str, int], str] = {
    ("NO", 0): "NO",
    **{("EL", n): f"NO{n}" for n in range(1, 6)},
    **{("VASS", n): f"VASS{n}" for n in range(1, 5)},
}
AREA_NAMES = {
    "NO": "Norway",
    "NO1": "Southeast Norway (price area NO1)",
    "NO2": "Southwest Norway (price area NO2)",
    "NO3": "Central Norway (price area NO3)",
    "NO4": "Northern Norway (price area NO4)",
    "NO5": "Western Norway (price area NO5)",
    "VASS1": "Southeast Norway (watercourse region 1)",
    "VASS2": "Western Norway (watercourse region 2)",
    "VASS3": "Central Norway (watercourse region 3)",
    "VASS4": "Northern Norway (watercourse region 4)",
}


class ReservoirsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    areas: list[Area] = Field(
        default=["NO", "NO1", "NO2", "NO3", "NO4", "NO5"],
        min_length=1,
        description="'NO' for the whole country, NO1-NO5 for electricity price areas, "
        "VASS1-VASS4 for watercourse regions.",
    )
    from_year: int | None = Field(
        default=None, ge=1995, le=2100, description="Leave out for the latest week only."
    )
    to_year: int | None = Field(default=None, ge=1995, le=2100)

    @model_validator(mode="after")
    def _years(self) -> ReservoirsInput:
        if self.to_year is not None and self.from_year is None:
            raise ValueError("give from_year with to_year")
        if self.from_year and self.to_year and self.to_year < self.from_year:
            raise ValueError("to_year must not be before from_year")
        return self


class Normal(BaseModel):
    """The same week over the last 20 years."""

    min_pct: float
    median_pct: float
    max_pct: float


class Week(BaseModel):
    area: str
    area_name: str
    year: int = Field(description="ISO year.")
    week: int = Field(description="ISO week.")
    date: dt.date = Field(description="The Sunday the week's measurements refer to.")
    fill_pct: float = Field(description="Share of capacity, per cent.")
    fill_twh: float
    capacity_twh: float
    change_pp: float | None = Field(description="Change from the week before, percentage points.")
    normal: Normal | None


class ReservoirsOutput(BaseModel):
    next_publication: dt.datetime | None
    rows: list[Week] = Field(description="By area as asked, then oldest week first.")


def _pct(value: Any) -> float | None:
    return round(float(value) * 100, 2) if value is not None else None


async def reservoirs(ctx: Context, args: ReservoirsInput) -> Result[ReservoirsOutput]:
    up = ctx.upstream(SPEC.id)
    if args.from_year is None:
        fetched = await up.get_json(f"{BASE_URL}/HentOffentligDataSisteUke", ttl="latest")
    else:
        fetched = await up.get_json(f"{BASE_URL}/HentOffentligData", ttl="history")
    normals = await up.get_json(f"{BASE_URL}/HentOffentligDataMinMaxMedian", ttl="history")

    by_week = {
        (AREAS.get((n["omrType"], n["omrnr"])), n["iso_uke"]): Normal(
            min_pct=_pct(n["minFyllingsgrad"]),  # type: ignore[arg-type]
            median_pct=_pct(n["medianFyllingsGrad"]),  # type: ignore[arg-type]
            max_pct=_pct(n["maxFyllingsgrad"]),  # type: ignore[arg-type]
        )
        for n in normals.json or []
    }
    wanted = {a: i for i, a in enumerate(dict.fromkeys(args.areas))}
    to_year = args.to_year or 2100
    rows: list[Week] = []
    next_publication = None
    for item in fetched.json or []:
        area = AREAS.get((item.get("omrType"), item.get("omrnr")))
        if area not in wanted:
            continue
        if args.from_year is not None and not args.from_year <= item["iso_aar"] <= to_year:
            continue
        published = item.get("neste_Publiseringsdato") or ""
        if args.from_year is None and not published.startswith("0001"):
            next_publication = dt.datetime.fromisoformat(published)
        rows.append(
            Week(
                area=area,  # type: ignore[arg-type]
                area_name=AREA_NAMES[area],  # type: ignore[index]
                year=item["iso_aar"],
                week=item["iso_uke"],
                date=dt.date.fromisoformat(item["dato_Id"]),
                fill_pct=_pct(item["fyllingsgrad"]),  # type: ignore[arg-type]
                fill_twh=round(item["fylling_TWh"], 3),
                capacity_twh=round(item["kapasitet_TWh"], 3),
                change_pp=_pct(item.get("endring_fyllingsgrad")),
                normal=by_week.get((area, item["iso_uke"])),
            )
        )
    rows.sort(key=lambda r: (wanted[r.area], r.date))

    notes = list(fetched.notes)
    if not rows:
        notes.append("No reservoir data for these areas and years.")
    if any(r.normal for r in rows):
        notes.append(
            "`normal` is the lowest, median and highest fill for the same week over the last "
            "20 years."
        )
    if args.from_year is not None:
        notes.append("Weekly; the date is the Sunday the measurements refer to.")
    return Result(
        data=ReservoirsOutput(next_publication=next_publication, rows=rows),
        provenance=[
            up.provenance(fetched, title="NVE reservoir statistics"),
            up.provenance(normals, title="NVE reservoir statistics, 20-year min, median and max"),
        ],
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="energy_reservoirs",
        title="Hydropower reservoir fill",
        description=(
            "How full Norway's hydropower reservoirs are, from NVE's weekly statistics: per cent "
            "of capacity and TWh for the whole country, each electricity price area (NO1-NO5) or "
            "watercourse region, with the change from last week and the 20-year low, median and "
            "high for the same week. Latest week by default; any years back to 1995."
        ),
        input_model=ReservoirsInput,
        output_model=ReservoirsOutput,
        handler=reservoirs,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/energy/reservoirs",
        examples=({}, {"areas": ["NO2"], "from_year": 2022, "to_year": 2022}),
    ),
)
