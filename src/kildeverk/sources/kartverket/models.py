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

# --- addresses_search --------------------------------------------------------------


class AddressSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Free text, e.g. 'Munkegata 1 Trondheim'. More words narrow the search; "
        "'*' is a wildcard.",
    )
    postcode: str | None = Field(default=None, pattern=r"^\d{4}$")
    municipality: str | None = Field(
        default=None, pattern=MUNICIPALITY_PATTERN, description=MUNICIPALITY_HELP
    )
    fuzzy: bool = Field(default=False, description="Also match spellings close to the query.")
    lat: float | None = Field(default=None, ge=57, le=82)
    lon: float | None = Field(default=None, ge=-11, le=35)
    radius_m: int = Field(
        default=100, ge=1, le=1000, description="With lat and lon: the addresses within this."
    )
    limit: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def _one_kind_of_search(self) -> AddressSearchInput:
        near = self.lat is not None or self.lon is not None
        if near and (self.lat is None or self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        text = any([self.query, self.postcode, self.municipality])
        if near and text:
            raise ValueError(
                "search either near lat and lon, or by query, postcode and municipality; not both"
            )
        if not near and not text:
            raise ValueError("give query, postcode, municipality, or lat and lon")
        if self.fuzzy and (not self.query or "*" in self.query):
            raise ValueError("fuzzy needs a query without wildcards")
        return self


class Cadastre(BaseModel):
    """The property the address belongs to: farm, holding and leasehold numbers (gnr/bnr/fnr)."""

    farm: int | None
    holding: int | None
    leasehold: int | None


class Address(BaseModel):
    id: str
    text: str = Field(description="As written on the address, e.g. 'Karl Johans gate 22'.")
    street: str | None
    number: int | None
    letter: str | None
    postcode: str | None
    postal_place: str | None
    municipality_code: str
    municipality: str | None
    kind: Literal["street", "cadastral"] = Field(
        description="'street' has a street name; 'cadastral' is identified by property numbers."
    )
    cadastre: Cadastre
    lat: float | None
    lon: float | None
    distance_m: float | None
    updated: dt.date | None


class AddressSearchOutput(BaseModel):
    total_matches: int
    addresses: list[Address]


# --- places_search -----------------------------------------------------------------


class PlaceSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Place name, e.g. 'Galdhøpiggen'. '*' is a wildcard: 'storvat*'.",
    )
    fuzzy: bool = Field(default=False, description="Also match spellings close to the query.")
    type: str | None = Field(
        default=None,
        min_length=2,
        max_length=60,
        description="Kind of place, in Norwegian as the register names it, e.g. 'Fjell', "
        "'Innsjø', 'By', 'Gard', 'Tettsted', 'Øy'. Unknown kinds list close matches.",
    )
    municipality: str | None = Field(
        default=None, pattern=MUNICIPALITY_PATTERN, description=MUNICIPALITY_HELP
    )
    county: str | None = Field(default=None, pattern=COUNTY_PATTERN, description=COUNTY_HELP)
    lat: float | None = Field(default=None, ge=57, le=82)
    lon: float | None = Field(default=None, ge=-11, le=35)
    radius_m: int = Field(default=500, ge=1, le=5000, description="With lat and lon.")
    limit: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def _one_kind_of_search(self) -> PlaceSearchInput:
        near = self.lat is not None or self.lon is not None
        if near and (self.lat is None or self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        if near and any([self.query, self.municipality, self.county, self.fuzzy]):
            raise ValueError(
                "search either near lat and lon (optionally with type), or by query; not both"
            )
        if not near and not self.query:
            raise ValueError("give query, or lat and lon")
        if self.fuzzy and "*" in (self.query or ""):
            raise ValueError("fuzzy does not combine with wildcards")
        return self


class PlaceName(BaseModel):
    name: str
    language: str | None
    status: str | None = Field(
        description="Spelling status, e.g. 'vedtatt' (decided), 'historisk'."
    )


class Area(BaseModel):
    code: str
    name: str


class Place(BaseModel):
    id: int = Field(description="Kartverket's place number (stedsnummer).")
    name: str = Field(description="The preferred name.")
    names: list[PlaceName] = Field(description="Every spelling and language the register holds.")
    type: str = Field(description="Kind of place, in Norwegian, e.g. 'Fjell' (mountain).")
    municipalities: list[Area]
    counties: list[Area]
    lat: float | None
    lon: float | None
    distance_m: float | None
    status: str | None = Field(description="'aktiv' for places that exist today.")


class PlaceSearchOutput(BaseModel):
    total_matches: int
    places: list[Place]


# --- elevation ---------------------------------------------------------------------


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=57, le=82)
    lon: float = Field(ge=-11, le=35)


class ElevationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[Point] = Field(min_length=1, max_length=50)


class Elevation(BaseModel):
    lat: float
    lon: float
    elevation_m: float | None = Field(description="Metres above sea level; negative is a depth.")
    data_source: str | None = Field(description="Which model the value comes from.")
    terrain: str | None = Field(description="Kartverket's terrain class, in Norwegian.")


class ElevationOutput(BaseModel):
    points: list[Elevation]


# --- regions_at_point --------------------------------------------------------------


class RegionsAtPointInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=57, le=72)
    lon: float = Field(ge=-1, le=33)


class RegionsAtPointOutput(BaseModel):
    municipality_code: str = Field(
        description="Current code; works with every *_municipality filter."
    )
    municipality: str
    county_code: str
    county: str
