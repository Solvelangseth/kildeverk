from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

FLOOD_URL = "https://api01.nve.no/hydrology/forecast/flood/v1.0.10/api"
LANDSLIDE_URL = "https://api01.nve.no/hydrology/forecast/landslide/v1.0.10/api"
AVALANCHE_URL = "https://api01.nve.no/hydrology/forecast/avalanche/v6.3.2/api"

SPEC = SourceSpec(
    id="nve_varsom",
    name="NVE Varsom warnings",
    publisher="Norwegian Water Resources and Energy Directorate (NVE), via varsom.no",
    homepage="https://www.varsom.no/",
    docs_url="https://api.nve.no/doc/flomvarsling/",
    terms_url="https://api.nve.no/doc/flomvarsling/",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    budget=Budget(rate_per_s=25 / 60, capacity=5, upstream_limit="none published"),
    cache_ttls_s={"current": 600, "historic": 86_400, "regions": 604_800},
    covers=[
        (
            "Flood and landslide warnings for every municipality: level (green to red), period, "
            "the warning, its causes, consequences and advice"
        ),
        (
            "Avalanche forecasts for every forecasting region: danger level, avalanche problems "
            "with aspects and heights, and advice"
        ),
    ],
    known_gaps=[
        (
            "Avalanche forecasts are only published in winter; outside the season every region "
            "says 'No Rating' (level 0)"
        ),
        "Some avalanche texts are published in Norwegian only, even when English is asked for",
        (
            "Warnings are forecasts; NVE gives no guarantee of timeliness, so check varsom.no "
            "before acting on them"
        ),
    ],
)
