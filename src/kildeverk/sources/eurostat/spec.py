from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination"
TOC_URL = f"{BASE_URL}/catalogue/toc/txt"
DATA_URL = f"{BASE_URL}/statistics/1.0/data"
# Countries whose Eurostat data are CC BY 4.0 for any use: the EU, EFTA and candidate countries.
# Data for others may be reused for non-commercial purposes only.
OPEN_GEO_PREFIXES = ("EU", "EA", "EFTA")
EFTA_AND_CANDIDATES = {
    "NO",
    "IS",
    "LI",
    "CH",
    "AL",
    "BA",
    "GE",
    "MD",
    "ME",
    "MK",
    "RS",
    "TR",
    "UA",
    "XK",
}

SPEC = SourceSpec(
    id="eurostat",
    name="Eurostat database",
    publisher="Eurostat (European Commission)",
    homepage="https://ec.europa.eu/eurostat",
    docs_url="https://wikis.ec.europa.eu/display/EUROSTATHELP/API+Statistics+-+data+query",
    # "Eurostat data ... CC BY 4.0", commercial reuse allowed with credit, no written licence
    # needed; data from non-Eurostat sources, and for countries outside the EU, EFTA and the
    # candidate countries, are for non-commercial use only.
    terms_url="https://ec.europa.eu/eurostat/web/main/help/copyright-notice",
    licence=Licence(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International (credit: Eurostat)",
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    budget=Budget(rate_per_s=1, capacity=10, upstream_limit="none published"),
    cache_ttls_s={"catalogue": 86_400, "data": 21_600},
    covers=[
        (
            "Eurostat's database: about 8,000 datasets on the economy, population, labour, "
            "prices, energy, environment, health, transport and more, for EU and EFTA countries "
            "(Norway included) and the EU as a whole, often by region"
        ),
        "Searching dataset titles, and any slice of a dataset as labelled rows",
    ],
    known_gaps=[
        (
            "Data for countries outside the EU, EFTA and candidate countries, and data Eurostat "
            "took from other sources, are for non-commercial use only; results flag such "
            "countries"
        ),
        "Searches match words in titles, not meaning",
        "A query returns at most 2,000 rows; filter the dataset's dimensions for less",
    ],
)
