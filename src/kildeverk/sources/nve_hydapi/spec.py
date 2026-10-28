from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://hydapi.nve.no/api/v1"
DOCS_URL = "https://hydapi.nve.no/UserDocumentation/"
KEY_URL = "https://hydapi.nve.no/Users"

SPEC = SourceSpec(
    id="nve_hydapi",
    name="NVE HydAPI",
    publisher="Norwegian Water Resources and Energy Directorate (NVE)",
    homepage="https://www.nve.no/",
    docs_url=DOCS_URL,
    terms_url=f"{DOCS_URL}#license",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    # HydAPI allows 5 requests per second per key; this service stays well below.
    budget=Budget(
        rate_per_s=50 / 60,
        capacity=10,
        upstream_limit="5 requests per second per API key; a cap on data points per request",
    ),
    cache_ttls_s={"stations": 14_400, "recent": 600, "historic": 86_400},
    requires_env=["KILDEVERK_NVE_API_KEY"],
    covers=[
        (
            "NVE's hydrological stations: rivers, lakes, groundwater and snow, with location, "
            "catchment and flood statistics"
        ),
        (
            "Observed discharge, water level, water temperature, snow, groundwater and more, as "
            "raw readings or hourly and daily means, back to the start of each series"
        ),
    ],
    known_gaps=[
        "Needs a free HydAPI key; without one these tools answer NOT_CONFIGURED",
        "The newest values are uncontrolled and can be revised; each row says how far it has been checked",
        "Rating curves and percentiles are not exposed yet",
        "Flood and landslide warnings are a different NVE service and are not included",
    ],
)
