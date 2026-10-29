"""place_overview combines other tools; parts that fail become notes."""

from __future__ import annotations

import pytest

from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.sources import composite
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


def _prov(source_id: str) -> dict:
    return {
        "source_id": source_id,
        "source_name": source_id,
        "publisher": "p",
        "licence": {"id": "NLOD-2.0", "name": "NLOD", "url": "https://data.norge.no/nlod/en/2.0"},
        "request": {"method": "GET", "url": f"https://example.test/{source_id}", "body": None},
        "retrieved_at": "2026-10-28T12:00:00Z",
        "cache": {"hit": False, "age_s": 0},
        "citation": "c",
    }


PARTS = {
    "regions_at_point": {
        "data": {
            "municipality_code": "4601",
            "municipality": "Bergen",
            "county_code": "46",
            "county": "Vestland",
        },
        "provenance": [_prov("kartverket")],
    },
    "terrain_elevation": {
        "data": {"points": [{"elevation_m": 4.07}]},
        "provenance": [_prov("kartverket")],
    },
    "weather_forecast": {
        "data": {
            "points": [
                {
                    "time": "2026-10-28T14:00:00Z",
                    "temperature_c": 11.2,
                    "wind_speed_ms": 4.3,
                    "symbol": "rain",
                    "precipitation_mm": 1.5,
                },
                {
                    "time": "2026-10-28T15:00:00Z",
                    "temperature_c": 10.2,
                    "wind_speed_ms": 5.0,
                    "symbol": "rain",
                    "precipitation_mm": 1.2,
                },
            ]
        },
        "provenance": [_prov("met_locationforecast")],
    },
    "weather_warnings": {
        "data": {
            "warnings": [
                {"level_name": "yellow", "event": "Gale", "valid_to": "2026-10-29T13:00:00+00:00"}
            ]
        },
        "provenance": [_prov("met_metalerts")],
    },
    "transit_find_stops": {
        "data": {
            "stops": [
                {
                    "id": "NSR:StopPlace:30853",
                    "name": "Olav Kyrres gate",
                    "distance_km": 0.14,
                    "modes": ["bus"],
                }
            ]
        },
        "provenance": [_prov("entur_geocoder")],
    },
    "places_search": {
        "data": {"places": [{"name": "Nygårdsparken", "type": "Park", "distance_m": 874.0}]},
        "provenance": [_prov("kartverket")],
    },
    "hazards_flood_landslide": {
        "data": {
            "warnings": [
                {
                    "kind": "flood",
                    "level_name": "yellow",
                    "title": "Flood warning yellow level",
                    "valid_to": "2026-10-29T07:00:00+01:00",
                }
            ]
        },
        "provenance": [_prov("nve_varsom")],
    },
}


@pytest.fixture
def parts(monkeypatch):
    calls: list[tuple[str, dict]] = []
    failing: set[str] = set()

    async def fake(ctx, tool, arguments):
        calls.append((tool, arguments))
        if tool in failing:
            return ToolError(ErrorCode.UPSTREAM_UNAVAILABLE, f"{tool} is down.", retry_after_s=30)
        return PARTS[tool]

    monkeypatch.setattr(composite, "_part", fake)
    return calls, failing


async def test_overview_combines_every_part(ctx, parts):
    calls, _ = parts
    result = await OPS["place_overview"].invoke(ctx, {"lat": 60.3913, "lon": 5.3221})
    data = result["data"]
    assert data["municipality"]["name"] == "Bergen" and data["elevation_m"] == 4.07
    assert data["weather"]["next_6h_precipitation_mm"] == 2.7
    assert data["weather"]["next_6h_temperature_range_c"] == [10.2, 11.2]
    assert [w["kind"] for w in data["warnings"]] == ["weather", "flood"]
    assert data["nearest_stops"][0]["name"] == "Olav Kyrres gate"
    assert ("hazards_flood_landslide", {"municipality": "4601"}) in calls
    follow = {f["tool"] for f in data["follow_up"]}
    assert {"transit_departures", "schools_search", "companies_search"} <= follow
    assert {p["source_id"] for p in result["provenance"]} == {
        "kartverket",
        "met_locationforecast",
        "met_metalerts",
        "entur_geocoder",
        "nve_varsom",
    }
    assert result["notes"] == []


