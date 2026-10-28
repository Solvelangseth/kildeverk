# Kildeverk

Live Norwegian public data for AI agents and people. Kildeverk is an MCP server
and a read-only JSON API over 18 official data services from 11 Norwegian publishers:
statistics, companies, weather, water, warnings, transport, maps, the sea, money,
energy, parliament, roads and schools. Every result says exactly where it came from.

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
| [MET Norway Locationforecast](#met_locationforecast) | ✅ available | `weather_forecast` |
| [MET Norway MetAlerts](#met_metalerts): weather warnings | ✅ available | `weather_warnings` |
| [MET Norway Frost](#met_frost): needs a free client id | ✅ available | `weather_find_stations`, `weather_station_elements`, `weather_observations` |
| [NVE HydAPI](#nve_hydapi): needs a free key | ✅ available | `water_find_stations`, `water_observations` |
| [Entur Geocoder](#entur_geocoder): stop places | ✅ available | `transit_find_stops` |
| [Entur Journey Planner](#entur_journeyplanner): departures | ✅ available | `transit_departures` |
| [Kartverket](#kartverket): addresses, place names, elevation, municipality at a point | ✅ available | `addresses_search`, `places_search`, `terrain_elevation`, `regions_at_point` |
| [Kartverket water level and tides](#kartverket_sea_level) | ✅ available | `sea_level` |
| [Norges Bank](#norges_bank): exchange rates and the policy rate | ✅ available | `currency_exchange_rates`, `rates_policy_rate` |
| [NVE Varsom](#nve_varsom): flood, landslide and avalanche warnings | ✅ available | `hazards_flood_landslide`, `hazards_avalanche` |
| [data.norge.no](#datanorge): the national data catalogue | ✅ available | `catalog_search` |
| [NVE reservoir statistics](#nve_reservoirs): hydropower reservoir fill | ✅ available | `energy_reservoirs` |
| [Stortinget](#stortinget): cases, votes and members | ✅ available | `parliament_cases`, `parliament_case`, `parliament_members` |
| [Statens vegvesen traffic data](#vegvesen_traffic) | ✅ available | `traffic_find_points`, `traffic_volumes` |
| [National School Register](#udir_nsr) | ✅ available | `schools_search`, `schools_get` |

Three tools combine sources. `place_overview` takes a coordinate and returns its municipality and
county, elevation, the weather now and over the next six hours, weather, flood and landslide
warnings in force, the nearest stops and named places nearby, and ready-made follow-up calls. It
calls the other tools, so each part keeps its own provenance, budget and cache, and a part that
fails becomes a note while the rest still answers. `municipality_profile` takes a municipality code,
old or current, or a name, follows it through the reforms with [SSB Klass](#ssb_klass), and returns
population and its change, registered companies and the largest employers, schools by level and
ownership, traffic counting points, and the warnings in force. Its population series is SSB's,
summed to today's borders, so the change reaches back past the 2020 and 2024 reforms.
`compare_municipalities` puts two to five of these side by side.

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
**prompts**: `profile_place`, `profile_municipality`, `find_statistic` and `compare_places`.

No source is scraped, and no undocumented endpoint behind a website is used. Kildeverk is
non-commercial. Every result names the licence its source states, or says that none is stated.

Kildeverk reads live data. It does not mirror or archive anything beyond a short-lived response cache.

## Use it

### The hosted service

The hosted service is not live yet. Everything needed to run it is in this repository (see
[Deploy your own](#deploy-your-own)), and this section will give its address once it is up.

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
  "truncated": false
}
```

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
- Financial statements, the register of beneficial owners and corporate group structure are not
  included.

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

**Setup:** Frost needs a free client id from
[frost.met.no](https://frost.met.no/auth/requestCredentials.html). Set it as
`KILDEVERK_FROST_CLIENT_ID`. Without it, these three tools answer `NOT_CONFIGURED` and the forecast
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
- Journey planning from A to B is not exposed yet.
- Groups of stop places (all of "Oslo", say) are not searched; use a stop place or a quay.

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
  abroad, or on Svalbard or Jan Mayen (which have no municipalities) answers `NOT_FOUND`.

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

**Known gaps:**
- Return levels (the 20-, 200- and 1000-year storm surge) are not exposed yet.

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

<a id="stortinget"></a>
### Stortinget: cases, votes and members

**What it covers:** the Norwegian parliament's own open data.
- `parliament_cases` lists the cases in a session (the current one by default): bills, budgets,
  members' proposals and more. You can filter by words in the title, type, status or committee.
- `parliament_case` gives one case: committee, rapporteurs, topics, the decision, and every vote on
  it. Each vote has its result and counts and, when recorded by name, how each party voted.
- `parliament_members` lists the members sitting today, or those of an electoral period, with
  party, constituency and committees, and a count per party.

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
- Questions to ministers, hearings and debates are not exposed yet.

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
uv run kildeverk site --out site/dist          # build the website
```

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
