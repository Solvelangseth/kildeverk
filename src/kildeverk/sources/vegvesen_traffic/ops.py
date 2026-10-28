"""Traffic counts from Statens vegvesen's traffic data API (GraphQL)."""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.context import Context
from kildeverk.core.envelope import Provenance, Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import Fetched, Upstream, UpstreamClientError
from kildeverk.sources.vegvesen_traffic.spec import GRAPHQL_URL, SPEC

OSLO = ZoneInfo("Europe/Oslo")
PAGE = 100  # the API refuses larger pages
MAX_DAYS = {"hourly": 7, "daily": 366}
HEAVY_FROM_M = 5.6  # Statens vegvesen's split between light and heavy vehicles

PointId = Field(pattern=r"^\d{5}V\d{3,9}$", description="Point id from traffic_find_points.")


# --- traffic_find_points -----------------------------------------------------------


class FindPointsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=60)
    municipality: str | None = Field(default=None, pattern=r"^\d{4}$")
    county: str | None = Field(default=None, pattern=r"^\d{2}$")
    road: str | None = Field(
        default=None,
        pattern=r"^(?i:[ERFK]V?)\s?\d{1,5}$",
        description="Road number, e.g. 'E39', 'Rv7', 'Fv5000'.",
    )
    lat: float | None = Field(default=None, ge=57, le=72)
    lon: float | None = Field(default=None, ge=4, le=32)
    radius_km: float = Field(default=5, gt=0, le=20, description="With lat and lon.")
    kind: Literal["vehicle", "bicycle"] | None = None
    include_inactive: bool = Field(
        default=False, description="Also points that are out of service or retired."
    )
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _some_filter(self) -> FindPointsInput:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if not any([self.name, self.municipality, self.county, self.lat is not None]):
            raise ValueError("give name, municipality, county, or lat and lon")
        return self


class Point(BaseModel):
    id: str
    name: str
    road: str | None = Field(description="Road reference, e.g. 'EV39 S77D1 m7122'.")
    municipality_code: str | None
    municipality: str | None
    county_code: str | None
    county: str | None
    lat: float | None
    lon: float | None
    distance_km: float | None
    kind: str
    status: str = Field(description="'operational', 'out_of_service' or 'retired'.")
    continuous: bool = Field(description="Counts all year, rather than in periods.")
    first_data: dt.date | None
    latest_data: dt.date | None


class FindPointsOutput(BaseModel):
    total_matches: int
    points: list[Point]


_POINT_FIELDS = (
    "id name operationalStatus trafficRegistrationType registrationFrequency "
    "location { coordinates { latLon { lat lon } } municipality { number name } "
    "county { number name } roadReference { shortForm } } "
    "dataTimeSpan { firstData latestData { volumeByDay } }"
)


async def _graphql(up: Upstream, query: str, ttl: str) -> Fetched:
    try:
        fetched = await up.post_json(GRAPHQL_URL, body={"query": query}, ttl=ttl)
    except UpstreamClientError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"The traffic data API rejected the request: {exc.detail}",
            source_id=SPEC.id,
            upstream_status=exc.status,
        ) from None
    errors = fetched.json.get("errors") or []
    if errors:
        message = str(errors[0].get("message") or "unknown error")
        kind = (errors[0].get("extensions") or {}).get("ErrorType")
        if kind == "NO_DATA" or "Could not find" in message:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"{message.split(' : ')[-1]}. Point ids come from traffic_find_points.",
                next_call=NextCall(tool="traffic_find_points", arguments={"name": "Bergen"}),
                source_id=SPEC.id,
            )
        raise ToolError(
            ErrorCode.UPSTREAM_UNAVAILABLE
            if "unknown error" in message
            else ErrorCode.INVALID_ARGUMENT,
            f"The traffic data API failed: {message[:200]}",
            retry_after_s=30 if "unknown error" in message else None,
            source_id=SPEC.id,
        )
    return fetched


def _road(value: str) -> str:
    """'E39' → 'EV39', 'rv 7' → 'RV7', as road references write them."""

    letters, number = re.match(r"^([A-Za-z]+)\s?(\d+)$", value.strip()).groups()  # type: ignore[union-attr]
    letter = letters[0].upper()
    return f"{letter}V{number}"


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _day(value: Any) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(value).date() if value else None
    except ValueError:
        return None