async def test_a_failing_part_becomes_a_note(ctx, parts):
    calls, failing = parts
    failing.update({"weather_forecast", "regions_at_point"})
    result = await OPS["place_overview"].invoke(ctx, {"lat": 60.3913, "lon": 5.3221})
    data = result["data"]
    assert data["weather"] is None and data["municipality"] is None
    assert data["nearest_stops"]  # the rest still answers
    assert any("No weather: weather_forecast is down." in n for n in result["notes"])
    assert any("flood and landslide warnings were not looked up" in n for n in result["notes"])
    assert "hazards_flood_landslide" not in {tool for tool, _ in calls}


async def test_a_point_at_sea_suggests_sea_level(ctx, parts, monkeypatch):
    monkeypatch.setitem(
        PARTS, "terrain_elevation", {"data": {"points": [{"elevation_m": -40.0}]}, "provenance": []}
    )
    result = await OPS["place_overview"].invoke(ctx, {"lat": 60.0, "lon": 5.0})
    assert "sea_level" in {f["tool"] for f in result["data"]["follow_up"]}


# --- municipality_profile ----------------------------------------------------------


def _match(code, name, status, today=(), exact=True):
    return {
        "code": code,
        "name": name,
        "status": status,
        "today": [{"code": c, "name": n} for c, n in today],
        "today_exact": exact,
    }


def test_pick_follows_reforms_and_refuses_guesses():
    assert composite._pick([_match("4601", "Bergen", "current")], "4601") == ("4601", "Bergen")
    old = [_match("1201", "Bergen", "ended", [("4601", "Bergen")])]
    assert composite._pick(old, "1201") == ("4601", "Bergen")
    # A current municipality wins over an ended one of the same name.
    os_ = [
        _match("3430", "Os", "current"),
        _match("1243", "Os", "ended", [("4624", "Bjørnafjorden")]),
    ]
    assert composite._pick(os_, "os") == ("3430", "Os")
    split = [_match("5001", "X", "ended", [("1", "A"), ("2", "B")], exact=False)]
    assert composite._pick(split, "5001").body.code == "NOT_FOUND"
    two = [_match("1", "Nes", "current"), _match("2", "Nes", "current")]
    error = composite._pick(two, "nes")
    assert error.body.code == "AMBIGUOUS" and error.body.next_call.arguments == {
        "municipality": "1"
    }


def test_population_ignores_placeholder_zeros():
    rows = [
        {"Tid": "2018", "value": 0},
        {"Tid": "2020", "value": 1000},
        {"Tid": "2025", "value": 1090},
        {"Tid": "2026", "value": 1100},
    ]
    people = composite._population(rows)
    assert people.latest == 1100 and people.change_since == "2020"
    assert people.change_since_pct == 10.0 and people.change_1y_pct == 0.92


