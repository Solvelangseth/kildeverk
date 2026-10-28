"""Address, place-name and elevation tools backed by Kartverket's open APIs."""

from __future__ import annotations

import datetime as dt
import difflib
import json
from typing import Any

from kildeverk.context import Context
from kildeverk.core.envelope import Result
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.core.operation import Operation
from kildeverk.core.upstream import UpstreamClientError
from kildeverk.sources.kartverket.models import (
    Address,
    AddressSearchInput,
    AddressSearchOutput,
    Area,
    Cadastre,
    Elevation,
    ElevationInput,
    ElevationOutput,
    Place,
    PlaceName,
    PlaceSearchInput,
    PlaceSearchOutput,
    RegionsAtPointInput,
    RegionsAtPointOutput,
)
from kildeverk.sources.kartverket.spec import (
    ADDRESSES_URL,
    ELEVATION_URL,
    MUNICIPALITY_URL,
    PLACES_URL,
    SPEC,
)
from kildeverk.sources.ssb_klass.names import with_region_names

# Coordinates in and out are plain WGS84-compatible latitude and longitude (ETRS89).
CRS = 4258

DATA_SOURCES = {
    "dtm1": "terrain model, 1 m",
    "dom1": "surface model, 1 m (includes buildings and trees)",
    "hoydekurver": "interpolated from height contours",
    "innsjohoyde": "lake surface height",
    "dybdekurver": "interpolated from depth contours; not for navigation",
}


def _rejected(exc: UpstreamClientError, what: str) -> ToolError:
    return ToolError(
        ErrorCode.INVALID_ARGUMENT,
        f"Kartverket's {what} API rejected the request: {exc.detail}",
        source_id=SPEC.id,
        upstream_status=exc.status,
    )


def _date(value: Any) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(value).date() if isinstance(value, str) else None
    except ValueError:
        return None


# --- addresses_search --------------------------------------------------------------


def _address(item: dict[str, Any]) -> Address:
    point = item.get("representasjonspunkt") or {}
    return Address(
        id=str(item["adresseid"]),
        text=item.get("adressetekst") or "",
        street=item.get("adressenavn") or None,
        number=item.get("nummer"),
        letter=item.get("bokstav") or None,
        postcode=item.get("postnummer"),
        postal_place=item.get("poststed"),
        municipality_code=item["kommunenummer"],
        municipality=item.get("kommunenavn"),
        kind="street" if item.get("objtype") == "Vegadresse" else "cadastral",
        cadastre=Cadastre(
            farm=item.get("gardsnummer"),
            holding=item.get("bruksnummer"),
            leasehold=item.get("festenummer"),
        ),
        lat=point.get("lat"),
        lon=point.get("lon"),
        distance_m=round(item["meterDistanseTilPunkt"], 1)
        if item.get("meterDistanseTilPunkt") is not None
        else None,
        updated=_date(item.get("oppdateringsdato")),
    )


async def addresses_search(ctx: Context, args: AddressSearchInput) -> Result[AddressSearchOutput]:
    up = ctx.upstream(SPEC.id)
    params: dict[str, Any] = {"utkoordsys": CRS, "treffPerSide": args.limit}
    if args.lat is not None and args.lon is not None:
        url = f"{ADDRESSES_URL}/punktsok"
        params |= {
            "lat": round(args.lat, 5),
            "lon": round(args.lon, 5),
            "radius": args.radius_m,
            "koordsys": CRS,
        }
    else:
        url = f"{ADDRESSES_URL}/sok"
        if args.query:
            params["sok"] = args.query
            if args.fuzzy:
                params["fuzzy"] = "true"
        if args.postcode:
            params["postnummer"] = args.postcode
        if args.municipality:
            params["kommunenummer"] = args.municipality
    try:
        fetched = await up.get_json(url, params=params, ttl="addresses")
    except UpstreamClientError as exc:
        raise _rejected(exc, "address") from None

    addresses = [_address(a) for a in fetched.json.get("adresser") or []]
    if args.lat is not None:
        addresses.sort(key=lambda a: a.distance_m if a.distance_m is not None else 1e9)
    total = (fetched.json.get("metadata") or {}).get("totaltAntallTreff", len(addresses))
    notes = list(fetched.notes)
    if not addresses:
        notes.append(
            "No address matched. Try fewer words, a wildcard ('storg*'), or fuzzy=true."
            if args.query
            else "No address matched."
        )
    elif total > len(addresses):
        notes.append(f"{total} addresses matched; the first {len(addresses)} are included.")
    return Result(
        data=AddressSearchOutput(total_matches=total, addresses=addresses),
        provenance=[up.provenance(fetched, title="Kartverket address search")],
        notes=notes,
        truncated=total > len(addresses),
    )


# --- places_search -----------------------------------------------------------------


async def _place_types(ctx: Context) -> dict[str, str]:
    """Display names and codes, both lower-cased, mapped to the code the API filters on."""

    fetched = await ctx.upstream(SPEC.id).get_json(f"{PLACES_URL}/navneobjekttyper", ttl="types")
    types: dict[str, str] = {}
    for t in fetched.json or []:
        types[t["navneobjekttype"].lower()] = t["navneobjekttypekode"]
        types[t["navneobjekttypekode"].lower()] = t["navneobjekttypekode"]
    return types


