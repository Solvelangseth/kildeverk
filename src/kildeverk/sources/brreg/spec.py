from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://data.brreg.no/enhetsregisteret/api"
DOCS_URL = f"{BASE_URL}/dokumentasjon/no/index.html"
# Pinned so that a new response version upstream cannot change these tools silently.
ACCEPT_UNIT = "application/vnd.brreg.enhetsregisteret.enhet.v2+json"
ACCEPT_SUBUNIT = "application/vnd.brreg.enhetsregisteret.underenhet.v2+json"
# Brreg refuses to page past this many results for one query.
MAX_RESULT_WINDOW = 10_000
REGISTER_PAGE = "https://virksomhet.brreg.no/nb/oppslag/enheter/{org_number}"

SPEC = SourceSpec(
    id="brreg",
    name="Enhetsregisteret (Brønnøysund Register Centre)",
    publisher="Brønnøysund Register Centre (Brønnøysundregistrene)",
    homepage="https://www.brreg.no/",
    docs_url=DOCS_URL,
    terms_url=DOCS_URL,
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    # 10 + 60 * 50/60 = at most 60 calls in any minute. Brreg publishes no limit.
    budget=Budget(rate_per_s=50 / 60, capacity=10, upstream_limit="none published"),
    cache_ttls_s={"unit": 3_600, "search": 900},
    covers=[
        (
            "Every registered legal entity in Norway: companies, sole proprietorships, associations, "
            "public bodies, with their organisation number"
        ),
        (
            "Name, legal form, industry, address and municipality, employee count, registration "
            "dates, share capital, bankruptcy and liquidation status, former names"
        ),
        "Sub-units (establishments) of an entity",
        "Search by name, municipality, industry, legal form, size and registration date",
    ],
    known_gaps=[
        "Roles (board members, managing director, auditors) are not included: they name people",
        "Phone numbers and e-mail addresses are left out on purpose, although Brreg publishes them",
        (
            "Industry codes are SN2025, which Brreg switched to in 2025; older SN2007 codes do not "
            "match, but a two-digit division prefix like '62' usually still finds the right firms"
        ),
        f"A search can page through at most {MAX_RESULT_WINDOW:,} results",
        "Annual accounts are a separate register; companies_accounts reads them",
    ],
)

ACCOUNTS_URL = "https://data.brreg.no/regnskapsregisteret/regnskap"

ACCOUNTS = SourceSpec(
    id="brreg_accounts",
    name="Regnskapsregisteret (Brønnøysund Register Centre)",
    publisher="Brønnøysund Register Centre (Brønnøysundregistrene)",
    homepage="https://www.brreg.no/",
    docs_url=f"{ACCOUNTS_URL}/v3/api-docs",
    # data.norge.no lists the open API as the distribution "Nøkkeltall fra årsregnskapet" under
    # NLOD 2.0: "Den åpne delen er tilgjengelig for alle".
    terms_url="https://data.norge.no/datasets/8132460c-91ab-3950-a54b-a54ee20c62e9",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    budget=Budget(rate_per_s=1, capacity=15, upstream_limit="none published"),
    # Accounts are filed once a year; a day is plenty.
    cache_ttls_s={"accounts": 86_400},
    covers=[
        (
            "Key figures from the annual accounts companies file, for the last three years: "
            "revenue, operating profit, profit before tax, tax, net result, assets, equity, debt "
            "and cash"
        ),
        (
            "Company accounts and, for parent companies, group accounts, with the currency, the "
            "accounting rules (Norwegian GAAP or IFRS) and whether they were audited"
        ),
    ],
    known_gaps=[
        "Only the last three years are open; Brreg sells older accounts",
        ("Public bodies, sole proprietorships and others that do not file accounts have none here"),
        "Notes, the board's report, the auditor's report and cash flow are not in the open API",
        "Figures are in the currency each company reports in; Equinor, for one, reports in USD",
        "Small companies may leave out lines such as sales revenue or tax; those are empty",
    ],
)
