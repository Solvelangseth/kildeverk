from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

EVENTS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

SPEC = SourceSpec(
    id="usgs_earthquakes",
    name="USGS Earthquake Catalog",
    publisher="U.S. Geological Survey (USGS)",
    homepage="https://earthquake.usgs.gov/",
    docs_url="https://earthquake.usgs.gov/fdsnws/event/1/",
    # "USGS-authored or produced data and information are considered to be in the U.S. Public
    # Domain", with credit to the U.S. Geological Survey requested.
    terms_url="https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
    licence=Licence(
        id="US-public-domain",
        name="U.S. Public Domain (credit: U.S. Geological Survey)",
        url="https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
    ),
    budget=Budget(rate_per_s=1, capacity=5, upstream_limit="at most 20,000 events per query"),
    cache_ttls_s={"recent": 600, "past": 86_400},
    covers=[
        (
            "Earthquakes worldwide from USGS's catalogue, near any point: time, magnitude, depth, "
            "place, whether USGS has reviewed it, how many people reported feeling it, and a "
            "link to its event page"
        ),
    ],
    known_gaps=[
        (
            "Outside the United States the catalogue misses many events below about magnitude "
            "4; the Norwegian National Seismic Network records smaller Norwegian earthquakes, "
            "but its licence is unclear, so it is not used"
        ),
        "Recent events are first automatic estimates and can be revised or deleted",
    ],
)
