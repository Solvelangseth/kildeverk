from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://data.ssb.no/api/klass/v1"
GUIDE_URL = f"{BASE_URL}/api-guide.html"

# Klass classification ids.
CLASSIFICATIONS = {"municipality": "131", "county": "104"}

# The history is read from this date. Municipality codes before it are unknown to
# the region tools, which say so rather than guess.
HISTORY_FROM = "1960-01-01"
# A fixed end keeps request URLs, and so cache keys and test fixtures, stable from
# day to day. Klass reports a code that is still valid with validTo equal to it.
HISTORY_TO = "2100-01-01"

SPEC = SourceSpec(
    id="ssb_klass",
    name="SSB Klass",
    publisher="Statistics Norway (SSB)",
    homepage="https://www.ssb.no/en/klass",
    docs_url=GUIDE_URL,
    terms_url=f"{GUIDE_URL}#_license",
    licence=Licence(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International",
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    # Klass publishes no limit. This service holds itself to the same budget as Statbank.
    budget=Budget(rate_per_s=20 / 60, capacity=5, upstream_limit="none published"),
    cache_ttls_s={"history": 86_400},
    covers=[
        "Every Norwegian municipality and county code since 1960, with names and validity periods",
        "Every code change: renumbering, renaming, mergers and splits, with dates",
        "Converting municipality or county series to the 2020 or 2024 borders, or any date",
    ],
    known_gaps=[
        (
            "Klass records changes of code, not every boundary adjustment between municipalities "
            "that keep their codes; those small transfers are invisible to harmonisation"
        ),
        (
            "A split cannot be converted exactly, because Klass says which areas a municipality "
            "split into but not how its population or other values divided"
        ),
        "Periods are read by year; a change in the middle of a year is placed in that year",
        "Codes valid only before 1960 are not known",
    ],
)
