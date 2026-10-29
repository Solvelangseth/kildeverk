from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kildeverk.sources.ssb_klass.names import (
    COUNTY_HELP,
    COUNTY_PATTERN,
    MUNICIPALITY_HELP,
    MUNICIPALITY_PATTERN,
)

MAX_DAYS = 31

LEVEL_NAMES = {0: "none", 1: "green", 2: "yellow", 3: "orange", 4: "red"}
AVALANCHE_LEVEL_NAMES = {
    0: "no rating",
    1: "low",
    2: "moderate",
    3: "considerable",
    4: "high",
    5: "very high",
}


class _Period(BaseModel):
    start: dt.date | None = Field(
        default=None, description="First day. Leave start and end out for today and two more days."
    )
    end: dt.date | None = Field(default=None, description="Last day, included.")

    @model_validator(mode="after")
    def _period(self):
        if self.end is not None and self.start is None:
            raise ValueError("give start with end")
        if self.start and self.end:
            if self.end < self.start:
                raise ValueError("end must not be before start")
            if (self.end - self.start).days >= MAX_DAYS:
                raise ValueError(f"a period can be at most {MAX_DAYS} days")
        return self


# --- hazards_flood_landslide -------------------------------------------------------


class FloodLandslideInput(_Period):
    model_config = ConfigDict(extra="forbid")

    kinds: list[Literal["flood", "landslide"]] = Field(default=["flood", "landslide"], min_length=1)
    municipality: str | None = Field(
        default=None, pattern=MUNICIPALITY_PATTERN, description=MUNICIPALITY_HELP
    )
    county: str | None = Field(default=None, pattern=COUNTY_PATTERN, description=COUNTY_HELP)
    min_level: int = Field(
        default=2,
        ge=1,
        le=4,
        description="1 green, 2 yellow, 3 orange, 4 red. The default leaves out green days.",
    )
    language: Literal["en", "nb"] = Field(
        default="en", description="'nb' for NVE's Norwegian texts."
    )

    @model_validator(mode="after")
    def _one_area(self) -> FloodLandslideInput:
        if self.municipality and self.county:
            raise ValueError("give municipality or county, not both")
        return self


class Area(BaseModel):
    code: str
    name: str


class Warning(BaseModel):
    kind: Literal["flood", "landslide"]
    level: int
    level_name: str
    valid_from: dt.datetime
    valid_to: dt.datetime
    published: dt.datetime | None
    title: str | None
    warning: str | None
    consequences: str | None
    advice: str | None
    causes: list[str]
    counties: list[Area]
    municipalities: list[Area]
    id: str


class FloodLandslideOutput(BaseModel):
    warnings: list[Warning] = Field(description="Highest level first, then by start time.")


# --- hazards_avalanche -------------------------------------------------------------


class AvalancheInput(_Period):
    model_config = ConfigDict(extra="forbid")

    region: int | None = Field(
        default=None,
        ge=3000,
        le=3999,
        description="Forecasting region id, e.g. 3011 (Tromsø). Leave region, lat and lon out "
        "for a summary of every region with their ids.",
    )
    lat: float | None = Field(default=None, ge=57, le=82)
    lon: float | None = Field(default=None, ge=-11, le=35)
    language: Literal["en", "nb"] = Field(
        default="en", description="'nb' for NVE's Norwegian texts."
    )

    @model_validator(mode="after")
    def _one_place(self) -> AvalancheInput:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if self.region is not None and self.lat is not None:
            raise ValueError("give region, or lat and lon, not both")
        return self


class AvalancheProblem(BaseModel):
    type: str | None
    cause: str | None
    probability: str | None
    trigger: str | None
    size: str | None
    distribution: str | None
    aspects: list[str] = Field(description="Compass directions of the slopes affected.")
    heights: str | None = Field(description="Where in the terrain, e.g. 'above 600 m'.")
    summary: str | None


class AvalancheForecast(BaseModel):
    region_id: int
    region: str
    region_type: str | None = Field(description="'A' regions get full forecasts, 'B' simpler ones.")
    date: dt.date
    level: int
    level_name: str
    summary: str | None
    published: dt.datetime | None
    problems: list[AvalancheProblem] = Field(description="Only when one region is asked for.")
    advice: list[str]
    danger_assessment: str | None = Field(
        description="The forecaster's assessment; can be in Norwegian only."
    )


class AvalancheOutput(BaseModel):
    forecasts: list[AvalancheForecast]
