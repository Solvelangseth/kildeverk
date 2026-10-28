"""A few real calls per source, to notice when an upstream changes. Not run in CI.

uv run pytest -m live
"""

from __future__ import annotations

import pytest

from kildeverk.context import build_context
from kildeverk.core.cache import ResponseCache
from kildeverk.settings import Settings
from kildeverk.sources.registry import operations

pytestmark = pytest.mark.live
OPS = {op.name: op for op in operations()}


@pytest.fixture
async def live():
    # Environment only (no .env file): CI passes the contact and the Frost id this way.
    ctx = build_context(Settings(_env_file=None), cache=ResponseCache(":memory:"))
    yield ctx
    await ctx.aclose()


async def test_ssb_search_describe_and_fetch(live):
    found = await OPS["statistics_search_tables"].invoke(live, {"query": "population"})
    assert found["data"]["tables"]
    described = await OPS["statistics_describe_table"].invoke(live, {"table_id": "07459"})
    data = await OPS["statistics_get_data"].invoke(live, described["data"]["example_arguments"])
    assert data["data"]["row_count"] == 1
    assert isinstance(data["data"]["rows"][0]["value"], int)


async def test_klass_history_and_a_reform_conversion(live):
    found = await OPS["regions_resolve"].invoke(live, {"query": "Bergen", "level": "municipality"})
    assert found["data"]["matches"][0]["code"] == "4601"
    result = await OPS["regions_harmonise"].invoke(
        live,
        {
            "level": "municipality",
            "target": "2020",
            "measure": "additive",
            "rows": [
                {"region": "1508", "period": "2024", "value": 1},
                {"region": "1580", "period": "2024", "value": 2},
            ],
        },
    )
    assert result["data"]["rows"][0] == {
        "region": "1507",
        "region_name": "Ålesund",
        "period": "2024",
        "value": 3.0,
        "method": "summed",
        "sources": ["1508", "1580"],
    }


async def test_brreg_lookup_and_search(live):
    company = await OPS["companies_get"].invoke(live, {"org_number": "923609016"})
    assert company["data"]["name"] == "EQUINOR ASA"
    found = await OPS["companies_search"].invoke(live, {"name": "equinor", "limit": 3})
    assert found["data"]["companies"]


async def test_met_forecast(live):
    result = await OPS["weather_forecast"].invoke(live, {"lat": 59.9423, "lon": 10.72, "hours": 6})
    assert len(result["data"]["points"]) >= 6


async def test_frost_stations_and_observations(live):
    if not live.settings.frost_client_id:
        pytest.skip("KILDEVERK_FROST_CLIENT_ID is not set")
    stations = await OPS["weather_find_stations"].invoke(live, {"name": "Blindern"})
    assert "SN18700" in {s["id"] for s in stations["data"]["stations"]}
    observed = await OPS["weather_observations"].invoke(
        live,
        {
            "station": "SN18700",
            "elements": ["daily_mean_temperature"],
            "start": "2024-01-01",
            "end": "2024-01-08",
        },
    )
    assert observed["data"]["row_count"] == 7


async def test_nve_station_and_latest_discharge(live):
    if not live.settings.nve_api_key:
        pytest.skip("KILDEVERK_NVE_API_KEY is not set")
    found = await OPS["water_find_stations"].invoke(live, {"station": "62.5.0"})
    assert found["data"]["stations"][0]["name"].startswith("Bulken")
    latest = await OPS["water_observations"].invoke(
        live, {"station": "62.5.0", "parameter": "discharge"}
    )
    assert latest["data"]["row_count"] == 1


async def test_entur_stop_and_departures(live):
    found = await OPS["transit_find_stops"].invoke(live, {"query": "Oslo S", "limit": 1})
    assert found["data"]["stops"][0]["id"] == "NSR:StopPlace:59872"
    departures = await OPS["transit_departures"].invoke(
        live, {"stop": "NSR:StopPlace:59872", "limit": 3}
    )
    assert departures["data"]["departures"]


async def test_kartverket_address_place_and_elevation(live):
    address = await OPS["addresses_search"].invoke(live, {"query": "Karl Johans gate 22 Oslo"})
    assert address["data"]["addresses"][0]["postcode"] == "0026"
    place = await OPS["places_search"].invoke(live, {"query": "Galdhøpiggen"})
    assert place["data"]["places"][0]["type"] == "Fjell"
    height = await OPS["terrain_elevation"].invoke(
        live, {"points": [{"lat": 61.63644, "lon": 8.31248}]}
    )
    assert 2400 < height["data"]["points"][0]["elevation_m"] < 2500


async def test_norges_bank_rates(live):
    rates = await OPS["currency_exchange_rates"].invoke(live, {"currencies": ["EUR"]})
    assert 5 < rates["data"]["rows"][0]["nok"] < 20
    policy = await OPS["rates_policy_rate"].invoke(live, {"since": "2020-01-01"})
    assert policy["data"]["changes"]


async def test_varsom_warnings_and_avalanche_summary(live):
    warnings = await OPS["hazards_flood_landslide"].invoke(live, {"municipality": "0301"})
    assert warnings["provenance"]
    summary = await OPS["hazards_avalanche"].invoke(live, {})
    assert len(summary["data"]["forecasts"]) >= 40


async def test_datanorge_search(live):
    result = await OPS["catalog_search"].invoke(live, {"query": "befolkning", "limit": 3})
    assert result["data"]["entries"]


async def test_quick_wins(live):
    warnings = await OPS["weather_warnings"].invoke(live, {})
    assert warnings["provenance"]
    place = await OPS["regions_at_point"].invoke(live, {"lat": 59.91, "lon": 10.75})
    assert place["data"]["municipality_code"] == "0301"
    sea = await OPS["sea_level"].invoke(live, {"station": "OSL"})
    assert sea["data"]["series"]
    reservoirs = await OPS["energy_reservoirs"].invoke(live, {"areas": ["NO"]})
    assert 0 < reservoirs["data"]["rows"][0]["fill_pct"] <= 100


async def test_new_publishers(live):
    cases = await OPS["parliament_cases"].invoke(live, {"limit": 3})
    assert cases["data"]["session"]
    members = await OPS["parliament_members"].invoke(live, {})
    assert members["data"]["count"] >= 169
    points = await OPS["traffic_find_points"].invoke(live, {"name": "Nygårdstunnelen"})
    assert points["data"]["points"]
    schools = await OPS["schools_search"].invoke(live, {"name": "Alvøen"})
    assert schools["data"]["schools"]


async def test_place_overview(live):
    result = await OPS["place_overview"].invoke(live, {"lat": 59.9139, "lon": 10.7522})
    assert result["data"]["municipality"]["code"] == "0301"
    assert result["data"]["weather"] and result["data"]["nearest_stops"]


async def test_municipality_profile(live):
    result = await OPS["municipality_profile"].invoke(live, {"municipality": "1201"})
    assert result["data"]["code"] == "4601" and result["data"]["population"]["latest"] > 250_000


async def test_compare_municipalities(live):
    result = await OPS["compare_municipalities"].invoke(live, {"municipalities": ["0301", "4601"]})
    assert [r["code"] for r in result["data"]["rows"]] == ["0301", "4601"]


async def test_statistics_series(live):
    result = await OPS["statistics_series"].invoke(
        live, {"table_id": "07459", "region": "Tromsø", "from_year": 2015}
    )
    assert result["data"]["method"] == "summed_to_todays_borders"


async def test_statistics_rank(live):
    result = await OPS["statistics_rank"].invoke(live, {"table_id": "07459", "limit": 3})
    assert result["data"]["rows"][0]["code"] == "0301"
