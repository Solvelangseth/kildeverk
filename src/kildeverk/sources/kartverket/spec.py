from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

ADDRESSES_URL = "https://ws.geonorge.no/adresser/v1"
PLACES_URL = "https://api.kartverket.no/stedsnavn/v1"
ELEVATION_URL = "https://ws.geonorge.no/hoydedata/v1"
MUNICIPALITY_URL = "https://api.kartverket.no/kommuneinfo/v1"

SPEC = SourceSpec(
    id="kartverket",
    name="Kartverket: addresses, place names and elevation",
    publisher="Norwegian Mapping Authority (Kartverket)",
    homepage="https://www.kartverket.no/",
    docs_url="https://www.kartverket.no/api-og-data",
    terms_url="https://www.kartverket.no/api-og-data/vilkar-for-bruk",
    licence=Licence(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International (credit: © Kartverket)",
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    # Kartverket publishes no request limit for these APIs, so this stays modest.
    budget=Budget(rate_per_s=25 / 60, capacity=5, upstream_limit="none published"),
    cache_ttls_s={
        "addresses": 86_400,
        "places": 86_400,
        "types": 604_800,
        "elevation": 604_800,
        "boundaries": 86_400,
    },
    covers=[
        (
            "Every official address in Norway from the cadastre: search by text, postcode or "
            "municipality, or find the addresses nearest a point"
        ),
        (
            "The central place-name register: mountains, lakes, farms, towns and more, with every "
            "approved spelling and language (Norwegian, Sámi, Kven)"
        ),
        "Terrain elevation, lake surface height and sea depth at up to 50 points",
        "Which municipality and county a point lies in, sea territory included",
    ],
    known_gaps=[
        "The address API returns at most the first 10,000 matches, and place names the first 5,000",
        "Elevation outside Norway and its waters is empty",
        "Sea depths are interpolated and must not be used for navigation",
        "Cadastral property data beyond the address (owners, areas) is not included",
    ],
)
