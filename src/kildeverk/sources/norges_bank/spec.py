from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://data.norges-bank.no/api/data"
OPEN_DATA_URL = "https://www.norges-bank.no/en/topics/Statistics/open-data/"

SPEC = SourceSpec(
    id="norges_bank",
    name="Norges Bank open data",
    publisher="Norges Bank",
    homepage="https://www.norges-bank.no/",
    docs_url=OPEN_DATA_URL,
    terms_url=OPEN_DATA_URL,
    # Norges Bank publishes the API as open data but states no licence or terms.
    licence=Licence(
        id="not-stated",
        name="No licence stated by the publisher",
        url=OPEN_DATA_URL,
    ),
    budget=Budget(rate_per_s=25 / 60, capacity=5, upstream_limit="none published"),
    cache_ttls_s={"recent": 3_600, "historic": 86_400, "currencies": 86_400},
    covers=[
        (
            "Norges Bank's exchange rates against the krone for about 40 currencies and indices, "
            "daily since 1999 (some earlier), with monthly and annual averages"
        ),
        "The key policy rate: its current level, when it last changed, and every change since",
    ],
    known_gaps=[
        "Norges Bank states no licence for this data; results say so",
        "Rates are published around 16:00 Norwegian time on business days, for that day",
        "Other interest rates (NOWA, government bonds) are not exposed yet",
    ],
)
