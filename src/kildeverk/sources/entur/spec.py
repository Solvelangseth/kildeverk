from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

PUBLISHER = "Entur AS"

GEOCODER_URL = "https://api.entur.io/geocoder/v3"
JOURNEY_PLANNER_URL = "https://api.entur.io/journey-planner/v3/graphql"
TERMS_URL = "https://developer.entur.org/pages-intro-authentication"

NLOD = Licence(
    id="NLOD-2.0",
    name="Norwegian Licence for Open Government Data 2.0",
    url="https://data.norge.no/nlod/en/2.0",
)

GEOCODER = SourceSpec(
    id="entur_geocoder",
    name="Entur Geocoder (stop places)",
    publisher=PUBLISHER,
    homepage="https://developer.entur.org/",
    docs_url="https://developer.entur.no/docs/open-services/geocoder",
    terms_url=TERMS_URL,
    licence=NLOD,
    # Entur allows 1000 requests a minute to the geocoder per client name.
    budget=Budget(
        rate_per_s=50 / 60,
        capacity=10,
        upstream_limit="1000 requests per minute per ET-Client-Name, reported in rate-limit-* "
        "headers; clients must identify with ET-Client-Name",
    ),
    cache_ttls_s={"stops": 86_400},
    covers=[
        (
            "Every public transport stop place in Norway from the national stop register (NSR): "
            "find by name, near a point, or by municipality, with modes and stop types"
        ),
    ],
    known_gaps=[
        "Only NSR stop places; addresses, POIs and OpenStreetMap places are left out on purpose",
        "Groups of stop places (a whole city, say) are not returned",
    ],
)

JOURNEY_PLANNER = SourceSpec(
    id="entur_journeyplanner",
    name="Entur Journey Planner",
    publisher=PUBLISHER,
    homepage="https://developer.entur.org/",
    docs_url="https://developer.entur.org/pages-journeyplanner-journeyplanner",
    terms_url=TERMS_URL,
    licence=NLOD,
    # Entur allows 2000 requests per two minutes per client name.
    budget=Budget(
        rate_per_s=50 / 60,
        capacity=10,
        upstream_limit="2000 requests per 2 minutes per ET-Client-Name, reported in rate-limit-* "
        "headers; clients must identify with ET-Client-Name",
    ),
    # Real-time departures change by the minute; a short cache still absorbs bursts.
    cache_ttls_s={"departures": 30, "journeys": 60},
    covers=[
        (
            "Departures from any stop place or quay in Norway, for every operator: scheduled and "
            "real-time times, platform, line, destination, cancellations and disruption notices"
        ),
        (
            "Journeys from A to B by stop, name or coordinates: every leg with line, platforms, "
            "real-time times, walking and changes"
        ),
    ],
    known_gaps=[
        "Real-time coverage depends on the operator; rows say whether a time is real-time",
        "Departures are cached for 30 seconds",
    ],
)
