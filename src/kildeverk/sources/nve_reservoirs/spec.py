from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk"

SPEC = SourceSpec(
    id="nve_reservoirs",
    name="NVE reservoir statistics",
    publisher="Norwegian Water Resources and Energy Directorate (NVE)",
    homepage="https://www.nve.no/energi/analyser-og-statistikk/magasinstatistikk/",
    docs_url="https://biapi.nve.no/magasinstatistikk/swagger/index.html",
    terms_url="https://api.nve.no/doc/magasinstatistikk/",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    budget=Budget(rate_per_s=10 / 60, capacity=3, upstream_limit="none published"),
    # Published weekly (Wednesdays); the full history is one response, kept for a few hours.
    cache_ttls_s={"latest": 3_600, "history": 21_600, "areas": 604_800},
    covers=[
        (
            "How full Norway's hydropower reservoirs are, weekly since 1995: share of capacity "
            "and TWh, for the whole country and each electricity price area (NO1-NO5)"
        ),
        "The lowest, median and highest fill for each week over the last 20 years",
    ],
    known_gaps=[
        "Weekly figures only, published on Wednesdays for the week before",
        "Individual reservoirs are not published; only area totals",
    ],
)