def _point(item: dict[str, Any], origin: tuple[float, float] | None) -> Point:
    location = item.get("location") or {}
    latlon = (location.get("coordinates") or {}).get("latLon") or {}
    municipality = location.get("municipality") or {}
    county = location.get("county") or {}
    span = item.get("dataTimeSpan") or {}
    lat, lon = latlon.get("lat"), latlon.get("lon")
    return Point(
        id=item["id"],
        name=item.get("name") or item["id"],
        road=(location.get("roadReference") or {}).get("shortForm"),
        municipality_code=f"{municipality['number']:04d}" if municipality.get("number") else None,
        municipality=municipality.get("name"),
        county_code=f"{county['number']:02d}" if county.get("number") else None,
        county=county.get("name"),
        lat=lat,
        lon=lon,
        distance_km=round(_distance_km(*origin, lat, lon), 2)
        if origin and lat is not None and lon is not None
        else None,
        kind=(item.get("trafficRegistrationType") or "").lower(),
        status=(item.get("operationalStatus") or "").lower(),
        continuous=item.get("registrationFrequency") == "CONTINUOUS",
        first_data=_day(span.get("firstData")),
        latest_data=_day((span.get("latestData") or {}).get("volumeByDay")),
    )


async def find_points(ctx: Context, args: FindPointsInput) -> Result[FindPointsOutput]:
    up = ctx.upstream(SPEC.id)
    provenance: list[Provenance] = []
    notes: list[str] = []
    county = args.county or (args.municipality[:2] if args.municipality else None)
    origin = (args.lat, args.lon) if args.lat is not None and args.lon is not None else None
    if origin and not county and not args.name:
        # The full list of points is several megabytes; narrow it to the point's county.
        from kildeverk.sources.kartverket.models import RegionsAtPointInput
        from kildeverk.sources.kartverket.ops import regions_at_point

        located = await regions_at_point(ctx, RegionsAtPointInput(lat=origin[0], lon=origin[1]))
        county = located.data.county_code
        provenance.extend(located.provenance)
        notes.append(
            f"Searched {located.data.county} only; points across the county border are not "
            "included."
        )

    search = []
    if args.name:
        search.append(f"query: {_quote(args.name)}")
    if county:
        search.append(f"countyNumbers: [{int(county)}]")
    if args.road:
        search.append(f"roadCategoryIds: [{_road(args.road)[0]}]")
    query = f"{{ trafficRegistrationPoints(searchQuery: {{{', '.join(search)}}}) {{ {_POINT_FIELDS} }} }}"
    fetched = await _graphql(up, query, ttl="points")
    provenance.append(up.provenance(fetched, title="Traffic registration points"))
    notes = [*fetched.notes, *notes]

    road = _road(args.road) if args.road else None
    points = []
    for item in fetched.json["data"]["trafficRegistrationPoints"] or []:
        p = _point(item, origin)
        if not args.include_inactive and p.status != "operational":
            continue
        if args.kind and p.kind != args.kind:
            continue
        if args.municipality and p.municipality_code != args.municipality:
            continue
        if road and not (p.road or "").upper().startswith(f"{road} "):
            continue
        if origin and (p.distance_km is None or p.distance_km > args.radius_km):
            continue
        points.append(p)
    if origin:
        points.sort(key=lambda p: p.distance_km or 0)
    else:
        points.sort(key=lambda p: (not p.continuous, p.name))
    if not points:
        notes.append(
            "No point matched. Try include_inactive=true, a larger radius_km, or fewer filters."
        )
    elif len(points) > args.limit:
        notes.append(f"{len(points)} points matched; the first {args.limit} are included.")
    return Result(
        data=FindPointsOutput(total_matches=len(points), points=points[: args.limit]),
        provenance=provenance,
        notes=notes,
        truncated=len(points) > args.limit,
    )


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# --- traffic_volumes ---------------------------------------------------------------


class VolumesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: str = PointId
    resolution: Literal["hourly", "daily", "annual"] = Field(
        default="daily",
        description="'annual' gives the annual average daily traffic (ÅDT) for every year.",
    )
    start: dt.date | None = Field(
        default=None,
        description="First day. Defaults to 7 days ago (daily) or yesterday (hourly).",
    )
    end: dt.date | None = Field(default=None, description="Last day, included.")

    @model_validator(mode="after")
    def _period(self) -> VolumesInput:
        if self.end is not None and self.start is None:
            raise ValueError("give start with end")
        if self.resolution != "annual" and self.start and self.end:
            if self.end < self.start:
                raise ValueError("end must not be before start")
            if (self.end - self.start).days >= MAX_DAYS[self.resolution]:
                raise ValueError(
                    f"{self.resolution} periods can be at most {MAX_DAYS[self.resolution]} days"
                )
        return self


class Volume(BaseModel):
    start: dt.datetime | None = Field(description="Null for annual averages.")
    end: dt.datetime | None
    year: int | None = Field(description="For annual averages.")
    vehicles: int | None = Field(description="A count, or for 'annual' the daily average.")
    coverage_pct: float | None = Field(description="How much of the period was counted.")
    light: int | None = Field(description="Vehicles shorter than 5.6 m.")
    heavy: int | None = Field(
        description="Vehicles 5.6 m or longer. Vehicles of unmeasured length are in neither."
    )
    by_direction: dict[str, int] = Field(description="Vehicles per heading.")


class VolumesOutput(BaseModel):
    point: str
    resolution: str
    rows: list[Volume]


_VOLUME_FIELDS = (
    "from to total { volumeNumbers { volume } coverage { percentage } } "
    "byDirection { heading total { volumeNumbers { volume } } } "
    "byLengthRange { lengthRange { lowerBound upperBound } total { volumeNumbers { volume } } }"
)


def _split(ranges: list[dict[str, Any]], key: str) -> tuple[int | None, int | None]:
    light = heavy = None
    for r in ranges:
        bounds = r.get("lengthRange") or {}
        value = ((r.get("total") or {}).get(key) or {}).get(
            "volume" if key == "volumeNumbers" else "average"
        )
        if bounds.get("lowerBound") is None and bounds.get("upperBound") == HEAVY_FROM_M:
            light = value
        elif bounds.get("lowerBound") == HEAVY_FROM_M and bounds.get("upperBound") is None:
            heavy = value
    return light, heavy


def _bound(day: dt.date) -> str:
    return dt.datetime(day.year, day.month, day.day, tzinfo=OSLO).isoformat()


