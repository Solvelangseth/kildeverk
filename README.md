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
| MET Norway (Locationforecast, Frost) | planned | |
| NVE HydAPI | planned, once its terms are confirmed | |
| Entur (stops, departures) | planned | |
| Kartverket (addresses, place names, elevation) | planned | |

Two tools describe the service itself: `sources_list` and `service_status`.

**Not included, and why:**
- Norges Bank's own open-data pages state no licence. It will be added if the bank confirms the terms.
- data.norge.no's search API is documented as internal and liable to change, and it states no licence for its metadata.
- NVE's flood and landslide warning API states no licence.
- No source is scraped, and no undocumented endpoint behind a website is used.

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
