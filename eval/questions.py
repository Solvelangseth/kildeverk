"""The evaluation set: realistic questions an agent should answer with Kildeverk's tools.

Each question has a reference call (the tool and arguments that answer it) and a rule that
pulls the answer out of that call's result. `build_truth.py` runs the reference calls live and
stores the answers; the runner then asks a model the question with only Kildeverk's tools and
scores what it submits. The reference call is never shown to the model.

Answers are about data that does not change (past dates, fixed periods) wherever possible.
Those marked `moves=True` follow the latest figures and are re-checked when truth is rebuilt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    tool: str
    arguments: dict[str, Any]
    extract: Callable[[dict[str, Any]], Any]
    kind: str = "number"  # "number" or "text"
    tolerance: float = 0.0  # relative, for numbers
    category: str = "lookup"
    moves: bool = False
    tools: tuple[str, ...] = field(default=())
    """Tools a good answer is expected to use; the reference tool is always one."""


def first(rows: list[dict[str, Any]], **match: Any) -> dict[str, Any]:
    return next(r for r in rows if all(r.get(k) == v for k, v in match.items()))


QUESTIONS: list[Question] = [
    # --- statistics -----------------------------------------------------------------
    Question(
        "s01",
        "How many people lived in Norway on 1 January 2025, according to Statistics Norway?",
        "statistics_get_data",
        {
            "table_id": "07459",
            "select": {"Region": ["0"], "ContentsCode": ["Personer1"], "Tid": ["2025"]},
        },
        lambda r: r["data"]["rows"][0]["value"],
    ),
    Question(
        "s02",
        "How many people lived in Tromsø in 2010, counted within today's municipal borders?",
        "statistics_series",
        {"table_id": "07459", "region": "Tromsø", "from_year": 2010},
        lambda r: first(r["data"]["points"], period="2010")["value"],
        category="reform",
    ),
    Question(
        "s03",
        "What was the population density (people per km² of land) of Tromsø municipality in 2007, "
        "for the area that is Tromsø today?",
        "statistics_series",
        {
            "table_id": "11342",
            "region": "5501",
            "measure": "FolkeLandArealKm2",
            "measure_kind": "non_additive",
        },
        lambda r: first(r["data"]["points"], period="2007")["value"],
        category="reform",
    ),
    Question(
        "s04",
        "Among Norwegian municipalities with at least 10,000 inhabitants, which grew fastest in "
        "population from 2015 to the latest year?",
        "statistics_rank",
        {"table_id": "07459", "compare_to": "2015", "min_value": 10000, "limit": 1},
        lambda r: r["data"]["rows"][0]["name"],
        kind="text",
        category="derived",
        moves=True,
    ),
    Question(
        "s05",
        "Which Norwegian county has the fewest inhabitants in the latest year?",
        "statistics_rank",
        {"table_id": "07459", "level": "county", "order": "lowest", "limit": 1},
        lambda r: r["data"]["rows"][0]["name"].split(" - ")[0],
        kind="text",
        category="derived",
        moves=True,
    ),
    # --- regions --------------------------------------------------------------------
    Question(
        "r01",
        "What is Bergen's municipality number today?",
        "regions_resolve",
        {"query": "Bergen", "level": "municipality"},
        lambda r: first(r["data"]["matches"], status="current")["code"],
        kind="text",
    ),
    Question(
        "r02",
        "The former municipality of Skoger merged into which of today's municipalities?",
        "regions_resolve",
        {"query": "Skoger", "level": "municipality"},
        lambda r: r["data"]["matches"][0]["today"][0]["name"],
        kind="text",
        category="reform",
    ),
    Question(
        "r03",
        "Which municipality is the point 59.0° N, 5.0° E in?",
        "regions_at_point",
        {"lat": 59.0, "lon": 5.0},
        lambda r: r["data"]["municipality"],
        kind="text",
    ),
    Question(
        "r04",
        "What was the municipality number of central Tromsø (69.65° N, 18.96° E) on 1 June 2019?",
        "regions_at_point",
        {"lat": 69.65, "lon": 18.96, "date": "2019-06-01"},
        lambda r: r["data"]["at_date"]["municipalities"][0]["code"],
        kind="text",
        category="reform",
    ),
    # --- companies ------------------------------------------------------------------
    Question(
        "c01",
        "What is Equinor ASA's organisation number?",
        "companies_search",
        {"name": "equinor", "limit": 5},
        lambda r: first(r["data"]["companies"], name="EQUINOR ASA")["org_number"],
        kind="text",
    ),
    Question(
        "c02",
        "Which organisation in Tromsø municipality has the most employees in the business register?",
        "companies_search",
        {"municipality": ["5501"], "sort": "most_employees", "limit": 1},
        lambda r: r["data"]["companies"][0]["name"],
        kind="text",
        moves=True,
        tools=("regions_resolve",),
    ),
    # --- weather and water ----------------------------------------------------------
    Question(
        "w01",
        "What was the daily mean temperature at Oslo - Blindern on 1 January 2024?",
        "weather_observations",
        {
            "station": "SN18700",
            "elements": ["daily_mean_temperature"],
            "start": "2024-01-01",
            "end": "2024-01-02",
        },
        lambda r: r["data"]["rows"][0]["value"],
        tolerance=0.001,
        tools=("weather_find_stations",),
    ),
    Question(
        "w02",
        "What was the highest weather warning level MET Norway issued for heavy rain in August 2023 "
        "(storm Hans)? Answer with the colour.",
        "weather_warnings",
        {"month": "2023-08", "min_level": 1},
        lambda r: {1: "green", 2: "yellow", 3: "orange", 4: "red"}[
            max(w["highest_level"] for w in r["data"]["warnings"] if "rain" in w["event"].lower())
        ],
        kind="text",
    ),
    Question(
        "w03",
        "What flood warning level did NVE give Ringerike municipality on 8 August 2023? Answer with "
        "the colour.",
        "hazards_flood_landslide",
        {
            "municipality": "3305",
            "kinds": ["flood"],
            "start": "2023-08-08",
            "end": "2023-08-08",
            "min_level": 1,
        },
        lambda r: r["data"]["warnings"][0]["level_name"],
        kind="text",
    ),
    Question(
        "w04",
        "What avalanche danger level (1-5) did Varsom forecast for the Tromsø region on 10 March 2026?",
        "hazards_avalanche",
        {"region": 3011, "start": "2026-03-10"},
        lambda r: r["data"]["forecasts"][0]["level"],
    ),
    Question(
        "w05",
        "What is the mean annual flood (peak discharge, m³/s) at NVE's Bulken gauging station on the "
        "Vosso river?",
        "water_find_stations",
        {"station": "62.5.0"},
        lambda r: r["data"]["stations"][0]["flood_statistics"]["mean_annual"],
        tolerance=0.01,
    ),
    Question(
        "w06",
        "What was the observed sea level at Bergen at 00:00 Norwegian time on 27 October 2026, in cm "
        "above chart datum?",
        "sea_level",
        {"station": "BGO", "start": "2026-10-27T00:00", "end": "2026-10-27T01:00"},
        lambda r: first(r["data"]["series"], type="observation")["points"][0]["cm"],
        tolerance=0.01,
    ),
    Question(
        "w07",
        "How full were the hydropower reservoirs in price area NO2 in week 1 of 2022, in per cent?",
        "energy_reservoirs",
        {"areas": ["NO2"], "from_year": 2022, "to_year": 2022},
        lambda r: first(r["data"]["rows"], week=1)["fill_pct"],
        tolerance=0.005,
    ),
    # --- maps -----------------------------------------------------------------------
    Question(
        "m01",
        "How high above sea level is the summit of Galdhøpiggen, according to Kartverket's terrain "
        "model, in metres?",
        "terrain_elevation",
        {"points": [{"lat": 61.63644, "lon": 8.31248}]},
        lambda r: r["data"]["points"][0]["elevation_m"],
        tolerance=0.002,
        tools=("places_search",),
    ),
    Question(
        "m02",
        "What is the postcode of Karl Johans gate 22 in Oslo?",
        "addresses_search",
        {"query": "Karl Johans gate 22 Oslo"},
        lambda r: r["data"]["addresses"][0]["postcode"],
        kind="text",
    ),
    Question(
        "m03",
        "What is the Northern Sámi name of Kautokeino?",
        "places_search",
        {"query": "Kautokeino", "limit": 3},
        lambda r: first(
            first(r["data"]["places"], type="Tettsted")["names"], language="Nordsamisk"
        )["name"],
        kind="text",
    ),
    # --- money ----------------------------------------------------------------------
    Question(
        "f01",
        "What was Norges Bank's monthly average EUR/NOK exchange rate for January 2025?",
        "currency_exchange_rates",
        {"currencies": ["EUR"], "frequency": "monthly", "start": "2025-01-01", "end": "2025-01-31"},
        lambda r: r["data"]["rows"][0]["nok"],
        tolerance=0.0001,
    ),
    Question(
        "f02",
        "What did Norges Bank's key policy rate become on 16 December 2022, in per cent?",
        "rates_policy_rate",
        {"since": "2022-01-01"},
        lambda r: first(r["data"]["changes"], effective="2022-12-16")["rate"],
    ),
    Question(
        "f03",
        "How many kroner did one Japanese yen cost by Norges Bank's rate on 27 October 2026?",
        "currency_exchange_rates",
        {"currencies": ["JPY"], "start": "2026-10-27", "end": "2026-10-27"},
        lambda r: r["data"]["rows"][0]["nok_per_unit"],
        tolerance=0.001,
        category="derived",
    ),
    # --- parliament, schools, traffic -----------------------------------------------
    Question(
        "p01",
        "How many members of Stortinget voted for the committee's recommendation on the 2025-2026 "
        "proposal to curb rising energy prices and living costs (vote 28502)?",
        "parliament_case",
        {"case_id": 200084},
        lambda r: first(r["data"]["votes"], id=28502)["for_count"],
        tools=("parliament_cases",),
    ),
    Question(
        "p02",
        "How many representatives did SV have in Stortinget in the 2021-2025 period, as listed for "
        "that period?",
        "parliament_members",
        {"period": "2021-2025", "party": "SV"},
        lambda r: r["data"]["count"],
    ),
    Question(
        "e01",
        "How many pupils does Alvøen skole in Bergen have, according to the National School Register?",
        "schools_get",
        {"org_number": "874738352"},
        lambda r: r["data"]["pupils"],
        moves=True,
        tools=("schools_search",),
    ),
    Question(
        "t01",
        "How many vehicles passed the Nygårdstunnelen - Bergen sentrum counting point on 20 October "
        "2026?",
        "traffic_volumes",
        {"point": "09194V804833", "start": "2026-10-20", "end": "2026-10-20"},
        lambda r: r["data"]["rows"][0]["vehicles"],
        tools=("traffic_find_points",),
    ),
    Question(
        "t02",
        "What was the annual average daily traffic (ÅDT) at the Nygårdstunnelen - Bergen sentrum "
        "counting point in 2019?",
        "traffic_volumes",
        {
            "point": "09194V804833",
            "resolution": "annual",
            "start": "2019-01-01",
            "end": "2019-12-31",
        },
        lambda r: first(r["data"]["rows"], year=2019)["vehicles"],
        tools=("traffic_find_points",),
    ),
    # --- combined -------------------------------------------------------------------
    Question(
        "x01",
        "How many active schools does the National School Register list in Bergen municipality?",
        "municipality_profile",
        {"municipality": "Bergen"},
        lambda r: r["data"]["schools"]["total"],
        moves=True,
        tools=("schools_search",),
    ),
    Question(
        "x02",
        "Of Bergen, Trondheim and Stavanger, which has the most registered companies per 1,000 "
        "inhabitants?",
        "compare_municipalities",
        {"municipalities": ["Bergen", "Trondheim", "Stavanger"]},
        lambda r: max(r["data"]["rows"], key=lambda x: x["companies_per_1000"])["name"].split(
            " - "
        )[0],
        kind="text",
        category="derived",
        moves=True,
    ),
    Question(
        "x03",
        "Which public transport stop is nearest to the point 60.3913° N, 5.3221° E in Bergen?",
        "transit_find_stops",
        {"lat": 60.3913, "lon": 5.3221, "radius_km": 0.5, "limit": 1},
        lambda r: r["data"]["stops"][0]["name"],
        kind="text",
        tools=("place_overview",),
    ),
]