def _preferred(names: list[dict[str, Any]]) -> dict[str, Any] | None:
    def rank(n: dict[str, Any]) -> tuple:
        status = n.get("skrivemåtestatus") or ""
        return (
            n.get("navnestatus") != "hovednavn",
            "prioritert" not in status and status != "vedtatt",
            "historisk" in status,
            n.get("stedsnavnnummer") or 99,
        )

    return min(names, key=rank) if names else None


def _place(item: dict[str, Any]) -> Place:
    names = item.get("stedsnavn")
    if names is None:  # the /navn shape: one name per item
        names = [item]
    best = _preferred(names) or {}
    point = item.get("representasjonspunkt") or {}
    return Place(
        id=item["stedsnummer"],
        name=best.get("skrivemåte") or str(item["stedsnummer"]),
        names=[
            PlaceName(
                name=n["skrivemåte"], language=n.get("språk"), status=n.get("skrivemåtestatus")
            )
            for n in names
            if n.get("skrivemåte")
        ],
        type=item.get("navneobjekttype") or "",
        municipalities=[
            Area(code=k["kommunenummer"], name=k["kommunenavn"]) for k in item.get("kommuner") or []
        ],
        counties=[
            Area(code=f["fylkesnummer"], name=f["fylkesnavn"]) for f in item.get("fylker") or []
        ],
        lat=point.get("nord"),
        lon=point.get("øst"),
        distance_m=item.get("meterFraPunkt"),
        status=item.get("stedstatus"),
    )


async def places_search(ctx: Context, args: PlaceSearchInput) -> Result[PlaceSearchOutput]:
    up = ctx.upstream(SPEC.id)
    type_code = None
    if args.type:
        types = await _place_types(ctx)
        type_code = types.get(args.type.lower())
        if type_code is None:
            close = difflib.get_close_matches(args.type.lower(), list(types), n=5, cutoff=0.6)
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"'{args.type}' is not a kind of place in the register."
                + (f" Close matches: {', '.join(close)}." if close else "")
                + " Kinds are named in Norwegian, e.g. Fjell, Innsjø, Elv, By, Gard, Øy.",
                source_id=SPEC.id,
            )

    params: dict[str, Any] = {"utkoordsys": CRS}
    near = args.lat is not None and args.lon is not None
    if near:
        url = f"{PLACES_URL}/punkt"
        # The point search has no type filter, so fetch generously and filter here.
        params |= {
            "nord": round(args.lat, 5),  # type: ignore[arg-type]
            "ost": round(args.lon, 5),  # type: ignore[arg-type]
            "radius": args.radius_m,
            "koordsys": CRS,
            "treffPerSide": 500 if type_code else args.limit,
        }
    else:
        url = f"{PLACES_URL}/sted"
        params |= {"sok": args.query, "treffPerSide": args.limit}
        if args.fuzzy:
            params["fuzzy"] = "true"
        if type_code:
            params["navneobjekttype"] = type_code
        if args.municipality:
            params["knr"] = args.municipality
        if args.county:
            params["fnr"] = args.county
    try:
        fetched = await up.get_json(url, params=params, ttl="places")
    except UpstreamClientError as exc:
        raise _rejected(exc, "place-name") from None

    places = [_place(p) for p in fetched.json.get("navn") or []]
    total = (fetched.json.get("metadata") or {}).get("totaltAntallTreff", len(places))
    if near:
        if type_code:
            places = [p for p in places if types.get(p.type.lower()) == type_code]
            total = len(places)
        places.sort(key=lambda p: p.distance_m if p.distance_m is not None else 1e9)
        places = places[: args.limit]
    notes = list(fetched.notes)
    if not places:
        notes.append(
            "No place matched. Try a wildcard ('storvat*'), fuzzy=true, or fewer filters."
            if args.query
            else "No named place within the radius."
        )
    elif total > len(places):
        notes.append(f"{total} places matched; the first {len(places)} are included.")
    notes.append("Place names come from the central place-name register (SSR), © Kartverket.")
    return Result(
        data=PlaceSearchOutput(total_matches=total, places=places),
        provenance=[up.provenance(fetched, title="Kartverket place names (SSR)")],
        notes=notes,
        truncated=total > len(places),
    )


# --- elevation ---------------------------------------------------------------------


