from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://asrv.avinor.no"
# Avinor asks that content be labelled with this, linked to www.avinor.no, near the data.
CREDIT = "Flight data from Avinor (https://www.avinor.no)"

SPEC = SourceSpec(
    id="avinor",
    name="Avinor flight data",
    publisher="Avinor AS",
    homepage="https://avinor.no/",
    docs_url="https://partner.avinor.no/en/services/flight-data/",
    # "We do not impose any limitations on how data is used", within Norwegian law; label it
    # "Flight data from Avinor" linked to avinor.no; fetch flight times every 3 minutes at most
    # and cache them; Avinor may end access for uses that harm its reputation.
    terms_url="https://partner.avinor.no/en/services/flight-data/",
    licence=Licence(
        id="avinor-terms",
        name="Avinor's terms for flight data: free use, labelled 'Flight data from Avinor'",
        url="https://partner.avinor.no/en/services/flight-data/",
    ),
    budget=Budget(
        rate_per_s=20 / 60,
        capacity=5,
        upstream_limit="flight times every 3 minutes at most, names once a day; cache, and do not "
        "let end users reach Avinor directly",
    ),
    cache_ttls_s={"flights": 180, "names": 86_400},
    covers=[
        (
            "Departures and arrivals at Norwegian airports in Avinor's feed, from an hour ago to "
            "several hours ahead: flight number, airline, the other airport and any stop on the "
            "way, scheduled and new or actual times, gate, check-in, baggage belt, and whether "
            "it is delayed or cancelled"
        ),
    ],
    known_gaps=[
        (
            "Only airports in Avinor's feed: Avinor's own and some others, such as Sandefjord "
            "Torp; an airport outside it answers with no flights"
        ),
        "Flight times are at most three minutes old, by Avinor's own rule",
        "Avinor gives no guarantee that the content is complete or up to date",
    ],
)
