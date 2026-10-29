from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

GRAPHQL_URL = "https://trafikkdata-api.atlas.vegvesen.no/"

SPEC = SourceSpec(
    id="vegvesen_traffic",
    name="Statens vegvesen traffic data",
    publisher="Norwegian Public Roads Administration (Statens vegvesen)",
    homepage="https://trafikkdata.atlas.vegvesen.no/",
    docs_url="https://trafikkdata.atlas.vegvesen.no/#/om-api",
    terms_url="https://dataut.vegvesen.no/en/dataset/trafikkdata",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    budget=Budget(rate_per_s=25 / 60, capacity=5, upstream_limit="none published"),
    cache_ttls_s={"points": 86_400, "recent": 900, "historic": 86_400, "averages": 86_400},
    covers=[
        (
            "About 10,000 traffic registration points on Norwegian roads and cycle paths, with "
            "road, municipality, position and how long each has counted"
        ),
        (
            "Vehicles per hour or per day at a point, by direction and by vehicle length, and "
            "the annual average daily traffic (ÅDT) for every year counted"
        ),
    ],
    known_gaps=[
        "Hourly is the finest resolution; single vehicles and speeds are not public",
        "Counts are only as complete as their coverage, which each row gives",
        "Traffic indices are not exposed yet; road_at_point reads the national road database",
    ],
)
