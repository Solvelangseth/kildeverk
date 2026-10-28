from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://data.ssb.no/api/pxwebapi/v2"

# SSB publishes 800,000 cells per extraction. This service returns at most this
# many rows per call, so one answer stays readable by a person or a model.
MAX_ROWS = 10_000

SPEC = SourceSpec(
    id="ssb_statbank",
    name="SSB Statbank",
    publisher="Statistics Norway (SSB)",
    homepage="https://www.ssb.no/en/statbank",
    docs_url="https://www.ssb.no/en/api/pxwebapi",
    terms_url="https://www.ssb.no/en/diverse/lisens",
    licence=Licence(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International",
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    # 5 + 60 * 20/60 = at most 25 calls in any minute, under SSB's 30.
    budget=Budget(
        rate_per_s=20 / 60,
        capacity=5,
        upstream_limit="30 queries per 60 seconds per IP address; 800,000 cells per query",
    ),
    cache_ttls_s={
        "search": 3_600,
        "metadata": 3_600,
        "codelist": 86_400,
        # Data entries are keyed on the table's `updated` timestamp as well, so a
        # table that SSB republishes is refetched as soon as its metadata expires.
        "data": 86_400,
    },
    covers=[
        "Search across all published Statbank tables, in English or Norwegian",
        "Table metadata: dimensions, value codes, units, aggregation codelists, footnotes",
        "Data for any selection of a table, returned as labelled rows",
    ],
    known_gaps=[
        "Search is SSB's own keyword search; it matches words, not meaning",
        "English search only matches English table titles, so Norwegian terms need lang='no'",
        "Codes are not checked for dimensions queried through a codelist; SSB checks them",
        f"At most {MAX_ROWS:,} rows per call; narrow the selection for more",
        "Tables from other PxWeb publishers (e.g. the Norwegian Directorate of Health) are not included",
    ],
)
