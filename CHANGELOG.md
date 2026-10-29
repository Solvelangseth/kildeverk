# Changelog

## Unreleased

- `parliament_questions`: questions members of Stortinget put to ministers (written questions,
  question time, interpellations), searchable by words, minister, party and answer status.
- `sea_level_extremes`: storm-surge return levels, record sea levels and tidal levels at a place on
  the coast, from Kartverket, in NN2000 so they compare with heights on land.
- A new source, the World Bank's World Development Indicators: `world_indicators` compares Norway
  with other countries and regions on GDP, life expectancy, emissions and the rest.
- A new source, Avinor: `flights_airport` gives departures and arrivals at a Norwegian airport,
  with delays, gates and baggage belts, labelled "Flight data from Avinor" as Avinor requires.
- Test recordings keep non-UTF-8 bodies (Avinor's ISO-8859-1 XML) in their own encoding.
- A new source, Ordbøkene: `dictionary_lookup` looks a word up in Bokmålsordboka and
  Nynorskordboka, with meanings, examples, inflection, word class and origin.
- A new source, Regobs: `hazards_field_observations` gives field observations of avalanches,
  landslides, floods and ice near a point, crediting each observer by username as Regobs requires.
- A first source from outside Norway: `hazards_earthquakes`, earthquakes near a point from the
  U.S. Geological Survey's catalogue (public domain).
- `weather_normals`: a station's 30-year climate normals from Frost, and how each month of a
  given year compared with them.
- Three more MET Norway products: `weather_nowcast` (radar precipitation every five minutes for the
  next two hours), `sea_forecast` (waves, sea temperature and currents along the coast) and
  `air_quality_forecast` (the air quality index and pollutants hour by hour, and where the worst
  hour's pollution comes from). `place_overview` now says when rain starts or stops.
- A new source, Regnskapsregisteret, with `companies_accounts`: the last three years' revenue,
  results, assets, equity and debt for any company that files accounts, company and group, in the
  currency it reports in, with operating margin, equity ratio and revenue change.
  `municipality_profile` adds the latest revenue and result to its largest employers.
- A new source, Elhub, with two tools. `electricity_municipality` gives a municipality's
  electricity use per day or hour by private, business and industry, and its installed production
  capacity by kind. `electricity_price_areas` gives consumption and production in NO1-NO5.
  `municipality_profile` and `compare_municipalities` now include electricity use per inhabitant.
- The hosted service is live at https://kildeverk.fly.dev (MCP at `/mcp`).
- The website is in Norwegian and redesigned: a getting-started panel per client, example
  questions to copy, the recipes in Norwegian, tools grouped by theme with search, and code and
  result boxes that wrap and grow instead of scrolling. The tools stay in English.
- The container starts as root only to take ownership of the mounted cache volume, then runs the
  service as an unprivileged user.

## 0.2.0 — 2026-10-28

Tools that answer a question from several sources at once, and more ways to use the answers.

**New tools**
- `place_overview`: a coordinate's municipality, elevation, weather, warnings in force, nearest
  stops and named places, with follow-up calls.
- `municipality_profile`: population and its ten-year change, companies and largest employers,
  schools, traffic counting points and warnings, for any municipality code (old or current) or
  name.
- `compare_municipalities`: two to five municipalities side by side, including companies per
  1,000 inhabitants.
- `statistics_series`: one SSB statistic for one region over every year, unbroken across the
  2020 and 2024 reforms, using SSB's series for today's borders or rebuilding earlier years
  through Klass.
- `statistics_rank`: every municipality or county ranked on one statistic, or on its change since
  an earlier year, with Norway's figure for reference.
- `cite_sources`: any result's provenance as BibTeX and CSL-JSON.

**Changed**
- Municipality and county names are accepted wherever a code is (`companies_search`,
  `schools_search`, `traffic_find_points`, `addresses_search`, `places_search`,
  `hazards_flood_landslide`, `weather_warnings`), resolved through Klass.
- `regions_at_point` can say which municipality and county a point was in on a past date.
- Every result carries a `summary` of its provenance: publishers, licences, upstream responses,
  cache hits, stale parts and the oldest retrieval time.
- Provenance records the title of what was fetched.
- `service_status` counts calls, errors, cache hits and time per tool.

**Added**
- MCP resources (a guide to choosing a tool, and every source) and prompts, including one per
  website recipe.
- An Atom feed of warnings per municipality: `/v1/feeds/warnings/<municipality>.atom`.
- The website gained worked "Recipes", and "Copy as curl" and "Copy as MCP call" buttons.
- The OpenAPI document carries each tool's examples.
- Live tests run every tool's own examples; a weekly workflow refreshes the recipes.

**Fixed**
- SSB's summed-series codelists come in two spellings (`agg_KommSummer` with `K-` codes,
  `agg_KommSummerHist` with `K_` codes); both are recognised.
- Ranking chooses the newest period with real figures, ignoring SSB's placeholder zeros and
  periods listed as `..`.

## 0.1.0 — 2026-10-28

The first version: 18 sources from 11 publishers behind one MCP server and JSON API.

- SSB Statbank and Klass (with harmonisation across the 2020 and 2024 reforms), Brønnøysund
  Register Centre, MET Norway (Locationforecast, Frost, MetAlerts), NVE (HydAPI, Varsom,
  reservoir statistics), Entur, Kartverket (addresses, place names, elevation, municipality at a
  point, water level and tides), Norges Bank, data.norge.no, Stortinget, Statens vegvesen traffic
  counts and Udir's school register.
- Provenance on every result; errors with a code, a plain message and often a ready next call.
- Token buckets below each published limit, a SQLite cache with revalidation and stale fallback,
  coalescing of identical requests.
- A public deployment mode with per-client limits, a generated website, a Dockerfile and a Fly.io
  configuration.
