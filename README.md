# Kildeverk

Live Norwegian public data for AI agents and people. Kildeverk is an MCP server
and a read-only JSON API over a small set of official Norwegian data services.
Every result says exactly where it came from.

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
| [MET Norway Frost](#met_frost): needs a free client id | ✅ available | `weather_find_stations`, `weather_station_elements`, `weather_observations` |
| [NVE HydAPI](#nve_hydapi): needs a free key | ✅ available | `water_find_stations`, `water_observations` |
| [Entur Geocoder](#entur_geocoder): stop places | ✅ available | `transit_find_stops` |
| [Entur Journey Planner](#entur_journeyplanner): departures | ✅ available | `transit_departures` |
| Kartverket (addresses, place names, elevation) | planned | |

Two tools describe the service itself: `sources_list` and `service_status`.

**Not yet included:**
- Norges Bank (exchange rates and the policy rate). Its open-data pages state no licence, so its
  results will say "licence not stated" rather than name one.
- NVE's flood and landslide warnings (Varsom). These also state no licence.
- data.norge.no's dataset search, which is documented as internal and liable to change.

No source is scraped, and no undocumented endpoint behind a website is used. Kildeverk is
non-commercial. Every result names the licence its source states, or says that none is stated.

Kildeverk reads live data. It does not mirror or archive anything beyond a short-lived response cache.

## Use it

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
- Flood and landslide warnings (Varsom) come from a different NVE service and are not included.
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

## Development

```sh
uv sync
uv run pytest            # offline: replays recorded upstream responses
uv run pytest -m live    # a few real calls per source
uv run python scripts/record.py ssb_statbank   # re-record a source's fixtures
```

Each source lives in `src/kildeverk/sources/<id>/`:
- `spec.py`: licence, limits, cache lifetimes, coverage and gaps.
- `models.py`: pydantic input and output models.
- `ops.py`: the handlers and the operation declarations.

`sources/registry.py` is the only place a source or tool is registered. The MCP tool list, the REST
routes, the OpenAPI document, `sources_list` and the website catalogue (`kildeverk catalogue`) are
all generated from it.

Tests enforce that every source has a licence URL, a fixture cassette and a section in this README,
and that every tool's examples validate against its own input model.

## Licence

The code is MIT licensed (see [LICENSE](LICENSE)). The data returned belongs to its publishers and
comes under each source's own licence, which every result states.