async def volumes(ctx: Context, args: VolumesInput) -> Result[VolumesOutput]:
    up = ctx.upstream(SPEC.id)
    point = _quote(args.point)
    rows: list[Volume] = []
    provenance: list[Provenance] = []
    notes: list[str] = []

    if args.resolution == "annual":
        query = (
            f"{{ trafficData(trafficRegistrationPointId: {point}) {{ volume {{ average {{ daily "
            "{ byYear { year total { volume { average } coverage { percentage } } "
            "byDirection { heading total { volume { average } } } "
            "byLengthRange { lengthRange { lowerBound upperBound } total { volume { average } } } "
            "} } } } } }"
        )
        fetched = await _graphql(up, query, ttl="averages")
        provenance.append(
            up.provenance(fetched, title=f"Annual average daily traffic, {args.point}")
        )
        notes.extend(fetched.notes)
        for y in fetched.json["data"]["trafficData"]["volume"]["average"]["daily"]["byYear"] or []:
            if args.start and y["year"] < args.start.year:
                continue
            if args.end and y["year"] > args.end.year:
                continue
            total = y.get("total") or {}
            light, heavy = _split(y.get("byLengthRange") or [], "volume")
            rows.append(
                Volume(
                    start=None,
                    end=None,
                    year=y["year"],
                    vehicles=(total.get("volume") or {}).get("average"),
                    coverage_pct=(total.get("coverage") or {}).get("percentage"),
                    light=light,
                    heavy=heavy,
                    by_direction={
                        d["heading"]: ((d.get("total") or {}).get("volume") or {}).get("average")
                        for d in y.get("byDirection") or []
                        if d.get("heading")
                    },
                )
            )
        notes.append("`vehicles` is the annual average daily traffic (ÅDT).")
    else:
        today = dt.datetime.now(OSLO).date()
        if args.start is None:
            start = today - dt.timedelta(days=1 if args.resolution == "hourly" else 7)
            end = today - dt.timedelta(days=1)
        else:
            start, end = args.start, args.end or args.start
        field = "byHour" if args.resolution == "hourly" else "byDay"
        after = None
        ttl = "historic" if end < today - dt.timedelta(days=2) else "recent"
        while True:
            cursor = f", after: {_quote(after)}" if after else ""
            query = (
                f"{{ trafficData(trafficRegistrationPointId: {point}) {{ volume {{ {field}("
                f"from: {_quote(_bound(start))}, to: {_quote(_bound(end + dt.timedelta(days=1)))}"
                f"{cursor}) {{ pageInfo {{ hasNextPage endCursor }} edges {{ node {{ "
                f"{_VOLUME_FIELDS} }} }} }} }} }} }}"
            )
            fetched = await _graphql(up, query, ttl=ttl)
            provenance.append(up.provenance(fetched, title=f"Traffic volumes, {args.point}"))
            notes.extend(fetched.notes)
            connection = fetched.json["data"]["trafficData"]["volume"][field]
            for edge in connection.get("edges") or []:
                node = edge["node"]
                total = node.get("total") or {}
                light, heavy = _split(node.get("byLengthRange") or [], "volumeNumbers")
                rows.append(
                    Volume(
                        start=dt.datetime.fromisoformat(node["from"]),
                        end=dt.datetime.fromisoformat(node["to"]),
                        year=None,
                        vehicles=(total.get("volumeNumbers") or {}).get("volume"),
                        coverage_pct=(total.get("coverage") or {}).get("percentage"),
                        light=light,
                        heavy=heavy,
                        by_direction={
                            d["heading"]: ((d.get("total") or {}).get("volumeNumbers") or {}).get(
                                "volume"
                            )
                            for d in node.get("byDirection") or []
                            if d.get("heading")
                        },
                    )
                )
            info = connection.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            after = info.get("endCursor")
        notes.append("Times are Norwegian local time.")

    if not rows:
        notes.append("This point has no counts for the period.")
    if any(r.coverage_pct is not None and r.coverage_pct < 95 for r in rows):
        notes.append("Some rows cover under 95% of their period; their counts are incomplete.")
    if any(r.vehicles is None for r in rows):
        notes.append("Rows with vehicles=null were not counted.")
    return Result(
        data=VolumesOutput(point=args.point, resolution=args.resolution, rows=rows),
        provenance=provenance,
        notes=notes,
    )


OPERATIONS = (
    Operation(
        name="traffic_find_points",
        title="Find traffic counting points",
        description=(
            "Find Statens vegvesen's traffic registration points by name, municipality, county, "
            "road (e.g. 'E39') or distance from a point, for vehicles or bicycles. Each point "
            "gives its road reference, location, whether it counts all year, and the dates it "
            "has data for."
        ),
        input_model=FindPointsInput,
        output_model=FindPointsOutput,
        handler=find_points,
        # A search near a point first asks Kartverket which county the point is in.
        source_ids=(SPEC.id, "kartverket"),
        http_method="GET",
        http_path="/v1/traffic/points",
        examples=(
            {"name": "Nygårdstunnelen"},
            {"lat": 59.91, "lon": 10.75, "radius_km": 2},
            {"county": "46", "road": "E39", "limit": 5},
        ),
    ),
    Operation(
        name="traffic_volumes",
        title="Traffic volumes at a point",
        description=(
            "How many vehicles passed a traffic registration point per hour or per day, split by "
            "direction and into light and heavy vehicles, with how much of each period was "
            "counted; or the annual average daily traffic (ÅDT) for every year it has counted."
        ),
        input_model=VolumesInput,
        output_model=VolumesOutput,
        handler=volumes,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/traffic/volumes",
        examples=(
            {"point": "09194V804833", "start": "2026-10-19", "end": "2026-10-25"},
            {"point": "09194V804833", "resolution": "annual", "start": "2015-01-01"},
        ),
    ),
)
