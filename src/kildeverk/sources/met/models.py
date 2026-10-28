from __future__ import annotations

import datetime as dt
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Latitude = Annotated[float, Field(ge=-90, le=90, description="Latitude in decimal degrees.")]
Longitude = Annotated[float, Field(ge=-180, le=180, description="Longitude in decimal degrees.")]
StationId = Annotated[
    str,
    Field(
        pattern=r"^SN\d{1,8}(:\d+)?$",
        description="Frost station id, e.g. 'SN18700' (Oslo - Blindern). "
        "Find ids with weather_find_stations.",
    ),
]

# Friendly names for the elements people ask for most; any Frost element id works too.
ELEMENT_ALIASES = {
    "temperature": "air_temperature",
    "daily_mean_temperature": "mean(air_temperature P1D)",
    "daily_max_temperature": "max(air_temperature P1D)",
    "daily_min_temperature": "min(air_temperature P1D)",
    "hourly_precipitation": "sum(precipitation_amount PT1H)",
    "daily_precipitation": "sum(precipitation_amount P1D)",
    "wind_speed": "wind_speed",
    "max_wind_gust": "max(wind_speed_of_gust PT1H)",
    "snow_depth": "surface_snow_thickness",
    "humidity": "relative_humidity",
    "pressure": "air_pressure_at_sea_level",
}


def _comma_list(value: object) -> object:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


# --- weather_forecast -------------------------------------------------------------


class ForecastInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: Latitude
    lon: Longitude
    altitude_m: int | None = Field(
        default=None,
        ge=-500,
        le=9000,
        description="Ground height in metres. Improves temperature in hilly terrain; MET "
        "estimates it if left out.",
    )
    hours: int = Field(default=48, ge=1, le=240, description="How far ahead, from the first step.")


class ForecastPoint(BaseModel):
    time: dt.datetime
    temperature_c: float | None
    wind_speed_ms: float | None
    wind_from_deg: float | None = Field(description="Direction the wind blows from, 0 = north.")
    humidity_pct: float | None
    cloud_pct: float | None
    pressure_hpa: float | None
    precipitation_mm: float | None = Field(
        description="Expected precipitation over the `precipitation_hours` after `time`."
    )
    precipitation_hours: int | None
    symbol: str | None = Field(description="MET weather symbol, e.g. 'lightrain', 'clearsky_day'.")


class Location(BaseModel):
    lat: float
    lon: float
    altitude_m: float | None


class ForecastOutput(BaseModel):
    location: Location
    updated_at: dt.datetime | None
    points: list[ForecastPoint]


# --- weather_find_stations --------------------------------------------------------


class FindStationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: Latitude | None = None
    lon: Longitude | None = None
    name: str | None = Field(
        default=None, min_length=2, max_length=60, description="Part of the station's name."
    )
    limit: int = Field(default=5, ge=1, le=50)
    include_closed: bool = Field(
        default=False, description="Also return stations no longer in use."
    )

    @model_validator(mode="after")
    def _one_way_to_search(self) -> FindStationsInput:
        has_point = self.lat is not None and self.lon is not None
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if has_point == (self.name is not None):
            raise ValueError("give either lat and lon, or name")
        return self


class Station(BaseModel):
    id: str
    name: str
    municipality: str | None
    municipality_code: str | None
    county: str | None
    lat: float | None
    lon: float | None
    elevation_m: float | None
    distance_km: float | None = Field(
        description="From the given point, when searching by position."
    )
    valid_from: dt.date | None
    valid_to: dt.date | None = Field(description="Null while the station is in use.")
    operators: list[str]


class FindStationsOutput(BaseModel):
    stations: list[Station]


# --- weather_station_elements -----------------------------------------------------


class StationElementsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station: StationId
    element_search: str | None = Field(
        default=None,
        min_length=2,
        max_length=60,
        description="Only elements whose id contains this text, e.g. 'precipitation'.",
    )


class ElementSeries(BaseModel):
    element: str = Field(description="Frost element id, usable in weather_observations.")
    unit: str | None
    resolutions: list[str] = Field(description="ISO 8601 durations, e.g. 'PT1H', 'P1D'.")
    available_from: dt.date | None
    available_to: dt.date | None = Field(description="Null while still being measured.")


class StationElementsOutput(BaseModel):
    station: str
    elements: list[ElementSeries]


# --- weather_observations ---------------------------------------------------------


class ObservationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station: StationId
    elements: Annotated[list[str], BeforeValidator(_comma_list)] = Field(
        min_length=1,
        max_length=10,
        description="What to fetch. Friendly names: "
        + ", ".join(ELEMENT_ALIASES)
        + ". Or any Frost element id, e.g. 'mean(air_temperature P1M)'.",
    )
    start: dt.datetime | dt.date = Field(description="First time included, e.g. '2024-01-01'.")
    end: dt.datetime | dt.date = Field(description="End of the period, not included.")
    max_rows: int = Field(default=2000, ge=1, le=10_000)

    @model_validator(mode="after")
    def _sane_period(self) -> ObservationsInput:
        if as_utc(self.end) <= as_utc(self.start):
            raise ValueError("end must be after start")
        if as_utc(self.end) - as_utc(self.start) > dt.timedelta(days=3660):
            raise ValueError("the period can be at most ten years")
        return self


def as_utc(value: dt.datetime | dt.date) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    return dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)


class Observation(BaseModel):
    time: dt.datetime
    element: str = Field(description="As requested: the friendly name if one was used.")
    value: float
    unit: str | None
    resolution: str | None
    time_offset: str | None = Field(
        description="When the measured period starts relative to `time`, e.g. 'PT6H'."
    )
    level_m: float | None = Field(description="Sensor height above ground, when stated.")
    quality_code: int | None = Field(description="0 = checked and OK; higher = less certain.")


class ObservationsOutput(BaseModel):
    station: str
    elements: dict[str, str] = Field(description="Requested name -> Frost element id.")
    row_count: int
    rows: list[Observation]
