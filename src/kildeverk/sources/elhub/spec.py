from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://api.elhub.no/energy-data/v0"

SPEC = SourceSpec(
    id="elhub",
    name="Elhub energy data",
    publisher="Elhub AS",
    homepage="https://elhub.no/",
    docs_url="https://api.elhub.no/",
    # The portal's "Terms of use": "Our APIs and datasets are licenced by CC BY 4.0", public
    # APIs "do not require any authorization", and "the rate limit is 5 calls per second per user".
    terms_url="https://api.elhub.no/",
    licence=Licence(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International (credit: Elhub)",
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    budget=Budget(
        rate_per_s=4,
        capacity=5,
        upstream_limit="5 calls per second per user (IP address); asks users not to overload it",
    ),
    # Rows for the last few days are still filling in; older ones change only when late meter
    # readings are corrected.
    cache_ttls_s={"recent": 3_600, "past": 86_400, "meta": 604_800},
    covers=[
        (
            "Electricity consumption in every municipality, hour by hour since 2021, split into "
            "private customers (homes and cabins), business (services) and industry, with the "
            "number of metering points"
        ),
        (
            "Installed production capacity in every municipality by kind: hydro, wind, solar, "
            "thermal and other, and how much of it sits with prosumers"
        ),
        (
            "Consumption and production in each electricity price area (NO1-NO5): consumption by "
            "households, cabins and primary, secondary and tertiary industry; production by hydro, "
            "wind, solar, thermal and other"
        ),
    ],
    known_gaps=[
        (
            "Elhub serves municipality consumption one day per request, so a call covers at most 31 "
            "days"
        ),
        (
            "Production per municipality is not given: Elhub's municipal production figures cover "
            "only prosumers, which would badly undercount places with power plants"
        ),
        (
            "Figures follow what grid companies report, and Elhub revises them as late or corrected "
            "meter readings arrive; the newest days are the least settled"
        ),
        "Exchange between price areas, 15-minute values and Norgespris figures are not exposed yet",
        "Datasets by industry code or by supplier need Maskinporten access and are not used",
    ],
)
