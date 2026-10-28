from kildeverk.core.envelope import Licence
from kildeverk.core.source import Budget, SourceSpec

PUBLISHER = "Norwegian Meteorological Institute (MET Norway)"

FORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
METALERTS_URL = "https://api.met.no/weatherapi/metalerts/2.0"
FROST_URL = "https://frost.met.no"
FROST_CREDENTIALS_URL = "https://frost.met.no/auth/requestCredentials.html"

# MET asks for at most 4 decimals. Three (about 110 m) is plenty for a forecast
# and lets nearby requests share one cached response.
COORDINATE_DECIMALS = 3

FROST_CC_BY_3_NO = Licence(
    id="CC-BY-3.0-NO",
    name="Creative Commons Attribution 3.0 Norway",
    url="https://creativecommons.org/licenses/by/3.0/no/",
)

LOCATIONFORECAST = SourceSpec(
    id="met_locationforecast",
    name="MET Norway Locationforecast",
    publisher=PUBLISHER,
    homepage="https://api.met.no/",
    docs_url="https://api.met.no/weatherapi/locationforecast/2.0/documentation",
    terms_url="https://api.met.no/doc/License",
    licence=Licence(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International (also offered under NLOD 2.0)",
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    # MET allows 20 requests per second per application; this service stays far below.
    budget=Budget(
        rate_per_s=50 / 60,
        capacity=10,
        upstream_limit="20 requests per second per application; respect Expires; "
        "identify with User-Agent; at most 4 coordinate decimals",
    ),
    cache_ttls_s={"forecast": 1_800},
    honour_expires=True,
    covers=[
        (
            "Weather forecast for any point: temperature, precipitation, wind, cloud, humidity, "
            "pressure and a weather symbol, hourly for about 2.5 days and 6-hourly to 9-10 days"
        ),
    ],
    known_gaps=[
        "Coordinates are rounded to 3 decimals (about 110 m) before the request",
        "Uses the compact product; probabilistic (percentile) values are not included",
        "Warnings (MetAlerts) and ocean forecasts are not included",
    ],
)

FROST = SourceSpec(
    id="met_frost",
    name="MET Norway Frost",
    publisher=PUBLISHER,
    homepage=FROST_URL,
    docs_url=f"{FROST_URL}/howto.html",
    terms_url="https://api.met.no/doc/License",
    # Every Frost response states this licence, so it is what each result cites.
    licence=FROST_CC_BY_3_NO,
    budget=Budget(rate_per_s=25 / 60, capacity=5, upstream_limit="none published"),
    cache_ttls_s={"stations": 86_400, "series": 86_400, "recent": 600, "historic": 86_400},
    requires_env=["KILDEVERK_FROST_CLIENT_ID"],
    covers=[
        "Weather stations: find by position or name, with location, elevation and operator",
        "What each station measures, and since when",
        (
            "Observations and daily or hourly aggregates: temperature, precipitation, wind, snow "
            "depth, humidity, pressure and hundreds of other elements"
        ),
    ],
    known_gaps=[
        "Needs a free Frost client id; without one these tools answer NOT_CONFIGURED",
        "Only open data: series that need Frost's client secret are not available",
        "Fresh observations can take an hour or more to appear",
        (
            "Frost states CC BY 3.0 Norway on every response, while MET's general licence page "
            "says NLOD 2.0 and CC BY 4.0; results cite what Frost states"
        ),
    ],
)

METALERTS = SourceSpec(
    id="met_metalerts",
    name="MET Norway MetAlerts",
    publisher=PUBLISHER,
    homepage="https://api.met.no/",
    docs_url="https://api.met.no/weatherapi/metalerts/2.0/documentation",
    terms_url="https://api.met.no/doc/License",
    licence=LOCATIONFORECAST.licence,
    budget=Budget(
        rate_per_s=50 / 60,
        capacity=10,
        upstream_limit="20 requests per second per application; respect Expires; "
        "identify with User-Agent",
    ),
    cache_ttls_s={"current": 300, "archive": 86_400},
    honour_expires=True,
    covers=[
        (
            "Official weather warnings for land and sea: wind, gale, rain, snow, ice, storm "
            "surge, forest fire danger, polar lows and more, with level, area and advice"
        ),
        "The archive of past warnings, month by month",
    ],
    known_gaps=[
        (
            "County codes are those in force when a warning was issued, so warnings before 2024 "
            "use the 2020 counties"
        ),
        "Warning areas are returned as names, not polygons",
    ],
)
