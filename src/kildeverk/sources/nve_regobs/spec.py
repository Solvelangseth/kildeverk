from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

BASE_URL = "https://api.regobs.no/v5"
REGISTRATION_PAGE = "https://www.regobs.no/registration/{reg_id}"

SPEC = SourceSpec(
    id="nve_regobs",
    name="Regobs field observations",
    publisher="Norwegian Water Resources and Energy Directorate (NVE), via regobs.no",
    homepage="https://www.regobs.no/",
    docs_url="https://api.regobs.no/v5/swagger/ui/index",
    # "Data som ligger på api.nve.no er lisensiert under ... (NLOD)", and Regobs requires that
    # "Regobs.no is credited" and "the observer/user that registered the data is credited using
    # the username".
    terms_url="https://api.nve.no/doc/regobs/",
    licence=Licence(
        id="NLOD-2.0",
        name="Norwegian Licence for Open Government Data 2.0 (credit: Regobs.no and the observer)",
        url="https://data.norge.no/nlod/en/2.0",
    ),
    budget=Budget(rate_per_s=30 / 60, capacity=5, upstream_limit="none published"),
    cache_ttls_s={"recent": 600, "past": 86_400},
    covers=[
        (
            "Field observations of snow and avalanches, landslides, floods and ice from Regobs, "
            "the observation system behind varsom.no: what was seen, where and when, by NVE's "
            "observers and the public"
        ),
        (
            "Each observation's text summaries (avalanche activity, danger signs, snow cover, "
            "ice thickness, water level and more), its place and municipality, the observer's "
            "username and competence level, and a link to it on regobs.no"
        ),
    ],
    known_gaps=[
        "Observations are what people report; Regobs publishes them as they are",
        "Pictures are counted and linked through the observation's page, not returned",
        (
            "Regobs requires that each observer is credited by username, so usernames are "
            "returned; nothing else about observers is, and a username that is an e-mail "
            "address is cut so that it no longer is one"
        ),
    ],
)
