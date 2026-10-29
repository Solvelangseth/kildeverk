from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://ord.uib.no"
ARTICLE_PAGE = "https://ordbokene.no/{dictionary}/{article_id}"
# The credit UiB asks for, word for word.
CREDIT = (
    "Bokmålsordboka/Nynorskordboka, Universitetet i Bergen og Språkrådet, ordbøkene.no, CC-BY 4.0"
)

SPEC = SourceSpec(
    id="ordbokene",
    name="Bokmålsordboka and Nynorskordboka (ordbøkene.no)",
    publisher="University of Bergen and the Language Council of Norway (Språkrådet)",
    homepage="https://ordbokene.no/",
    docs_url=f"{BASE_URL}/",
    # "Bokmålsordboka og Nynorskordboka er tilgjengelege under lisensen CC BY 4.0", for content
    # and for "data henta gjennom API-et", with the credit above.
    terms_url="https://www.uib.no/en/node/182212",
    licence=Licence(
        id="CC-BY-4.0",
        name=f"Creative Commons Attribution 4.0 International (credit: {CREDIT})",
        url="https://creativecommons.org/licenses/by/4.0/deed.no",
    ),
    budget=Budget(rate_per_s=2, capacity=12, upstream_limit="none published"),
    cache_ttls_s={"search": 86_400, "article": 604_800, "concepts": 604_800},
    covers=[
        (
            "The official Bokmål and Nynorsk dictionaries: a word's meanings, examples, "
            "inflection (every standard form), word class and gender, and its origin"
        ),
        "Similar spellings when a word is not found",
    ],
    known_gaps=[
        "Norwegian only; meanings are explained in Norwegian",
        "Compound words that are not in the dictionary are not split or explained",
    ],
)
