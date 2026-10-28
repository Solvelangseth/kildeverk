from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://data-nsr.udir.no/v4"

SPEC = SourceSpec(
    id="udir_nsr",
    name="National School Register (NSR)",
    publisher="Norwegian Directorate for Education and Training (Udir)",
    homepage="https://nsr.udir.no/",
    docs_url="https://data-nsr.udir.no/swagger/index.html",
    terms_url="https://data-nsr.udir.no/swagger/index.html",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    budget=Budget(rate_per_s=25 / 60, capacity=5, upstream_limit="none published"),
    # NSR imports from the Central Coordinating Register nightly, 01:00-02:00.
    cache_ttls_s={"search": 21_600, "school": 21_600},
    covers=[
        (
            "Every primary and secondary school in Norway, public and private, plus Norwegian "
            "schools abroad: name, municipality, ownership, grades and number of pupils"
        ),
    ],
    known_gaps=[
        "Kindergartens are in a different register and are not included",
        "Pupil numbers are the register's latest figure, not a time series",
        "Results, staffing ratios and other school statistics are not included",
    ],
)