async def test_profile_combines_sources(ctx, monkeypatch):
    def school(total):
        return {"data": {"total_matches": total, "schools": []}, "provenance": [_prov("udir_nsr")]}

    answers = {
        "regions_resolve": {
            "data": {"matches": [_match("1201", "Bergen", "ended", [("4601", "Bergen")])]},
            "provenance": [_prov("ssb_klass")],
        },
        "statistics_get_data": {
            "data": {"rows": [{"Tid": "2025", "value": 293709}, {"Tid": "2026", "value": 294860}]},
            "provenance": [_prov("ssb_statbank")],
        },
        "companies_search": {
            "data": {
                "total_matches": 58393,
                "companies": [
                    {
                        "org_number": "964338531",
                        "name": "BERGEN KOMMUNE",
                        "employees": 32820,
                        "industry": None,
                    },
                    {
                        "org_number": "983974910",
                        "name": "HELSE BERGEN HF",
                        "employees": 13000,
                        "industry": None,
                    },
                ],
            },
            "provenance": [_prov("brreg")],
        },
        "traffic_find_points": {
            "data": {"total_matches": 172},
            "provenance": [_prov("vegvesen_traffic")],
        },
        "hazards_flood_landslide": {"data": {"warnings": []}, "provenance": [_prov("nve_varsom")]},
        "weather_warnings": {"data": {"warnings": []}, "provenance": [_prov("met_metalerts")]},
        "electricity_municipality": {
            "data": {
                "from_date": "2026-10-22",
                "to_date": "2026-10-28",
                "days_with_figures": 7,
                "average_mwh_per_day": 9721.5,
                "by_group": [
                    {"group": "private", "mwh": 37037.0, "share_pct": 54.4, "metering_points": 1}
                ],
                "capacity_mw": 125.8,
                "capacity": [{"kind": "hydro", "mw": 72.8, "prosumer_mw": 0.0}],
            },
            "provenance": [_prov("elhub")],
        },
    }
    calls = []

    async def fake(ctx, tool, arguments):
        calls.append((tool, arguments))
        if tool == "schools_search":
            key = arguments.get("level") or arguments.get("ownership") or "all"
            return school({"all": 235, "primary": 93, "secondary": 32, "private": 112}[key])
        if tool == "companies_accounts":
            if arguments["org_number"] == "964338531":
                return ToolError(ErrorCode.NOT_FOUND, "No open accounts.")
            year = {"year": 2025, "revenue": 1.2e10, "net_result": -5e6, "currency": "NOK"}
            return {"data": {"accounts": [year]}, "provenance": [_prov("brreg_accounts")]}
        return answers[tool]

    monkeypatch.setattr(composite, "_part", fake)
    result = await OPS["municipality_profile"].invoke(ctx, {"municipality": "1201"})
    data = result["data"]
    assert (data["code"], data["name"], data["resolved_from"]) == ("4601", "Bergen", "1201")
    assert data["population"]["latest"] == 294860 and data["companies_registered"] == 58393
    assert data["schools"] == {"total": 235, "primary": 93, "secondary": 32, "private": 112}
    assert data["traffic_points"] == 172
    power = data["electricity"]
    assert power["kwh_per_inhabitant_per_day"] == 33.0  # 9,721.5 MWh a day over 294,860 people
    assert power["private_kwh_per_inhabitant_per_day"] == 17.9
    assert (power["private_share_pct"], power["largest_capacity_kind"]) == (54.4, "hydro")
    assert ("electricity_municipality", {"municipality": "4601"}) in calls
    municipality, hospital = data["largest_employers"]
    assert municipality["revenue"] is None
    assert (hospital["accounts_year"], hospital["revenue"], hospital["currency"]) == (
        2025,
        1.2e10,
        "NOK",
    )
    assert ("companies_accounts", {"org_number": "983974910", "kind": "company"}) in calls
    assert any(n.startswith("Employers without revenue") for n in result["notes"])
    assert ("weather_warnings", {"county": "46"}) in calls
    population_calls = [a for t, a in calls if t == "statistics_get_data"]
    assert population_calls[0]["codelists"] == {"Region": "agg_KommSummer"}
    assert population_calls[0]["select"]["Region"] == ["K-4601"]
    assert len(result["provenance"]) >= 7


def test_pick_with_no_match_says_so():
    error = composite._pick([], "nowhereville")
    assert error.body.code == "NOT_FOUND" and "past or present" in error.body.message


async def test_compare_skips_duplicates_and_reports_failures(ctx, monkeypatch):
    def profile(code, name, population, companies):
        return {
            "data": {
                "code": code,
                "name": name,
                "population": {
                    "latest": population,
                    "change_1y_pct": 1.0,
                    "change_since_pct": 5.0,
                    "change_since": "2016",
                },
                "companies_registered": companies,
                "schools": {"total": 10},
                "traffic_points": 3,
                "electricity": {"kwh_per_inhabitant_per_day": 30.0, "installed_capacity_mw": 5.0},
                "warnings": [],
            },
            "provenance": [_prov("ssb_statbank")],
            "notes": [],
        }

    answers = {
        "Bergen": profile("4601", "Bergen", 300000, 60000),
        "1201": profile("4601", "Bergen", 300000, 60000),
        "Stavanger": profile("1103", "Stavanger", 150000, 30000),
    }

    asked = []

    async def fake(ctx, tool, arguments):
        asked.append(arguments)
        name = arguments["municipality"]
        if name not in answers:
            return ToolError(ErrorCode.NOT_FOUND, f"No municipality is called '{name}'.")
        return answers[name]

    monkeypatch.setattr(composite, "_part", fake)
    result = await OPS["compare_municipalities"].invoke(
        ctx, {"municipalities": ["Stavanger", "Bergen", "1201", "Nowhere"]}
    )
    assert {a.get("employer_accounts") for a in asked} == {False}
    rows = result["data"]["rows"]
    assert [r["code"] for r in rows] == ["4601", "1103"]
    assert rows[0]["companies_per_1000"] == 200.0
    assert rows[0]["electricity_kwh_per_inhabitant_per_day"] == 30.0
    assert result["data"]["failed"] == ["Nowhere"]
    assert any("already in the comparison" in n for n in result["notes"])
