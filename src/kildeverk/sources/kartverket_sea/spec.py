from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

TIDE_URL = "https://vannstand.kartverket.no/tideapi.php"
DOCS_URL = "https://vannstand.kartverket.no/tideapi_en.html"

SPEC = SourceSpec(
    id="kartverket_sea_level",
    name="Kartverket water level and tides",
    publisher="Norwegian Mapping Authority, Hydrographic Service (Kartverket)",
    homepage="https://www.kartverket.no/til-sjos/se-havniva",
    docs_url=DOCS_URL,
    terms_url=(
        "https://vannstand.kartverket.no/API%20for%20water%20level%20and%20tides%20-%20"
        "communication%20protocol_revJune2025.pdf"
    ),
    licence=Licence(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International (credit: Kartverket, "
        "Hydrographic Service)",
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    # Kartverket asks users not to poll heavily and to cache; no number is published.
    budget=Budget(
        rate_per_s=20 / 60,
        capacity=5,
        upstream_limit="none published; asks for caching and no heavy polling",
    ),
    cache_ttls_s={"recent": 900, "historic": 86_400},
    covers=[
        (
            "Water level anywhere on the Norwegian coast: observed at about 25 permanent tide "
            "gauges, modelled elsewhere, with tidal predictions, the weather's effect and a "
            "forecast a few days ahead"
        ),
        "Tide tables: the times and heights of high and low water",
    ],
    known_gaps=[
        "Away from a tide gauge every value is modelled; observations exist only at the gauges",
        "Positions inland or far offshore have no data",
        "Return levels (the 100-year storm surge and so on) are not exposed yet",
    ],
)
