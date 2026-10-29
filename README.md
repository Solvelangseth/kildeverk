# Kildeverk

Live Norwegian public data for AI agents and people. Kildeverk is an MCP server
and a read-only JSON API over 28 official data services from 16 publishers, 14 of them Norwegian:
statistics, companies, weather, water, warnings, transport, maps, the sea, money,
energy, parliament, roads and schools. Every result says exactly where it came from.

**Try it:** [kildeverk.fly.dev](https://kildeverk.fly.dev) · MCP at `https://kildeverk.fly.dev/mcp`

- **One set of tools, two front doors.** The same handlers serve MCP (streamable HTTP or stdio) and REST.
- **Provenance on every result:** the source, its licence, the exact upstream URL, when it was retrieved, and a citation line you can paste.
- **Errors an agent can act on.** Each error has a code, a plain explanation, whether retrying helps, how long to wait, and often a ready-made next call.
- **Polite to upstreams.** Each upstream gets a token bucket below its published limit, an on-disk cache, request coalescing and conditional requests.

This is a personal project, built and maintained by one person. It is not affiliated with any of the
publishers whose data it reads.

## Status and scope

| Source | Status | Tools |
| --- | --- | --- |
| [SSB Statbank](#ssb_statbank) | ✅ available | `statistics_search_tables`, `statistics_describe_table`, `statistics_get_data` |
| [SSB Klass](#ssb_klass): regions and harmonisation across the 2020 and 2024 reforms | ✅ available | `regions_list`, `regions_resolve`, `regions_changes`, `regions_harmonise` |
| [Brønnøysund Register Centre (Enhetsregisteret)](#brreg) | ✅ available | `companies_search`, `companies_get` |
| [Regnskapsregisteret](#brreg_accounts): annual accounts | ✅ available | `companies_accounts` |
| [MET Norway Locationforecast](#met_locationforecast) | ✅ available | `weather_forecast` |
| [MET Norway MetAlerts](#met_metalerts): weather warnings | ✅ available | `weather_warnings` |
| [MET Norway Nowcast](#met_nowcast): rain in the next two hours | ✅ available | `weather_nowcast` |
| [MET Norway Oceanforecast](#met_oceanforecast): waves and sea temperature | ✅ available | `sea_forecast` |
| [MET Norway Airqualityforecast](#met_airquality) | ✅ available | `air_quality_forecast` |
| [MET Norway Frost](#met_frost): needs a free client id | ✅ available | `weather_find_stations`, `weather_station_elements`, `weather_observations`, `weather_normals` |
| [NVE HydAPI](#nve_hydapi): needs a free key | ✅ available | `water_find_stations`, `water_observations` |
| [Entur Geocoder](#entur_geocoder): stop places | ✅ available | `transit_find_stops` |
| [Entur Journey Planner](#entur_journeyplanner): departures and journeys | ✅ available | `transit_departures`, `transit_journeys` |
| [Avinor](#avinor): flight departures and arrivals | ✅ available | `flights_airport` |
| [Kartverket](#kartverket): addresses, place names, elevation, municipality at a point | ✅ available | `addresses_search`, `places_search`, `terrain_elevation`, `regions_at_point` |
| [Kartverket water level and tides](#kartverket_sea_level) | ✅ available | `sea_level`, `sea_level_extremes` |
| [Norges Bank](#norges_bank): exchange rates and the policy rate | ✅ available | `currency_exchange_rates`, `rates_policy_rate` |
| [NVE Varsom](#nve_varsom): flood, landslide and avalanche warnings | ✅ available | `hazards_flood_landslide`, `hazards_avalanche` |
| [Regobs](#nve_regobs): field observations of avalanches, landslides, floods and ice | ✅ available | `hazards_field_observations` |
| [data.norge.no](#datanorge): the national data catalogue | ✅ available | `catalog_search` |
| [NVE reservoir statistics](#nve_reservoirs): hydropower reservoir fill | ✅ available | `energy_reservoirs` |
| [Elhub](#elhub): electricity consumption and production | ✅ available | `electricity_municipality`, `electricity_price_areas` |
| [Stortinget](#stortinget): cases, votes, members and questions | ✅ available | `parliament_cases`, `parliament_case`, `parliament_members`, `parliament_questions` |
| [Statens vegvesen traffic data](#vegvesen_traffic) | ✅ available | `traffic_find_points`, `traffic_volumes` |
| [National School Register](#udir_nsr) | ✅ available | `schools_search`, `schools_get` |
| [Ordbøkene](#ordbokene): Bokmålsordboka and Nynorskordboka | ✅ available | `dictionary_lookup` |
| [USGS Earthquake Catalog](#usgs_earthquakes) | ✅ available | `hazards_earthquakes` |
| [World Bank World Development Indicators](#worldbank_wdi) | ✅ available | `world_indicators` |

Three tools combine sources. `place_overview` takes a coordinate and returns its municipality and
county, elevation, the weather now and over the next six hours, weather, flood and landslide
warnings in force, the nearest stops and named places nearby, and ready-made follow-up calls. It
calls the other tools, so each part keeps its own provenance, budget and cache, and a part that
fails becomes a note while the rest still answers. `municipality_profile` takes a municipality code,
old or current, or a name, follows it through the reforms with [SSB Klass](#ssb_klass), and returns
population and its change, registered companies and the largest employers, schools by level and
ownership, traffic counting points, electricity use per inhabitant from [Elhub](#elhub), and the
warnings in force. Its population series is SSB's,
summed to today's borders, so the change reaches back past the 2020 and 2024 reforms.
`compare_municipalities` puts two to five of these side by side.

`statistics_series` gives one SSB statistic for Norway, a county or a municipality over every
year in one call. Where SSB publishes a series summed to today's borders, it uses that. Where it
does not, `measure_kind` lets Kildeverk rebuild the earlier years itself with
[SSB Klass](#ssb_klass): counts and totals (`additive`) are summed from the regions that became
today's one, and rates and shares (`non_additive`) follow one-to-one renumberings only. The result
says which method it used and from which codes.

`statistics_rank` ranks every municipality or county on one SSB statistic, with Norway's figure for
reference. Give `compare_to` to rank by change since an earlier year ("which municipalities grew
fastest since 2015?"), and `min_value` to leave out tiny municipalities whose percentages swing.
When the newest year is listed before its figures exist, it ranks the newest year that has them,
and says so.

`cite_sources` turns the `provenance` of any result into references, as BibTeX and as CSL-JSON
for Zotero, Pandoc and citation processors. It runs locally and fetches nothing.

Two tools describe the service itself: `sources_list` and `service_status`, which also counts
calls, errors and cache hits per tool.

Tools that filter by municipality or county also accept names: `companies_search`,
`schools_search`, `traffic_find_points`, `addresses_search`, `places_search`,
`hazards_flood_landslide` and `weather_warnings`. Names are resolved to today's code through SSB
Klass, including former municipalities that merged whole into one of today's; Klass is cited in
the result, and a note says what a name was read as. A name shared by two municipalities, or
a former one that was divided, is an error that lists the codes.

Over MCP, the server also offers **resources**: `kildeverk://guide` (which tool answers which
question), `kildeverk://sources`, and one `kildeverk://sources/<id>` per source. It offers four
**prompts**: `profile_place`, `profile_municipality`, `find_statistic` and `compare_places`, plus
one `recipe_<tool>` prompt for each worked question on the website. The OpenAPI document carries
each tool's examples, so `/docs` opens with requests that work as they are.

No source is scraped, and no undocumented endpoint behind a website is used. Kildeverk is
non-commercial. Every result names the licence its source states, or says that none is stated.

Kildeverk reads live data. It does not mirror or archive anything beyond a short-lived response cache.

## Use it

### The hosted service

The hosted service runs at **https://kildeverk.fly.dev**, on one machine in Stockholm. No sign-up
and no key: point an MCP client at the URL below, or call the JSON API directly.

```json
{
  "mcpServers": {
    "kildeverk": { "type": "http", "url": "https://kildeverk.fly.dev/mcp" }
  }
}
```

```sh
claude mcp add --transport http kildeverk https://kildeverk.fly.dev/mcp
curl "https://kildeverk.fly.dev/v1/weather/forecast?lat=59.91&lon=10.75"
```

The website at the same address has a "Try it" button for every tool, and the API's interactive
documentation is at [/docs](https://kildeverk.fly.dev/docs). It is a personal project with no
uptime promise; for heavy use, run your own (see [Deploy your own](#deploy-your-own)).

A public deployment differs from a local one in three ways:
- **Each client address gets its own budget:** 60 calls a minute with bursts of 20, across the
  JSON API and MCP. Above it, calls answer HTTP 429 with a `RATE_LIMITED` error and `Retry-After`.
  The upstream budgets are shared by everyone, and this keeps one busy client from spending them.
- **The website** is served at `/`, built from the same registry as the tools, with a "Try it"
  button for every tool. The JSON index moves to `/v1`.
- **Keys:** Frost and HydAPI tools work only if the deployment has its own keys set.

### Locally, over stdio

A local install has its own upstream budget, which matters if you make many calls.

```json
{
  "mcpServers": {
    "kildeverk": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Solvelangseth/kildeverk", "kildeverk", "serve"],
      "env": { "KILDEVERK_CONTACT": "you@example.com" }
    }
  }
}
```

`KILDEVERK_CONTACT` goes into the User-Agent so that upstreams can reach whoever is making the
requests. MET Norway requires this.

### As an HTTP server

```sh
uv run kildeverk serve --http --port 8000
# MCP:      http://127.0.0.1:8000/mcp
# REST:     http://127.0.0.1:8000/v1/...
# OpenAPI:  http://127.0.0.1:8000/openapi.json
```

### From the command line

```sh
uv run kildeverk call statistics_get_data '{"table_id": "07459", "select": {"Region": ["0301", "4601"], "Tid": {"latest": 2}}}'
```

## What a result looks like

```json
{
  "data": { "table_id": "07459", "rows": [{ "Region": "0301", "Region_label": "Oslo - Oslove", "Tid": "2026", "value": 728714, "...": "..." }] },
  "provenance": [{
    "source_id": "ssb_statbank",
    "licence": { "id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/" },
    "request": { "method": "GET", "url": "https://data.ssb.no/api/pxwebapi/v2/tables/07459/data?lang=en&..." },
    "retrieved_at": "2026-10-28T07:02:11Z",
    "cache": { "hit": false, "age_s": 0.0, "stale": false },
    "citation": "Statistics Norway (SSB): Statbank table 07459: Population, by region and year. Retrieved 2026-10-28 07:02 UTC from https://data.ssb.no/... Licence: Creative Commons Attribution 4.0 International (https://creativecommons.org/licenses/by/4.0/)."
  }],
  "notes": [],
  "truncated": false,
  "summary": {
    "publishers": ["Statistics Norway (SSB)"],
    "licences": ["Creative Commons Attribution 4.0 International"],
    "upstream_responses": 1,
    "from_cache": 0,
    "stale": false,
    "oldest_retrieved_at": "2026-10-28T07:02:11Z"
  }
}
```

`summary` is the provenance at a glance. For the tools that combine sources, which may draw on a
dozen upstream responses, it says in one place who the data is from, how much came from the cache,
and how old the oldest part is.

An error looks like this:

```json
{
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "Dimension Region (region) has no value 'Bergen'. Values are codes, not names; look the code up by searching the table's values.",
    "retryable": false,
    "next_call": { "tool": "statistics_describe_table", "arguments": { "table_id": "07459", "value_search": "Bergen" } },
    "source_id": "ssb_statbank"
  }
}
```

The error codes are `INVALID_ARGUMENT`, `NOT_FOUND`, `AMBIGUOUS`, `TOO_LARGE`, `RATE_LIMITED`,
`UPSTREAM_UNAVAILABLE`, `UPSTREAM_TIMEOUT`, `UPSTREAM_CHANGED`, `NOT_CONVERTIBLE`, `NOT_CONFIGURED`
and `INTERNAL`. Over REST each code maps to an HTTP status, and rate-limit errors carry `Retry-After`.
Over MCP an error is a tool result with `isError` set and the same body.

## How upstream limits are respected

- **A token bucket per upstream.** Each bucket is sized so that no 60-second window can exceed the
  upstream's published limit. If a call would have to wait more than 5 seconds, it is refused with
  `RATE_LIMITED` and a `retry_after_s`.
- **An upstream 429** blocks that upstream's bucket for the `Retry-After` it gave.
- **A SQLite cache** with lifetimes set per source and per request type. Expired entries keep their
  ETag and Last-Modified so they can be revalidated. If upstream fails, an expired copy is served,
  marked `stale`, and a note says why.
- **Identical requests in flight** share one upstream call.
- **An identifying User-Agent:** `kildeverk/<version> (<deployment>; +<repo>; <contact>)`.

## Sources

<a id="ssb_statbank"></a>
### SSB Statbank

**What it covers:** every published table in Statistics Norway's Statbank, through PxWebApi v2.
- Keyword search across tables, in English or Norwegian.
- Table metadata: dimensions, value codes, units, aggregation codelists (counties, 5-year age groups, …) and footnotes.
- Data for any selection, returned as labelled rows.

**Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), per [SSB's terms](https://www.ssb.no/en/diverse/lisens).

**Rate limits:** SSB publishes 30 queries per 60 seconds per IP and 800,000 cells per query.
Kildeverk spends at most 25 per minute and returns at most 10,000 rows per call.

**Caching:**
- Search and metadata: 1 hour. Codelists: 24 hours.
- Data responses are keyed on the table's `updated` timestamp. A cached answer is therefore reused
  until SSB republishes the table, and is refetched once the metadata shows that it has.
- SSB sends no ETag or Last-Modified, so there is nothing to revalidate with. Expiry is time-based.

**How the tools fit together:**
1. `statistics_search_tables` finds tables.
2. `statistics_describe_table` shows a table's codes. `value_search` finds a code by name, and
   `example_arguments` is a valid starting call.
3. `statistics_get_data` fetches the data:
   - Selections are lists of codes, `"*"`, `{"latest": N}` or `{"from": code}`.
   - A time dimension you leave out defaults to its latest period. Other dimensions you leave out
     are totalled where SSB allows it.
   - The size of the answer is checked against the metadata before any data is requested.

**Known gaps:**
- Search is SSB's own keyword search. English search only matches English titles, so Norwegian
  terms need `lang: "no"`. The tool adds a note saying so when an English search finds nothing.
- Codes in dimensions queried through a codelist are not checked locally; SSB checks them.
- Only SSB's Statbank is included, not PxWeb databases run by other agencies.

<a id="ssb_klass"></a>
### SSB Klass: regions and their history

**What it covers:** every Norwegian municipality and county code since 1960, read from Statistics
Norway's classification service Klass:
- names and validity periods for every code;
- every recorded change: mergers, splits, renumberings and renamings, with their dates;
- conversion of a regional series to the borders of another date.

**Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), stated in the
[Klass API guide](https://data.ssb.no/api/klass/v1/api-guide.html#_license).

**Rate limits:** Klass publishes none. Kildeverk holds itself to the same 25 calls per minute as for
Statbank. Every region tool reads the same two responses per level (all codes and all changes since
1960), and both are cached for 24 hours. In practice that means a handful of upstream calls per day.

**How harmonisation works (`regions_harmonise`):**

The history is a graph of *units*. A unit is one code over one stretch of time during which its
territory, as far as Klass records it, did not change. A code alone is not enough, for two reasons:
- Codes are reused: `0712` was Skoger until 1964 and Larvik from 2018.
- A code can keep its number while its territory grows: Stavanger kept `1103` when it absorbed
  Finnøy and Rennesøy in 2020.

Each input row is placed in the unit that was valid in its year, then followed through the
recorded changes to the target date, forwards or backwards in time.

| Situation | What happens |
| --- | --- |
| Code unchanged, or only renumbered (1201 Bergen → 4601) | value carried over |
| Several regions merged into one, every piece present, additive measure | values summed |
| A piece of a merger is missing from the input | not converted; the reason names the missing codes |
| A region was split (Snillfjord 2020, Ålesund 2024, Viken 2024) | not converted: Klass does not say how values divided, and nothing is estimated |
| Going back across a merger (2024 Stavanger → 2019 borders) | the same as a split, so not converted |
| Rates, shares and averages (`measure: "non_additive"`) | renumbered, never summed |
| Zero for a code in a year it did not exist | dropped as an SSB placeholder, and counted |
| Values for the same area from two border vintages in one period | not converted, so nothing is counted twice |

Every answer lists each input code's mapping (`unchanged`, `renumbered`, `merged`, `split` or
`no_successor`) and every row it could not convert, with the reason.

**Known gaps:**
- Klass records changes of code, not every small boundary adjustment between municipalities that
  kept their codes. Those transfers are invisible here.
- A split is never converted, even approximately. Population-weighted estimates may come later,
  clearly marked as estimates.
- Periods are read by year, so a change in the middle of a year is placed in that year.
- Codes valid only before 1960 are unknown.
- Codes for unknown or unspecified areas, such as `9999` "Uoppgitt", are listed like any other code.

<a id="brreg"></a>
### Enhetsregisteret (Brønnøysund Register Centre)

**What it covers:** every registered legal entity in Norway, from the Central Coordinating Register
for Legal Entities. That includes companies, sole proprietorships, associations, foundations and
public bodies, together with their sub-units (establishments).
- `companies_search` filters by name, municipality, industry, legal form, minimum employees and
  registration date. Bankrupt entities are excluded unless you ask for them.
- `companies_get` looks up one organisation number, whether it belongs to a main unit or a
  sub-unit. It returns the legal form, industries, addresses, employees, share capital, register
  memberships, bankruptcy and liquidation status, former names and, if asked, the sub-units.

**Licence:** [NLOD 2.0](https://data.norge.no/nlod/en/2.0), as stated in
[Brreg's API documentation](https://data.brreg.no/enhetsregisteret/api/dokumentasjon/no/index.html).

**Rate limits:** Brreg publishes none, apart from the cap on paging below. Kildeverk spends at most
60 calls per minute.

**Caching:** entity lookups for 1 hour, searches for 15 minutes. Brreg sends no validators.

**Behaviour worth knowing:**
- Requests pin Brreg's versioned media types (`enhet.v2`, `underenhet.v2`), so a new response
  version upstream cannot silently change these tools.
- Organisation numbers are checked against their modulus-11 check digit before any request is made.
- Brreg answers 410 when it has withdrawn an entity for legal reasons. In that case Kildeverk
  refuses the lookup and deletes any cached copy, as Brreg asks.
- The industry filter matches any of an entity's up to three industry codes, not only the main one.

**Privacy:**
- Roles (board members, managing directors, auditors) are not served, because they name people.
- Phone numbers and e-mail addresses are dropped from every response and scrubbed from the test
  fixtures, although Brreg publishes them.
- Sole proprietorships are often named after their owner. That is how the public register works,
  and Kildeverk shows those names as published.

**Known gaps:**
- Industry codes are SN2025, which Brreg switched to in 2025, so SN2007 codes such as `62.010` no
  longer match. A two-digit division such as `62` does, and an empty result adds a note saying so.
- One search pages through at most 10,000 results.
- The register of beneficial owners and corporate group structure are not included. Annual
  accounts are a separate source, [Regnskapsregisteret](#brreg_accounts).

<a id="brreg_accounts"></a>
### Regnskapsregisteret: annual accounts

**What it covers:** key figures from the annual accounts Norwegian companies file with the
Brønnøysund Register Centre.
- `companies_accounts` gives, for one organisation number, the last three years' revenue, sales
  revenue, operating costs, salary costs, operating profit, net financial items, profit before tax,
  tax, net result, total, fixed and current assets, cash, equity and debt, with the operating
  margin, the equity ratio and the change in revenue from the year before. It gives company
  accounts and, for parent companies, group accounts, each with its currency, its accounting rules
  (NGAAP, IFRS or simplified IFRS), and whether it was audited.
- `municipality_profile` adds the latest revenue and net result to each of the largest employers.
  `compare_municipalities` leaves this out to save calls.

**Licence:** [NLOD 2.0](https://data.norge.no/nlod/en/2.0). data.norge.no lists the open API as the
distribution "Nøkkeltall fra årsregnskapet" under NLOD 2.0
([the catalogue entry](https://data.norge.no/datasets/8132460c-91ab-3950-a54b-a54ee20c62e9)).

**Rate limits:** none published. Kildeverk spends at most 75 calls a minute.

**Caching:** a day; accounts are filed once a year.

**Behaviour worth knowing:**
- Amounts are in the currency each company reports in. Equinor, for one, reports in USD; the
  notes say so whenever a result is not in NOK.
- Public bodies, sole proprietorships and others that do not file accounts have none. The error
  says so and suggests `companies_get` instead.
- Small companies may leave out lines such as sales revenue or tax; those fields are empty, not 0.

**Known gaps:**
- Only the last three years are open; Brreg sells older accounts.
- Notes, the board's report, the auditor's report and cash flow are not in the open API.

<a id="met_locationforecast"></a>
### MET Norway Locationforecast

**What it covers:** a weather forecast for any point. It gives temperature, precipitation, wind,
cloud, humidity, pressure and a weather symbol: hourly for about the first 2.5 days, then 6-hourly up
to about 10 days. `weather_forecast` needs no configuration.

**Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), also offered under NLOD 2.0,
per [MET's licence page](https://api.met.no/doc/License). Credit goes to MET Norway.

**Following MET's [terms of service](https://api.met.no/doc/TermsOfService):**
- **User-Agent:** every request identifies Kildeverk and its contact (`KILDEVERK_CONTACT`).
- **Caching:** a response is cached until its `Expires` time and then revalidated with
  `If-Modified-Since`, which MET answers with 304 when nothing changed.
- **Coordinates:** rounded to 3 decimals (about 110 m). MET allows at most 4. Rounding further lets
  nearby requests share one cached forecast.
- **Request rate:** at most 60 calls a minute, far below MET's 20 requests a second.
- **Deprecation:** MET signals a deprecated API version with HTTP 203; Kildeverk logs it as a
  warning.

**Known gaps:**
- Only the compact product is used, so there are no percentile (uncertainty) values.
- Weather warnings (MetAlerts) and ocean forecasts are not included.
- Each precipitation value covers its own `precipitation_hours` (1, 6 or 12). Add up only
  non-overlapping periods.

<a id="met_metalerts"></a>
### MET Norway MetAlerts: weather warnings

**What it covers:** MET Norway's official weather warnings for land and sea.
- `weather_warnings` gives the warnings in force or announced now, or those of any past month from
  the archive. They cover wind, gale, rain, snow, ice, storm surge, forest fire danger, polar lows
  and more. You can filter by point, county, or land and sea. Each warning has its level, area,
  counties, period, description, consequences and advice, and a link to MET's page for it.

For flood, landslide and avalanche warnings, which NVE issues, use [NVE Varsom](#nve_varsom).

**Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (also NLOD), as for the
forecast.

**Rate limits and caching:** shared with the forecast's rules: Kildeverk honours `Expires`, and
caches current warnings for 5 minutes and archive months for 24 hours.

**Behaviour worth knowing:**
- The archive keeps every revision of a warning. Kildeverk returns the latest revision of each and
  says how many earlier ones it left out. Cancelled warnings are left out too.
- A revision can raise or lower the level. `level` is the latest; `highest_level` is the highest
  any revision reached. Filtering and sorting use `highest_level`, so the August 2023 storm Hans
  warning that was eased to orange at the end still shows as the red warning it was.
- County numbers are those in force when the warning was issued. Before 2024 that means the
  2020-2023 counties; [SSB Klass](#ssb_klass) can map them.

<a id="met_frost"></a>
### MET Norway Frost

**What it covers:** MET Norway's observation archive.
- `weather_find_stations` finds stations near a point or by name.
- `weather_station_elements` lists what a station measures, at which resolutions, and since when.
- `weather_observations` returns hourly readings and daily or monthly aggregates over a period.
  Friendly names cover the common cases (`daily_mean_temperature`, `daily_precipitation`,
  `snow_depth`, …), and any Frost element id works too.
- `weather_normals` gives a station's 30-year climate normals (1991-2020 by default, or 1961-1990
  and 1931-1960): monthly and yearly mean temperature and precipitation. Given a year, it puts
  each month's observed mean temperature and precipitation beside the normal, with the
  difference in degrees and the precipitation as per cent of normal, and marks the month still
  under way as incomplete.

**Setup:** Frost needs a free client id from
[frost.met.no](https://frost.met.no/auth/requestCredentials.html). Set it as
`KILDEVERK_FROST_CLIENT_ID`. Without it, these four tools answer `NOT_CONFIGURED` and the forecast
still works. The id is sent as HTTP basic auth and never appears in URLs, provenance or fixtures.

**Licence:** every Frost response states
[CC BY 3.0 Norway](https://creativecommons.org/licenses/by/3.0/no/), and each result cites the
licence its own response states. MET's [general licence page](https://api.met.no/doc/License) says
NLOD 2.0 and CC BY 4.0 "unless specified otherwise". Both are attribution licences that allow
redistribution.

**Rate limits:** Frost publishes none. Kildeverk spends at most 30 calls a minute.

**Caching:**
- Station lists and element lists: 24 hours.
- Observations for periods ending more than two days ago: 24 hours.
- More recent observations: 10 minutes.

**Behaviour worth knowing:**
- Requests ask for each element's default series (`timeoffsets=default`, `levels=default`).
  Without that, Frost also returns alternatives, such as daily precipitation counted from 18 UTC
  as well as from 06 UTC, and they look like duplicates.
- Each row carries `time_offset`, so the measured period is explicit. Daily precipitation with
  `PT6H` runs from 06 UTC to 06 UTC.
- An element the station doesn't measure returns `INVALID_ARGUMENT`, with a `next_call` to
  `weather_station_elements`. A period with no data returns `NOT_FOUND` with Frost's own reason.

**Known gaps:**
- Only open data: series that need Frost's client secret are not available.
- The newest observations can take an hour or more to appear.
- At most ten years per call and 10,000 rows per answer.

<a id="met_nowcast"></a>
### MET Norway Nowcast: rain in the next two hours

**What it covers:** `weather_nowcast` gives precipitation every five minutes for the next two
hours anywhere in the Nordic area, from weather radar, with whether it is raining now, when rain
starts or stops, the heaviest rate, the amount in the next hour, and the temperature, wind and
humidity now. `place_overview` uses it to say when rain starts or stops.

**Licence, rate limits:** as for [Locationforecast](#met_locationforecast). Kildeverk follows each
answer's `Expires`, about five minutes.

**Known gaps:** only the Nordic area (Svalbard is outside, and the error points to
`weather_forecast`). With reduced radar coverage the precipitation is less reliable, and the
result says so.

<a id="met_oceanforecast"></a>
### MET Norway Oceanforecast: waves and sea temperature

**What it covers:** `sea_forecast` gives, for a point at sea along the Norwegian coast, the
significant wave height and direction, the sea temperature, and the current speed and direction,
hourly for up to about eight days, with the highest waves ahead. The forecast is for the nearest
sea grid point, which the result gives.

**Licence, rate limits:** as for [Locationforecast](#met_locationforecast); cached for an hour or
as long as `Expires` says.

**Known gaps:** points on land or far into a fjord have no forecast, and the error says so. Wave
period and swell are not in the API.

<a id="met_airquality"></a>
### MET Norway Airqualityforecast

**What it covers:** `air_quality_forecast` gives the forecast air quality at a point in Norway,
hour by hour for about two days, for the smallest statistical area (`grunnkrets`, a few streets),
part of the municipality, or the whole municipality. Each hour has the air quality index (1 to 5),
MET's level (low, moderate, high, very high), the pollutant behind it, and the NO2, PM10, PM2.5 and
ozone concentrations. The worst hour also says where its pollution comes from: traffic exhaust,
road dust and wear, heating (mostly wood burning), shipping, industry, or pollution carried in
from elsewhere.

**Licence, rate limits:** as for [Locationforecast](#met_locationforecast).

**Behaviour worth knowing:** upstream lists the hours out of order and sometimes twice; Kildeverk
keeps the last copy of each hour, sorts them, and starts from the current hour.

**Known gaps:** MET still calls this API version 0.1, unchanged since 2018, so treat it as less
settled than MET's other products. It is a model forecast for Norway only; measured air quality
(NILU) is not included.

<a id="nve_hydapi"></a>
### NVE HydAPI

**What it covers:** hydrological observations from the Norwegian Water Resources and Energy
Directorate, covering rivers, lakes, reservoirs, snow and groundwater.
- `water_find_stations` finds stations by name, municipality code, county, or distance from a point.
  It can be limited to stations measuring a given parameter. Each station lists its series, with
  their resolutions and years, its catchment area, whether the catchment is regulated, and flood
  statistics: peak discharge for the mean annual flood and the 5-, 10-, 20- and 50-year floods.
- `water_observations` returns daily or hourly means, or raw readings, for one parameter. Leave out
  the period to get the latest value. Friendly names cover the common parameters (`discharge`,
  `water_level`, `water_temperature`, `snow_depth`, `groundwater_level`, …), and any HydAPI
  parameter number works too.

**Setup:** HydAPI needs a free key from [hydapi.nve.no](https://hydapi.nve.no/Users). Set it as
`KILDEVERK_NVE_API_KEY`. Without it, these tools answer `NOT_CONFIGURED`. The key is sent as the
`X-API-Key` header and never appears in URLs, provenance or fixtures.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), stated in the
[HydAPI documentation](https://hydapi.nve.no/UserDocumentation/) and on every response. NVE asks to
be named as the source of the data.

**Rate limits:** 5 requests per second per key, reported in the `x-rate-limit-*` headers, plus a cap
on data points per request. Kildeverk spends at most 60 calls a minute.

**Caching:**
- Station metadata: 4 hours, which is how often NVE updates it.
- Observations for periods ending more than two days ago: 24 hours.
- Recent observations and latest values: 10 minutes.

**Behaviour worth knowing:**
- Every value carries `quality`: `uncontrolled`, `primary_controlled` or `secondary_controlled`.
  New data is uncontrolled and can still change, and the result says so in a note.
- HydAPI's `Active` flag reads backwards (0 means active stations only). Kildeverk exposes it as
  `include_closed`.
- Searching around a point uses a square WKT polygon in HydAPI's (latitude longitude) order. Results
  are then sorted by true distance and cut to the radius.

**Known gaps:**
- Rating curves and percentiles are not exposed yet.
- Flood, landslide and avalanche warnings come from a different NVE service: see
  [NVE Varsom](#nve_varsom).
- Station metadata names parameters in Norwegian. The `alias` field gives the English name that
  `water_observations` accepts.

<a id="entur_geocoder"></a>
### Entur Geocoder: stop places

**What it covers:** every public transport stop place in Norway, taken from the national stop
register (NSR) that Entur maintains.
- `transit_find_stops` finds stops by name, near a point, or by municipality code. It can be limited
  to some kinds of stop, such as `railStation`, `ferryStop` or `airport`. Each stop has its NSR id,
  the modes it serves, its municipality and county, its position and its fare zones.

Only NSR stop places are returned. The geocoder also knows addresses, points of interest and
OpenStreetMap places, but Kildeverk asks for the `stopPlace` layer alone, so every result is a stop
that `transit_departures` can use.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), stated in
[Entur's developer documentation](https://developer.entur.org/pages-intro-authentication).

**Rate limits:** 1000 requests a minute per client name, reported in `rate-limit-*` headers.
Kildeverk spends at most 60 calls a minute.

**Caching:** 24 hours. The stop register changes rarely.

**Behaviour worth knowing:**
- This uses Geocoder v3. Entur deprecated v1 and v2 in June 2026.
- With a `query`, `lat` and `lon` only rank nearby stops higher; `radius_km` applies when there is
  no query.

<a id="entur_journeyplanner"></a>
### Entur Journey Planner: departures

**What it covers:** departures from any stop place or single quay in Norway, for every operator:
trains, buses, trams, metro, ferries and flights.
- `transit_departures` returns the next departures, with scheduled and expected times, the delay,
  whether the time is real-time, the platform, line, destination, operator and cancellations. Any
  disruption notices are listed once and referenced from the departures they affect. It can be
  limited to some modes, and can look from a later start time.

**Identification:** Entur requires every client to send an `ET-Client-Name` header in the form
`<company>-<application>`. Kildeverk sends `kildeverk-local` or `kildeverk-public`. Set
`KILDEVERK_ENTUR_CLIENT_NAME` to use your own. No key is needed.
- `transit_journeys` plans a journey from A to B, each end given as a stop id, a stop name
  (looked up with the geocoder, and the result says what it was read as) or coordinates: the next
  journeys, or those arriving by a time, each with departure, arrival, duration, changes and
  walking distance, and every leg's mode, line, direction, stops, platforms, real-time times,
  cancellations and notices. Cached for a minute.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), as for the geocoder.

**Rate limits:** 2000 requests per two minutes per client name. Kildeverk spends at most 60 calls a
minute.

**Caching:** 30 seconds. Departures for "now" are the same request from call to call, so a burst of
identical questions costs one upstream call; the result says when it came from the cache.

**Behaviour worth knowing:**
- Times are Norwegian local time with their UTC offset. A `start` without an offset is read as
  Norwegian time, summer time included.
- Departures are ordered by expected time, so a delayed train can come after a later scheduled one.
- Real-time coverage depends on the operator; `realtime: false` means the time is the timetable.
- The query is GraphQL, and provenance records the full request body.

**Known gaps:**
- Groups of stop places (all of "Oslo", say) are not searched; use a stop place or a quay.

<a id="avinor"></a>
### Avinor flight data

**What it covers:** `flights_airport` gives departures and arrivals at a Norwegian airport, from an
hour ago to seven hours ahead by default (up to 24 hours either way): flight number, airline, the
other airport and any stops, whether the flight is domestic, Schengen or international, the
scheduled time, the new or actual time with the delay in minutes, gate, check-in, baggage belt, and
whether it is delayed or cancelled. It takes an IATA code or the airport's name, and filters by
direction, the other airport or a flight number.

**Licence:** Avinor's own terms: "We do not impose any limitations on how data is used", within
Norwegian law, and Avinor may end access for uses that harm its reputation
([terms](https://partner.avinor.no/en/services/flight-data/)). Content must be labelled "Flight
data from Avinor", linked to avinor.no and close to the data; every result carries that label.

**Rate limits:** Avinor asks that flight times be fetched at most every three minutes and cached,
and that end users never reach its service directly. Kildeverk caches flight times for three
minutes and the airport, airline and status names for a day, and spends at most 20 calls a minute.

**Behaviour worth knowing:** the feed is ISO-8859-1 XML. Times are UTC.

**Known gaps:** only airports in Avinor's feed (Avinor's own and some others, such as Sandefjord
Torp). Avinor gives no guarantee that the content is complete or up to date.

<a id="kartverket"></a>
### Kartverket: addresses, place names and elevation

**What it covers:** three open APIs from the Norwegian Mapping Authority.
- `addresses_search` finds official addresses from the cadastre. You can search by free text
  (`Munkegata 1 Trondheim`), postcode or municipality code, or find the addresses nearest a point.
  Each address has its coordinates, postcode, municipality and property numbers (gnr/bnr/fnr).
- `places_search` searches the central place-name register (SSR) for mountains, lakes, rivers,
  islands, farms, towns and more. You can search by name, with wildcards or fuzzy matching, or near
  a point, and filter by kind of place, municipality or county. Each place lists every spelling and
  language the register holds, including Sámi and Kven names.
- `terrain_elevation` gives the height above sea level at up to 50 points. Lakes give their surface
  height, and the sea gives its depth as a negative value. Each value says which model it came from.
- `regions_at_point` tells you which municipality and county a coordinate lies in. Its codes work in
  every tool that filters by municipality or county, so it joins a location to statistics,
  companies, addresses and warnings. Municipalities include their sea territory; a point beyond it,
  abroad, or on Svalbard or Jan Mayen (which have no municipalities) answers `NOT_FOUND`. Give a
  `date` to also learn which municipality and county the point was in then: today's municipality is
  followed back through [SSB Klass](#ssb_klass). When several municipalities later merged into
  today's one, all of them are listed and `certain` is false, because Klass records codes rather
  than borders.

**Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), per Kartverket's
[terms of use](https://www.kartverket.no/api-og-data/vilkar-for-bruk), which ask for the credit
"© Kartverket". The place-name register also has database protection, and Kartverket asks that
systematic use credit SSR, so place results carry a note saying so.

**Rate limits:** none published. Kildeverk spends at most 25 calls a minute.

**Caching:**
- Addresses and place names: 24 hours.
- Elevation and the list of kinds of place: 7 days.

**Behaviour worth knowing:**
- Kinds of place are named in Norwegian, as the register names them: `Fjell` (mountain), `Innsjø`
  (lake), `Elv` (river), `Øy` (island), `Gard` (farm). An unknown kind is answered with close
  matches.
- The address API returns at most 10,000 matches and the place-name API 5,000; results say how many
  matched in total.
- Searching near a point cannot be combined with a text search. Point searches for place names
  return no municipality or county, because the API leaves them out there.
- Depths are interpolated from depth contours and must not be used for navigation.
- The elevation API takes coordinates as (east, north); Kildeverk takes `lat` and `lon` and
  converts them.

**Known gaps:**
- Property data beyond the address, such as owners and areas, is not included.
- Points outside Norway and its waters have no elevation.

<a id="norges_bank"></a>
### Norges Bank: exchange rates and the policy rate

**What it covers:** the central bank's own published rates.
- `currency_exchange_rates` gives how many kroner a currency costs, for about 40 currencies and the
  krone's trade-weighted indices (`I44`, `TWI`). Rates are daily on business days, or monthly or
  annual averages. Leave out `start` for the latest rate.
- `rates_policy_rate` gives the key policy rate now, the date it took effect, and every change since
  a given date, with the size of each change.

**Licence:** none stated. Norges Bank publishes this as open data, but its
[open-data page](https://www.norges-bank.no/en/topics/Statistics/open-data/) gives no licence or terms.
Results therefore say "No licence stated by the publisher" instead of naming one.

**Rate limits:** none published. Kildeverk spends at most 25 calls a minute.

**Caching:**
- Latest rates and the policy rate: 1 hour.
- Periods ending more than two days ago: 24 hours.

**Behaviour worth knowing:**
- Some currencies are quoted per 100 units (JPY, SEK, DKK and others). Each row gives Norges Bank's
  quote (`nok` for `per` units) and the rate for one unit (`nok_per_unit`).
- Currencies Norges Bank has stopped publishing, such as HRK after the euro changeover, still answer.
  A note says when they were last quoted.
- An unknown code next to known ones is reported in a note. If every code is unknown, the error
  lists the codes Norges Bank publishes.
- The policy rate's change dates are the first business day at the new rate, not the meeting date.

**Known gaps:**
- Other interest rates, such as NOWA and government bond yields, are not exposed yet.

<a id="nve_varsom"></a>
### NVE Varsom: flood, landslide and avalanche warnings

**What it covers:** the warnings NVE publishes on [varsom.no](https://www.varsom.no/).
- `hazards_flood_landslide` gives flood and landslide warnings for all of Norway, a county or a
  municipality. Each warning has its level (green, yellow, orange, red), when it applies, its title,
  what to expect, the causes, consequences and advice, and the counties and municipalities it covers.
  By default it covers today and the next two days, yellow and above. Any past period of up to 31 days
  works too, so the August 2023 storm Hans is still there, at red.
- `hazards_avalanche` gives avalanche forecasts by forecasting region or by point. Each forecast has
  the danger level (1 low to 5 very high), a summary, and its avalanche problems: type, cause,
  probability, trigger, size, and the aspects and heights affected. It also has advice and the
  forecaster's assessment. With no region or point, it lists every region's level and id, highest
  danger first.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), stated in NVE's documentation for the
[flood](https://api.nve.no/doc/flomvarsling/), [landslide](https://api.nve.no/doc/jordskredvarsling/)
and [avalanche](https://api.nve.no/doc/snoeskredvarsel/) APIs. NVE asks for the credit "Varsler fra
Flomvarslingen / Jordskredvarslingen / Snøskredvarslingen i Norge og www.varsom.no", and asks users not
to leave warnings out based on their own judgement. Kildeverk never filters a warning except by the
level you ask for.

**Rate limits:** none published. Kildeverk spends at most 25 calls a minute.

**Caching:**
- Current warnings: 10 minutes.
- Past periods: 24 hours.
- The list of avalanche regions: 7 days.

**Behaviour worth knowing:**
- Nationwide, NVE lists only warnings above green. Ask for a municipality to see green days too
  (`min_level: 1`).
- A county query returns one row per municipality upstream. Kildeverk merges rows that share a
  warning id into one warning listing all its municipalities.
- Times are Norwegian local time with their offset. Flood and landslide days run from 07:00 to 07:00.
- Avalanche forecasts are published from about December to June. Outside the season every region
  says "no rating" (level 0), and a note says why.
- The avalanche danger assessment is often in Norwegian even when English is asked for. The summary,
  problems and advice are in English.
- Avalanche heights are read from NVE's height codes: above, below, between two heights, or outside
  them.

**Known gaps:**
- Warnings are forecasts. NVE gives no guarantee of timeliness, so check varsom.no before acting.
- Municipality and county codes must be current (since 2024). [SSB Klass](#ssb_klass) can map older
  codes.

<a id="nve_regobs"></a>
### Regobs: field observations

**What it covers:** Regobs is the observation system behind varsom.no, where NVE's observers and
the public report what they see on the ground. `hazards_field_observations` returns observations
near a point of snow and avalanches, landslides, floods and ice: time, place, municipality and
forecasting region, height, the observer's username and competence level, a short text for each
kind of observation (avalanche activity, danger signs, snow cover, landslides, water level, ice
thickness and more), the number of pictures, and a link to the observation on regobs.no. Newest
first; by default the last two weeks within 20 km.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), as stated in
[NVE's Regobs API documentation](https://api.nve.no/doc/regobs/). Regobs requires that Regobs.no
and each observer's username are credited, and every result's notes say so.

**Rate limits:** none published. Kildeverk spends at most 30 calls a minute; each search is two
calls, one for the observations and one for the total count.

**Privacy:**
- Usernames are returned because the licence requires crediting them; nothing else about observers
  is. A username that is an e-mail address is cut (`ola@nve.no` becomes `ola@nve`) so that it
  credits the observer without publishing an address.
- Pictures are counted, not returned, and the test fixtures drop them along with observer ids.

**Known gaps:** observations are what people report, published as they are. Texts are in the
observer's language and shortened past 600 characters; the link has the full observation.

<a id="datanorge"></a>
### data.norge.no: the national data catalogue

**What it covers:** the catalogue where Norwegian public bodies describe their datasets and APIs,
run by the Norwegian Digitalisation Agency (Digdir).
- `catalog_search` searches it by text, and filters by EU theme, publisher, file format, open-data
  status or recent change. Each entry has its title, a short description, publisher, themes, formats,
  keywords, and links to its data.norge.no page and the publisher's own description.

It finds where data lives and who publishes it. It does not return the data itself, and it is the
fallback for topics the other tools don't cover.

**Licence:** none stated for the catalogue metadata. The search API's
[documentation](https://search.api.fellesdatakatalog.digdir.no/swagger-ui.html) gives none, so results
say "No licence stated". Each dataset's own licence is on its data.norge.no page.

**Rate limits:** none published. Kildeverk keeps to 10 calls a minute, because this is a search
service run for people using data.norge.no.

**Caching:** 1 hour.

**Behaviour worth knowing:**
- Titles and descriptions are what each publisher wrote, often in Norwegian. Norwegian words
  (`befolkning`, `vær`) usually find more than English ones.
- To search one publisher, take `publisher.path` from any result, for example
  `/STAT/972417807/971526920` for Statistics Norway. A shorter path covers everything below it:
  `/KOMMUNE` is every municipality.
- Without a query, results come newest first.
- Results are paged. `page` asks for the next one, and the result says how many pages there are.

**Known gaps:**
- Concepts, information models and public services in the catalogue are not searched.
- How complete and accurate an entry is depends on its publisher.

<a id="kartverket_sea_level"></a>
### Kartverket: water level and tides

**What it covers:** sea level along the Norwegian coast from Kartverket's Hydrographic Service.
- `sea_level` gives, for any coastal point or tide gauge, the observed water level, the tidal
  prediction, the effect of wind and air pressure, and a forecast for the next few days. With
  `kind: "tide_table"` it gives the times and heights of high and low water instead. Heights can be
  above chart datum (as in tide tables and sea charts), mean sea level, or NN2000.

Observations exist only at the roughly 25 permanent tide gauges. Elsewhere every value is modelled
from the nearest gauge, and the result names that gauge and says how it was adjusted.

**Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The
[API protocol](https://vannstand.kartverket.no/tideapi_en.html) asks that the Norwegian Mapping
Authority, Hydrographic Service, be credited.

**Rate limits:** none published, but Kartverket asks users to cache and not to poll heavily.
Kildeverk spends at most 20 calls a minute.

**Caching:**
- Periods reaching into the last day: 15 minutes.
- Older periods: 24 hours.
- Calls without a period round "now" to the hour, so they share a cached response within the hour.

**Behaviour worth knowing:**
- This API answers in XML; Kildeverk's upstream gateway parses it with the same cache, budget and
  provenance as every JSON source.
- Times are Norwegian local time with their offset. The API reads requested times as UTC+1 all
  year, so Kildeverk converts them; without that, summer periods would start an hour late.
- A point inland or far offshore answers `NOT_FOUND` with Kartverket's reason.
- Water level periods can be up to 31 days, tide tables up to a year.

`sea_level_extremes` gives, for a point on the coast or a gauge, the storm-surge levels reached on
average once in 1, 5, 10, 20, 50, 100, 200 and 1000 years, the low-water return levels, the
highest and lowest levels ever observed (with the date, or Kartverket's note when it is a year or a
named storm), the tidal levels from highest astronomical tide down to chart datum, and the land
uplift. It works in NN2000 by default, the height system of maps and buildings, so the levels
compare directly with terrain heights. Sea level rise is not included.

<a id="nve_reservoirs"></a>
### NVE reservoir statistics: hydropower reservoir fill

**What it covers:** how full Norway's hydropower reservoirs are. NVE measures the 490 largest
reservoirs every week.
- `energy_reservoirs` gives the fill in per cent and TWh, the capacity, and the change from the week
  before. Areas are the whole country, the electricity price areas NO1-NO5, or the watercourse
  regions VASS1-VASS4. Each week also carries the lowest, median and highest fill for the same week
  over the last 20 years. By default it gives the latest week and the date of the next publication;
  give years for history back to 1995.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), stated in
[NVE's API documentation](https://api.nve.no/doc/magasinstatistikk/).

**Rate limits:** none published. Kildeverk spends at most 10 calls a minute.

**Caching:** the latest week for 1 hour; the full history and the 20-year range for 6 hours.

**Behaviour worth knowing:**
- Figures are published on Wednesdays for the week before. A week's date is the Sunday its
  measurements refer to.
- History comes from one upstream response covering every area since 1995, so any range of years
  costs the same single cached call.

**Known gaps:**
- Individual reservoirs are not published, only area totals.

<a id="elhub"></a>
### Elhub: electricity consumption and production

**What it covers:** metered electricity from Elhub, the national data hub every Norwegian meter
reports to.
- `electricity_municipality` gives one municipality's consumption, per day or per hour, split into
  private customers (homes and cabins), business (services) and industry, with each group's share
  and number of metering points. It also gives the production capacity installed in the
  municipality by kind (hydro, wind, solar, thermal, other), including how much of it is on
  prosumer meters such as rooftop solar. Accepts codes, old or current, and names.
- `electricity_price_areas` gives consumption and production per day and for the period in the
  price areas NO1-NO5: consumption by households, cabins and primary, secondary and tertiary
  industry, and production by hydro, wind, solar, thermal and other. With all five areas it adds a
  total for Norway.
- `municipality_profile` and `compare_municipalities` include the last seven days' use per
  inhabitant, in total and for homes and cabins, and the installed capacity.

**Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), credit Elhub, as stated in
the terms of use on [Elhub's API portal](https://api.elhub.no/). The public APIs need no key.

**Rate limits:** 5 calls a second per user (IP address), and Elhub asks users not to overload it.
Kildeverk spends at most 4 a second.

**Caching:** periods ending in the last three days for 1 hour; older ones for a day.

**Behaviour worth knowing:**
- Periods are whole days in Norwegian time, from 2021-01-01, at most 31 days per call; by default
  the last seven full days.
- Elhub serves municipality consumption one day per request, so a week costs seven calls (plus one
  for capacity). Price areas take up to a month per request.
- The autumn clock change gives a day of 25 hours, and the hourly rows keep both 02:00 hours.
- Figures are what grid companies report, and Elhub revises them as late readings arrive.
- `net_mwh` for a price area is production minus metered consumption. Grid losses are in neither,
  so it shows roughly whether an area produced more than it used, not its exchange with
  neighbours.

**Known gaps:**
- Production per municipality: Elhub's municipal figures cover only prosumers, so only capacity
  is shown.
- Exchange between price areas, 15-minute values and Norgespris figures are not exposed yet.
- Datasets by industry code or supplier need Maskinporten access.

<a id="stortinget"></a>
### Stortinget: cases, votes and members

**What it covers:** the Norwegian parliament's own open data.
- `parliament_cases` lists the cases in a session (the current one by default): bills, budgets,
  members' proposals and more. You can filter by words in the title, type, status or committee.
- `parliament_case` gives one case: committee, rapporteurs, topics, the decision, and every vote on
  it. Each vote has its result and counts and, when recorded by name, how each party voted.
- `parliament_members` lists the members sitting today, or those of an electoral period, with
  party, constituency and committees, and a count per party.
- `parliament_questions` lists the questions members put to ministers in a session: written
  questions (in full), questions from question time, or interpellations, filtered by words (each
  matching from the start of a word), the minister, the asker's party and whether it is answered.
  Each has the asker and constituency, the minister, the dates and a link to the question and its
  answer on stortinget.no. The API's single-question endpoint fails for current questions, so
  answer texts are left to that link.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), per Stortinget's
[terms of use](https://data.stortinget.no/om-datatjenesten/bruksvilkar/). The terms require
Stortinget to be named as the source, and say data must not be presented in a misleading way.

**Rate limits:** 100 calls a minute, answered with 429 above that. Kildeverk spends at most 50.

**Caching:**
- Case lists, cases and votes: 1 hour.
- Sessions and members: 24 hours.

**Behaviour worth knowing:**
- Titles and decisions are in Norwegian. Search with Norwegian words (`strømpris`, `skatt`).
- Many votes are by acclamation. They have no counts and no names, and the result says so.
- The party breakdown counts each representative's recorded vote as for, against or absent, and
  matches Stortinget's own totals.
- `dealt_with` means the committee has dealt with the case, as Stortinget defines it.
- Stortinget answers an unknown case id with HTTP 500. Kildeverk reports that as `NOT_FOUND`,
  saying the id probably does not exist.
- Members' e-mail addresses and birth dates are never returned, and are scrubbed from fixtures.

**Known gaps:**
- Committees are given only for members sitting today, not for past periods.
- Hearings and debates are not exposed yet; nor are the texts of ministers' answers.

<a id="vegvesen_traffic"></a>
### Statens vegvesen: traffic counts

**What it covers:** the Norwegian Public Roads Administration's traffic registration points,
about 10,000 of them on roads and cycle paths.
- `traffic_find_points` finds points by name, municipality, county, road (`E39`, `Rv7`) or
  distance from a point, for vehicles or bicycles.
- `traffic_volumes` gives vehicles per hour or per day at a point, by direction and split into
  light and heavy vehicles, with how much of each period was counted. With `resolution: "annual"`
  it gives the annual average daily traffic (ÅDT) for every year the point has counted.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), per Statens vegvesen's
[data catalogue](https://dataut.vegvesen.no/en/dataset/trafikkdata). No key is needed.

**Rate limits:** none published. Kildeverk spends at most 25 calls a minute.

**Caching:**
- Point lists and annual averages: 24 hours.
- Counts for periods ending in the last two days: 15 minutes.
- Older counts: 24 hours.

**Behaviour worth knowing:**
- The full list of points is a 5 MB response, so searches are narrowed upstream by name or county.
  A search near a point first asks [Kartverket](#kartverket) which county the point is in, and
  then says that points across the county border are not included. Provenance lists both calls.
- Light vehicles are under 5.6 m, heavy ones 5.6 m or longer. Vehicles whose length was not
  measured are in neither group, so the two can sum to a little less than the total.
- Rows covering under 95% of their period are flagged in a note; their counts are incomplete.
- The API pages at 100 rows, so hourly periods are capped at 7 days and daily ones at a year.

**Known gaps:**
- Hourly is the finest resolution; single vehicles and speeds are not public.
- Traffic indices and the national road database (NVDB) are not exposed yet.

<a id="udir_nsr"></a>
### National School Register (NSR)

**What it covers:** Udir's register of every primary and secondary school in Norway, public and
private, and Norwegian schools abroad.
- `schools_search` finds schools by name, municipality or county, optionally one level (`primary`
  or `secondary`) or kind of ownership.
- `schools_get` gives one school: pupils, staff, grades, owner, Bokmål or Nynorsk, address,
  position, website, and when it opened or closed.

**Licence:** [NLOD](https://data.norge.no/nlod/en/2.0), stated in the
[API documentation](https://data-nsr.udir.no/swagger/index.html).

**Rate limits:** none published. Kildeverk spends at most 25 calls a minute.

**Caching:** 6 hours. NSR imports from the Central Coordinating Register each night.

**Known gaps:**
- Kindergartens are in a different register and are not included.
- Pupil numbers are the register's latest figure, not a time series.

<a id="deploy-your-own"></a>

<a id="ordbokene"></a>
### Ordbøkene: Bokmålsordboka and Nynorskordboka

**What it covers:** the official Norwegian dictionaries from the University of Bergen and the
Language Council of Norway. `dictionary_lookup` gives, for a word in Bokmål, Nynorsk or both, each
article's headwords, word class and gender, every standard inflected form, the meanings with
examples, and the word's origin, with a link to ordbøkene.no. `*` matches any letters. A word that
is not a headword gets similar words instead.

**Licence:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.no), for the content and
for data fetched through the API, commercial use included
([UiB's terms](https://www.uib.no/en/node/182212)). UiB asks for this credit wherever the content
is shown, and every result carries it: "Bokmålsordboka/Nynorskordboka, Universitetet i Bergen og
Språkrådet, ordbøkene.no, CC-BY 4.0".

**Rate limits:** none published. Kildeverk spends at most 120 calls a minute; a lookup is one
search, one call per article and, once a week, the list of abbreviations.

**Behaviour worth knowing:** the dictionaries store texts with placeholders and abbreviations
(`norr.`, `besl`); Kildeverk fills them in from the dictionaries' own list, so results read as
plain Norwegian ("norrønt fjǫrdr; beslektet med fare").

**Known gaps:** explanations are in Norwegian, and compounds that are not headwords are not split.

<a id="usgs_earthquakes"></a>
### USGS Earthquake Catalog

**What it covers:** `hazards_earthquakes` gives earthquakes near a point from the U.S. Geological
Survey's worldwide catalogue: time, magnitude and its type, depth, place, distance from the point,
whether USGS has reviewed the event, how many people reported feeling it, and the event page. By
default the last year within 500 km and magnitude 2.5 and up, newest first; it can order by
magnitude instead.

**Licence:** USGS-produced data are in the U.S. public domain; USGS asks for credit to the U.S.
Geological Survey ([copyrights and credits](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)).

**Rate limits:** at most 20,000 events per query. Kildeverk spends at most 60 calls a minute and
asks for one event more than the limit, to say whether there are more.

**Caching:** searches ending in the last 30 days for 10 minutes; older ones for a day.

**Known gaps:**
- Outside the United States the catalogue misses many earthquakes below about magnitude 4. The
  Norwegian National Seismic Network records the smaller Norwegian ones, but its licence is unclear,
  so it is not used.
- Recent events are automatic estimates at first and can be revised.


<a id="worldbank_wdi"></a>
### World Bank World Development Indicators

**What it covers:** `world_indicators` gives one of the World Bank's World Development Indicators for
Norway and other countries or regions (`WLD` for the world, `EUU` for the EU, `OED` for the OECD):
each country's latest value, ranked, or every year in a range. It takes a WDI code or a common name
(`gdp_per_capita`, `life_expectancy`, `co2_per_capita`, `renewable_energy_share`,
`unemployment`, …), and by default compares the Nordic countries. The result carries the World
Bank's definition of the indicator.

**Licence:** the World Development Indicators are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
([catalogue entry](https://datacatalog.worldbank.org/search/dataset/0037712/World-Development-Indicators)).
Other World Bank datasets can carry other licences, so an indicator from any other source (such as
the WDI archives) is refused, with the current WDI indicator suggested where there is one.

**Rate limits:** none published. Kildeverk spends at most 60 calls a minute.

**Behaviour worth knowing:** one unknown country code makes the World Bank reject a whole request,
so Kildeverk then asks country by country and reports only the unknown codes.

**Known gaps:** yearly figures, often a year or two behind; no search, so give a code or a common
name.

## Deploy your own

The service is one process with one SQLite cache, so it runs on one small machine. The
[Dockerfile](Dockerfile) builds the website into the image; [fly.toml](fly.toml) runs it on
[Fly.io](https://fly.io) in Stockholm with a 1 GB volume for the cache, for a few euros a month.

```sh
fly launch --no-deploy --copy-config --name <your-app>   # or keep app = "kildeverk" if free
fly volumes create kildeverk_cache --size 1 --region arn
fly secrets set KILDEVERK_CONTACT=you@example.com        # required by MET Norway
fly secrets set KILDEVERK_FROST_CLIENT_ID=... KILDEVERK_NVE_API_KEY=...   # optional
fly deploy
```

Anywhere else that runs a container works the same way. Mount a volume at `/data`, and set
`KILDEVERK_CLIENT_IP_HEADER` only if a proxy in front overwrites that header with the caller's
address; otherwise leave it empty.

| Setting | Default | What it does |
| --- | --- | --- |
| `KILDEVERK_DEPLOYMENT` | `local` (`public` in the image) | `public` turns on per-client limits and allows any Host header |
| `KILDEVERK_CONTACT` | empty | Added to the User-Agent; MET Norway requires one |
| `KILDEVERK_CACHE_PATH` | `~/.cache/kildeverk/responses.sqlite` | The response cache |
| `KILDEVERK_SITE_DIR` | none | A built website to serve at `/` (`kildeverk site --out <dir>`) |
| `KILDEVERK_CLIENT_LIMIT_PER_MINUTE`, `_BURST` | 60, 20 | Per-client budget on a public deployment |
| `KILDEVERK_CLIENT_IP_HEADER` | empty | Trusted proxy header naming the caller, e.g. `Fly-Client-IP` |
| `KILDEVERK_FROST_CLIENT_ID`, `KILDEVERK_NVE_API_KEY` | empty | Keys for Frost and HydAPI |
| `KILDEVERK_ENTUR_CLIENT_NAME` | `kildeverk-<deployment>` | Sent to Entur as `ET-Client-Name` |

`/healthz` answers without calling any upstream, for platform health checks.

`/v1/feeds/warnings/<municipality>.atom` is an Atom feed of the weather warnings for the
municipality's county, the flood and landslide warnings for the municipality, and the avalanche
forecasts at moderate or above for every forecasting region that covers part of it, for any feed
reader. It takes a code (old or current) or a name, and is built from the same tools, so it shares
their budgets and cache. On a quiet day it holds one entry saying there are no warnings.

## What it is not

- **Not a mirror.** Kildeverk reads live data and caches responses briefly. If a publisher is down
  and nothing is cached, the call fails with a retryable error.
- **Not a guarantee.** One person runs it, on one machine, with no SLA. Warnings and forecasts in
  particular should be checked with their publisher before anyone acts on them.
- **Not complete.** Each source's section lists what is left out. Much of the text, such as case
  titles and avalanche assessments, is in Norwegian, because that is how it is published.
- **Not a single budget per user.** On the hosted service, the upstream budgets are shared. Heavy
  use is better served by a local install, which has budgets of its own.

## Development

```sh
uv sync
uv run pytest            # offline: replays recorded upstream responses
uv run pytest -m live    # a few real calls per source
uv run python scripts/record.py ssb_statbank   # re-record a source's fixtures
uv run python scripts/build_recipes.py         # re-run the website's worked questions live
uv run kildeverk site --out site/dist          # build the website
```

`eval/` holds an evaluation set: 32 questions an agent should answer with these tools, each with
the reference call that answers it, live-built truth (`uv run python -m eval.build_truth`) and a
scorer. Questions about fixed periods keep their answers; those marked `moves` follow the latest
figures and need truth rebuilt before a run. `eval/run.py` asks a model each question with only
Kildeverk's tools (and, as a baseline, with none), scores the submitted answers and reports
accuracy, tool calls and tokens:

```sh
uv run --group eval python -m eval.run --arms tools,notools --out eval/runs/run.jsonl
```

Every run spends model tokens; it needs Anthropic credentials (`ANTHROPIC_API_KEY` or an
`ant auth login` profile).

Each source lives in `src/kildeverk/sources/<id>/`:
- `spec.py`: licence, limits, cache lifetimes, coverage and gaps.
- `models.py`: pydantic input and output models (in `ops.py` for the smaller sources).
- `ops.py`: the handlers and the operation declarations.

`sources/registry.py` is the only place a source or tool is registered. The MCP tool list, the REST
routes, the OpenAPI document, `sources_list` and the website catalogue (`kildeverk catalogue`) are
all generated from it.

Tests enforce that every source has a licence URL, a fixture cassette and a section in this README,
and that every tool's examples validate against its own input model.

## Licence

The code is MIT licensed (see [LICENSE](LICENSE)). The data returned belongs to its publishers and
comes under each source's own licence, which every result states.
