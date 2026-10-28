from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The EU data themes the catalogue classifies by.
THEMES = {
    "AGRI": "Agriculture, fisheries, forestry and food",
    "ECON": "Economy and finance",
    "EDUC": "Education, culture and sport",
    "ENER": "Energy",
    "ENVI": "Environment",
    "GOVE": "Government and public sector",
    "HEAL": "Health",
    "INTR": "International issues",
    "JUST": "Justice, legal system and public safety",
    "OP_DATPRO": "Provisional data",
    "REGI": "Regions and cities",
    "SOCI": "Population and society",
    "TECH": "Science and technology",
    "TRAN": "Transport",
}
Theme = Literal[
    "AGRI",
    "ECON",
    "EDUC",
    "ENER",
    "ENVI",
    "GOVE",
    "HEAL",
    "INTR",
    "JUST",
    "OP_DATPRO",
    "REGI",
    "SOCI",
    "TECH",
    "TRAN",
]


class CatalogSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
        description="Words to find in titles, descriptions and keywords. Norwegian words often "
        "find more, e.g. 'befolkning' as well as 'population'.",
    )
    kind: Literal["datasets", "data_services"] = Field(
        default="datasets", description="Datasets, or APIs and other data services."
    )
    open_data_only: bool = Field(default=False, description="Only data marked as open data.")
    themes: list[Theme] | None = Field(default=None, min_length=1)
    publisher: str | None = Field(
        default=None,
        pattern=r"^/[A-Z]+(/\d{9})*$",
        description="Organisation path as results give it in publisher.path, e.g. "
        "'/STAT/972417807/971526920' (Statistics Norway). A shorter path includes everything "
        "below it: '/KOMMUNE' is every municipality.",
    )
    formats: list[str] | None = Field(
        default=None,
        min_length=1,
        description="File types such as 'CSV', 'JSON', 'GEOJSON', or media types such as "
        "'text/csv'.",
    )
    modified_within_days: int | None = Field(default=None, ge=1, le=3650)
    limit: int = Field(default=10, ge=1, le=50)
    page: int = Field(default=0, ge=0, le=200)

    @model_validator(mode="after")
    def _some_filter(self) -> CatalogSearchInput:
        if not any(
            [
                self.query,
                self.themes,
                self.publisher,
                self.formats,
                self.modified_within_days,
                self.open_data_only,
            ]
        ):
            raise ValueError("give a query or at least one filter")
        return self


class Publisher(BaseModel):
    name: str | None
    org_number: str | None
    path: str | None = Field(description="Use as `publisher` to search only this organisation.")


class CatalogEntry(BaseModel):
    id: str
    kind: Literal["dataset", "data_service"]
    title: str
    description: str | None = Field(description="Cut at about 500 characters.")
    publisher: Publisher
    open_data: bool | None
    access: str | None = Field(description="'public', 'restricted' or 'non-public'.")
    themes: list[str]
    formats: list[str]
    keywords: list[str]
    page_url: str = Field(description="The entry on data.norge.no, with licence and downloads.")
    source_url: str | None = Field(description="Where the publisher's own description lives.")
    first_harvested: dt.datetime | None
    modified: dt.datetime | None


class CatalogSearchOutput(BaseModel):
    total_matches: int
    page: int
    pages: int
    entries: list[CatalogEntry]
