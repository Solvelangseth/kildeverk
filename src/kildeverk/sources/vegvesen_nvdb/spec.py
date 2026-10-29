from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://nvdbapiles.atlas.vegvesen.no"

SPEC = SourceSpec(
    id="vegvesen_nvdb",
    name="Nasjonal vegdatabank (NVDB)",
    publisher="Norwegian Public Roads Administration (Statens vegvesen)",
    homepage="https://www.vegvesen.no/fag/teknologi/nasjonal-vegdatabank/",
    docs_url="https://nvdb-docs.atlas.vegvesen.no/",
    # data.norge.no lists "Nasjonal vegdatabank API" under "Norwegian Licence for Open Government
    # Data (NLOD) 2.0", with general access. The API rate-limits, and refuses requests without an
    # X-Client header naming the client.
    terms_url="https://data.norge.no/datasets/e52c9fbc-1cf2-3910-97c1-425cd5c2304e",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    budget=Budget(
        rate_per_s=2,
        capacity=12,
        upstream_limit="a rate limiter, not published; an X-Client header is required",
    ),
    cache_ttls_s={"position": 86_400, "objects": 86_400},
    covers=[
        (
            "The road at any point in Norway: its road reference (E, R, F, K, P), speed limit, "
            "annual average daily traffic, signed height limit, and whether it is on a bridge "
            "or in a tunnel, with their names"
        ),
    ],
    known_gaps=[
        "Only the road nearest the point that carries vehicles; footpaths and cycle paths are skipped",
        (
            "A point above a tunnel finds the road on the surface; give a point on the tunnel's "
            "road at its entrance"
        ),
        "Other road objects (lanes, weight limits, road works, rest areas) are not exposed yet",
    ],
)
