# Kildeverk

Live Norwegian public data for AI assistants and developers. Kildeverk is a hosted MCP server and
JSON API over official data services: statistics, companies, weather, water, warnings, transport,
maps, the sea, money, energy, parliament, laws, public tenders, roads, schools, food inspections
and development aid. Every result says exactly where it came from: the source, its licence, the
exact upstream URL, when it was retrieved, and a citation line you can paste.

**Website:** [kildeverk.fly.dev](https://kildeverk.fly.dev) · **MCP:** `https://kildeverk.fly.dev/mcp` ·
**API docs:** [kildeverk.fly.dev/docs](https://kildeverk.fly.dev/docs)

No sign-up and no key.

## Connect

Claude Code, as a plugin from this repository:

```sh
/plugin marketplace add Solvelangseth/Kildeverk
/plugin install kildeverk@kildeverk
```

Or as a plain MCP server:

```sh
claude mcp add --transport http kildeverk https://kildeverk.fly.dev/mcp
```

Any other MCP client (Claude Desktop, ChatGPT, Cursor, VS Code):

```json
{
  "mcpServers": {
    "kildeverk": { "type": "http", "url": "https://kildeverk.fly.dev/mcp" }
  }
}
```

The JSON API answers plain HTTP:

```sh
curl "https://kildeverk.fly.dev/v1/weather/forecast?lat=59.91&lon=10.75"
```

## Fewer tools

A client lists every tool by default. One that needs only some areas, for a small model or a
tight context, names them in the URL: `https://kildeverk.fly.dev/mcp?tools=sea,law`.

| Toolset | Covers |
| --- | --- |
| `statistics` | SSB's Statbank: any statistic, a region over time, rankings |
| `regions` | municipalities and counties: codes, reforms, profiles, comparisons, a point's overview |
| `maps` | addresses, elevation, map layers at a point, Svalbard place names |
| `weather` | forecasts, nowcast, warnings, observations, normals, sun and moon, air quality |
| `hazards` | floods, landslides, avalanches, earthquakes, field observations, rivers |
| `nature` | species observations and red-listed and alien species records |
| `sea` | sea forecasts and levels, storm surge, ships, fish farms, salmon lice, fish buyers |
| `energy` | electricity use and production, reservoirs, oil and gas fields and wells |
| `transport` | public transport, flights, roads, traffic counts, road messages |
| `business` | companies, their accounts, food inspections (smilefjes), Arbeidstilsynet approvals |
| `tenders` | public tenders and who won them |
| `finance` | exchange rates, policy rates, NOWA and bond yields, the ECB |
| `law` | Norwegian laws and regulations, EU legislation |
| `parliament` | Stortinget: cases, votes, questions, hearings, debates, members |
| `health` | health statistics |
| `education` | schools, kindergartens, the Pupil Survey, universities, journal levels |
| `aid` | Norwegian development aid per agreement, from Norad |
| `international` | World Bank and Eurostat |
| `about` | service status, citations, the dictionaries |

`all` (or no `tools`) lists everything. A tool left out of the list still runs when called by name.

## Sources and licences

The website lists every source, what it covers and the licence its publisher states. Over MCP,
call `sources_list` or read the `kildeverk://sources` resource. The data belongs to its publishers
and comes under each source's own licence, which every result states. Kildeverk is not affiliated
with any of them.

## Limits

Each client address may make 60 calls a minute, with bursts of 20. Above that, calls answer HTTP
429 with a `RATE_LIMITED` error and a `Retry-After` header.

## This repository

This repository holds what clients need to find and connect to the hosted service: the Claude
Code plugin (`.claude-plugin/`), the MCP registry entry (`server.json`) and an uptime check that
runs every 15 minutes. The server's own code is not published here.

Questions and bug reports: [open an issue](https://github.com/Solvelangseth/Kildeverk/issues).

The files in this repository are MIT licensed (see [LICENSE](LICENSE)).