async def elevation(ctx: Context, args: ElevationInput) -> Result[ElevationOutput]:
    up = ctx.upstream(SPEC.id)
    # This API takes (east, north) pairs, that is (lon, lat).
    coords = [[round(p.lon, 5), round(p.lat, 5)] for p in args.points]
    params = {"koordsys": CRS, "punkter": json.dumps(coords, separators=(",", ":"))}
    try:
        fetched = await up.get_json(f"{ELEVATION_URL}/punkt", params=params, ttl="elevation")
    except UpstreamClientError as exc:
        raise _rejected(exc, "elevation") from None

    rows = [
        Elevation(
            lat=p["y"],
            lon=p["x"],
            elevation_m=round(p["z"], 2) if p.get("z") is not None else None,
            data_source=DATA_SOURCES.get(p.get("datakilde"), p.get("datakilde")),
            terrain=p.get("terreng"),
        )
        for p in fetched.json.get("punkter") or []
    ]
    notes = list(fetched.notes)
    if any(r.elevation_m is None for r in rows):
        notes.append("Some points have no value: they lie outside Norway and its waters.")
    if any(r.elevation_m is not None and r.elevation_m < 0 for r in rows):
        notes.append("Negative values are sea depths, interpolated; not for navigation.")
    return Result(
        data=ElevationOutput(points=rows),
        provenance=[up.provenance(fetched, title="Kartverket elevation")],
        notes=notes,
    )


# --- regions_at_point --------------------------------------------------------------


async def regions_at_point(ctx: Context, args: RegionsAtPointInput) -> Result[RegionsAtPointOutput]:
    up = ctx.upstream(SPEC.id)
    params = {"nord": round(args.lat, 5), "ost": round(args.lon, 5), "koordsys": CRS}
    try:
        fetched = await up.get_json(f"{MUNICIPALITY_URL}/punkt", params=params, ttl="boundaries")
    except UpstreamClientError as exc:
        if exc.status != 404:
            raise _rejected(exc, "municipality") from None
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"({args.lat}, {args.lon}) is in no Norwegian municipality: it is outside the "
            "territorial sea, abroad, or on Svalbard or Jan Mayen, which have none.",
            next_call=NextCall(
                tool="places_search", arguments={"lat": args.lat, "lon": args.lon, "radius_m": 5000}
            ),
            source_id=SPEC.id,
            upstream_status=404,
        ) from None
    body = fetched.json
    return Result(
        data=RegionsAtPointOutput(
            municipality_code=body["kommunenummer"],
            municipality=body["kommunenavn"],
            county_code=body["fylkesnummer"],
            county=body["fylkesnavn"],
        ),
        provenance=[up.provenance(fetched, title="Kartverket municipality at point")],
        notes=[*fetched.notes, "Municipalities include their sea territory out to the baseline."],
    )


OPERATIONS = (
    Operation(
        name="addresses_search",
        title="Search Norwegian addresses",
        description=(
            "Find official addresses from Kartverket's cadastre by free text ('Munkegata 1 "
            "Trondheim'), postcode or municipality code, or the addresses nearest a point. Each "
            "address has its coordinates, postcode, municipality and property numbers (gnr/bnr)."
        ),
        input_model=AddressSearchInput,
        output_model=AddressSearchOutput,
        handler=with_region_names({"municipality": "municipality"})(addresses_search),
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/addresses",
        examples=(
            {"query": "Karl Johans gate 22 Oslo"},
            {"lat": 59.9139, "lon": 10.7522, "radius_m": 50},
        ),
    ),
    Operation(
        name="places_search",
        title="Search Norwegian place names",
        description=(
            "Find mountains, lakes, rivers, islands, farms, towns and other named places in "
            "Kartverket's place-name register, by name (wildcards and fuzzy matching allowed) or "
            "near a point, optionally by kind of place, municipality or county. Each place lists "
            "every spelling and language the register holds, including Sámi and Kven names."
        ),
        input_model=PlaceSearchInput,
        output_model=PlaceSearchOutput,
        handler=with_region_names({"municipality": "municipality", "county": "county"})(
            places_search
        ),
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/places",
        examples=(
            {"query": "Galdhøpiggen"},
            {"query": "Storvatnet", "type": "Innsjø", "county": "50"},
            {"lat": 61.636, "lon": 8.312, "radius_m": 1000},
        ),
    ),
    Operation(
        name="terrain_elevation",
        title="Elevation at points",
        description=(
            "Height above sea level at up to 50 points in Norway, from Kartverket's 1 m terrain "
            "model where available. Lakes give their surface height and the sea its depth "
            "(negative). Each value says which model it came from."
        ),
        input_model=ElevationInput,
        output_model=ElevationOutput,
        handler=elevation,
        source_ids=(SPEC.id,),
        http_method="POST",
        http_path="/v1/terrain/elevation",
        examples=({"points": [{"lat": 61.63644, "lon": 8.31248}, {"lat": 59.91, "lon": 10.75}]},),
    ),
    Operation(
        name="regions_at_point",
        title="Municipality and county at a point",
        description=(
            "Which municipality and county a coordinate lies in, by Kartverket's current "
            "boundaries. The codes plug straight into the statistics, company, address, warning "
            "and region tools, so this joins a location to everything filed by municipality."
        ),
        input_model=RegionsAtPointInput,
        output_model=RegionsAtPointOutput,
        handler=regions_at_point,
        source_ids=(SPEC.id,),
        http_method="GET",
        http_path="/v1/regions/at-point",
        examples=({"lat": 60.39, "lon": 5.32}, {"lat": 69.65, "lon": 18.96}),
    ),
)
