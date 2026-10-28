from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

StationId = Annotated[
    str,
    Field(
        pattern=r"^\d{1,4}\.\d{1,5}\.\d{1,3}$",
        description="NVE station id, three numbers with dots, e.g. '62.5.0'. "
        "Find ids with water_find_stations.",
    ),
]

# Friendly names for common parameters; any HydAPI parameter number works too.
PARAMETER_ALIASES = {
    "precipitation": 0,
    "water_level": 1000,
    "discharge": 1001,
    "water_temperature": 1003,
    "reservoir_volume": 1004,
    "air_temperature": 17,
    "snow_depth": 2002,
    "snow_water_equivalent": 2003,
    "groundwater_level": 5130,
}
ParameterName = Annotated[
    str,
    Field(
        pattern=r"^([a-z_]+|\d{1,5})$",
        description="One of " + ", ".join(PARAMETER_ALIASES) + ", or a HydAPI parameter number.",
    ),
]

RESOLUTIONS = {"instantaneous": 0, "hourly": 60, "daily": 1440}


# --- water_find_stations -----------------------------------------------------------


class FindStationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station: StationId | None = Field(default=None, description="One station by id.")
    name: str | None = Field(
        default=None, min_length=2, max_length=60, description="Part of the name."
    )
    municipality: str | None = Field(
        default=None, pattern=r"^\d{4}$", description="Municipality code, e.g. '4621' (Voss)."
    )
    county: str | None = Field(
        default=None, min_length=2, max_length=40, description="County name."
    )
    lat: float | None = Field(default=None, ge=57, le=82)
    lon: float | None = Field(default=None, ge=-11, le=35)
    radius_km: float = Field(default=20, gt=0, le=100, description="With lat and lon.")
    parameter: ParameterName | None = Field(
        default=None, description="Only stations measuring this, e.g. 'discharge'."
    )
    include_closed: bool = False
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _some_filter(self) -> FindStationsInput:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if not any([self.station, self.name, self.municipality, self.county, self.lat is not None]):
            raise ValueError("give station, name, municipality, county, or lat and lon")
        return self


class Series(BaseModel):
    parameter: int
    alias: str | None = Field(description="Name to use in water_observations, when there is one.")
    name: str = Field(description="NVE's own (Norwegian) name for the parameter.")
    unit: str | None
    resolutions: list[Literal["instantaneous", "hourly", "daily"]]
    data_from: dt.date | None
    data_to: dt.date | None


class FloodStatistics(BaseModel):
    """Peak (culmination) discharge in m³/s: the mean annual flood and floods with a return period."""

    mean_annual: float | None
    return_5y: float | None
    return_10y: float | None
    return_20y: float | None
    return_50y: float | None


class Station(BaseModel):
    id: str
    name: str
    river: str | None
    lake: str | None
    municipality_code: str | None
    municipality: str | None
    county: str | None
    lat: float | None
    lon: float | None
    elevation_m: float | None
    distance_km: float | None
    catchment_km2: float | None
    regulation: str | None = Field(
        description="Whether and how the catchment is regulated by dams."
    )
    active: bool
    series: list[Series]
    flood_statistics: FloodStatistics | None


class FindStationsOutput(BaseModel):
    total_matches: int
    stations: list[Station]


# --- water_observations ------------------------------------------------------------


class ObservationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station: StationId
    parameter: ParameterName = "discharge"
    resolution: Literal["instantaneous", "hourly", "daily"] = "daily"
    start: dt.datetime | dt.date | None = Field(
        default=None, description="Leave start and end out for the latest value only."
    )
    end: dt.datetime | dt.date | None = Field(default=None, description="Not included.")
    max_rows: int = Field(default=2000, ge=1, le=10_000)

    @model_validator(mode="after")
    def _period(self) -> ObservationsInput:
        if (self.start is None) != (self.end is None):
            raise ValueError("give both start and end, or neither for the latest value")
        if self.start is not None and as_utc(self.end) <= as_utc(self.start):  # type: ignore[arg-type]
            raise ValueError("end must be after start")
        return self


def as_utc(value: dt.datetime | dt.date) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    return dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)


class Reading(BaseModel):
    time: dt.datetime
    value: float
    quality: Literal["unknown", "uncontrolled", "primary_controlled", "secondary_controlled"]
    corrected: bool


class ObservationsOutput(BaseModel):
    station: str
    station_name: str | None
    parameter: int
    parameter_name: str | None
    unit: str | None
    method: str | None = Field(
        description="'Mean' for hourly and daily values, 'Instantaneous' for raw."
    )
    row_count: int
    rows: list[Reading]
