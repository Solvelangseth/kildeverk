from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

SEARCH_URL = "https://search.api.fellesdatakatalog.digdir.no/search"
DOCS_URL = "https://search.api.fellesdatakatalog.digdir.no/swagger-ui.html"

SPEC = SourceSpec(
    id="datanorge",
    name="data.norge.no catalogue search",
    publisher="Norwegian Digitalisation Agency (Digdir), data.norge.no",
    homepage="https://data.norge.no/",
    docs_url=DOCS_URL,
    terms_url="https://data.norge.no/nb/about",
    # The search API's documentation states no licence for the catalogue metadata it returns.
    licence=Licence(
        id="not-stated",
        name="No licence stated for the catalogue metadata; each dataset states its own",
        url="https://data.norge.no/nb/about",
    ),
    budget=Budget(rate_per_s=10 / 60, capacity=3, upstream_limit="none published"),
    cache_ttls_s={"search": 3_600},
    covers=[
        (
            "Norway's national data catalogue: datasets and APIs described by public bodies, "
            "searchable by text, theme, publisher, format, open-data status and recent change"
        ),
    ],
    known_gaps=[
        "Finds descriptions of data, not the data itself; each result links to its catalogue page",
        "Quality depends on what each publisher wrote; titles and descriptions are often Norwegian",
        "Publisher filtering needs the organisation path that results carry, e.g. '/STAT/972417807/971526920'",
        "Concepts, information models and public services in the catalogue are not searched",
    ],
)
