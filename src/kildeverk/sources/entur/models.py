from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

StopId = Annotated[
    str,
    Field(
        pattern=r"^NSR:(StopPlace|Quay):\d{1,9}$",
        description="NSR id of a stop place ('NSR:StopPlace:59872', all its platforms) or of one "
        "quay ('NSR:Quay:571', one platform or side of the road). Find ids with transit_find_stops.",
    ),
]

# NeTEx stop place types, as Entur's geocoder filters on them.
StopType = Literal[
    "onstreetBus",
    "busStation",
    "coachStation",
    "onstreetTram",
    "tramStation",
    "metroStation",
    "railStation",
    "airport",
    "ferryStop",
    "harbourPort",
    "ferryPort",
    "liftStation",
    "vehicleRailInterchange",
    "other",
]

Mode = Literal[
    "bus",
    "coach",
    "tram",
    "metro",
    "rail",
    "water",
    "air",
    "cableway",
    "funicular",
    "lift",
    "trolleybus",
    "monorail",
    "taxi",
]


# --- transit_find_stops ------------------------------------------------------------


class FindStopsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None, min_length=2, max_length=80, description="Stop name, e.g. 'Oslo S'."
    )
    lat: float | None = Field(default=None, ge=57, le=82)
    lon: float | None = Field(default=None, ge=-11, le=35)
    radius_km: float = Field(
        default=1, gt=0, le=10, description="With lat and lon and no query: how far to look."
    )
    municipality: str | None = Field(
        default=None, pattern=r"^\d{4}$", description="Municipality code, e.g. '4601' (Bergen)."
    )
    stop_types: list[StopType] | None = Field(
        default=None, min_length=1, description="Only these kinds of stop, e.g. ['railStation']."
    )
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _some_filter(self) -> FindStopsInput:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if not any([self.query, self.lat is not None, self.municipality, self.stop_types]):
            raise ValueError("give query, lat and lon, municipality, or stop_types")
        return self


class Stop(BaseModel):
    id: str
    name: str
    label: str = Field(description="Name with the municipality, as Entur displays it.")
    municipality_code: str | None
    municipality: str | None
    county: str | None
    lat: float
    lon: float
    distance_km: float | None = Field(description="From lat and lon, when searching near a point.")
    modes: list[str]
    stop_types: list[str]
    fare_zones: list[str]


class FindStopsOutput(BaseModel):
    stops: list[Stop]


# --- transit_departures ------------------------------------------------------------


class DeparturesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop: StopId
    limit: int = Field(default=10, ge=1, le=50)
    within_minutes: int = Field(
        default=120, ge=1, le=1440, description="Only departures within this many minutes."
    )
    start: dt.datetime | None = Field(
        default=None,
        description="Look from this time instead of now (local Norwegian time unless an offset "
        "is given). Real-time data only exists for the next few hours.",
    )
    modes: list[Mode] | None = Field(default=None, min_length=1, description="e.g. ['rail'].")
    include_cancelled: bool = True


class Departure(BaseModel):
    aimed: dt.datetime = Field(description="Scheduled departure.")
    expected: dt.datetime = Field(description="Real-time estimate, or the schedule without one.")
    delay_s: int = Field(description="Expected minus aimed, in seconds.")
    realtime: bool = Field(description="Whether 'expected' comes from real-time data.")
    cancelled: bool
    platform: str | None
    quay_id: str | None
    line: str | None = Field(description="Public line code, e.g. 'R14' or '31'.")
    line_name: str | None
    mode: str | None
    destination: str | None
    via: list[str]
    operator: str | None
    authority: str | None
    service_journey_id: str
    situation_ids: list[str] = Field(description="Notices in `situations` that affect this one.")


class Situation(BaseModel):
    id: str
    severity: str | None
    summary: str | None
    description: str | None


class DeparturesOutput(BaseModel):
    stop_id: str
    stop_name: str
    departures: list[Departure] = Field(description="In order of expected departure.")
    situations: list[Situation] = Field(description="Disruption notices for these departures.")
