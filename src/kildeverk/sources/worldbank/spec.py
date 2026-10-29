from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://api.worldbank.org/v2"
WDI_SOURCE = "2"

SPEC = SourceSpec(
    id="worldbank_wdi",
    name="World Bank World Development Indicators",
    publisher="The World Bank",
    homepage="https://data.worldbank.org/",
    docs_url="https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
    # The World Development Indicators' catalogue entry: "License: Creative Commons Attribution
    # 4.0". Other World Bank datasets can carry other licences, so only WDI is served.
    terms_url="https://datacatalog.worldbank.org/search/dataset/0037712/World-Development-Indicators",
    licence=Licence(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International (credit: The World Bank, World "
        "Development Indicators)",
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    budget=Budget(rate_per_s=1, capacity=10, upstream_limit="none published"),
    cache_ttls_s={"data": 86_400, "indicator": 604_800},
    covers=[
        (
            "The World Bank's World Development Indicators for every country and region: GDP, "
            "population, life expectancy, unemployment, inflation, emissions, energy, health, "
            "education and about 1,400 more, yearly, to compare Norway with other countries"
        ),
    ],
    known_gaps=[
        (
            "Only the World Development Indicators: other World Bank datasets can carry other "
            "licences, so indicators from them are refused"
        ),
        "Yearly figures; the latest year is often one or two years back",
        "No search: give an indicator code, or one of the common names the tool lists",
    ],
)
