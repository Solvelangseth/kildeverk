from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://data.stortinget.no/eksport"

SPEC = SourceSpec(
    id="stortinget",
    name="Stortinget open data",
    publisher="Stortinget (the Norwegian parliament)",
    homepage="https://www.stortinget.no/",
    docs_url="https://data.stortinget.no/dokumentasjon-og-hjelp/",
    terms_url="https://data.stortinget.no/om-datatjenesten/bruksvilkar/",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0 (credit: Stortinget)",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    budget=Budget(
        rate_per_s=50 / 60, capacity=10, upstream_limit="100 requests per minute; 429 above"
    ),
    cache_ttls_s={"sessions": 86_400, "cases": 3_600, "case": 3_600, "people": 86_400},
    covers=[
        (
            "Every case before Stortinget by session: bills, budgets and other matters, with "
            "committee, status, type and the decision"
        ),
        (
            "How Stortinget voted on a case: each vote's result, counts, and how each party "
            "voted when votes were recorded by name"
        ),
        "The members of Stortinget: party, constituency and committees, now or for a period",
    ],
    known_gaps=[
        "Titles and texts are in Norwegian",
        "Many votes are by acclamation, with no counts or names; results say so",
        "Questions to ministers, hearings and debates are not exposed yet",
        "Contact details and birth dates of members are left out",
    ],
)
