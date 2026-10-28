# Roadmap

What comes next, roughly in order. Items marked **(needs owner)** need an account, a decision
or a credential and cannot be done from the code alone.

## Launch

- [ ] Create the public GitHub repository and push `main` **(needs owner)**. The first CI run
      also builds the Docker image for the first time.
- [ ] Deploy to Fly.io: volume, secrets (`KILDEVERK_CONTACT`, Frost and HydAPI keys), `fly deploy`
      **(needs owner)**.
- [ ] Put the hosted URL in the README and on the website; add the hosted MCP URL to the
      "Connect" panel.
- [ ] Check the website by eye at desktop and phone width, light and dark.

## Tools that combine sources

- [x] `place_overview`: a coordinate's municipality, elevation, weather, warnings, stops and
      named places.
- [x] `municipality_profile`: population and change (SSB), companies and largest employers
      (Brreg), schools (NSR), traffic counting points and current warnings, for any code or name.
- [x] Population history across reforms in `municipality_profile`, from SSB's series summed to
      today's borders (`agg_KommSummer`), so every municipality gets a ten-year change.
- [x] `compare_municipalities`: the same figures side by side for two to five municipalities.

## Making it better for agents

- [x] Expose the catalogue as MCP resources (a guide, all sources, one per source) and add MCP
      prompts: profile a place, profile a municipality, find a statistic, compare places.
- [ ] An evaluation set: 30-40 realistic questions with checkable answers, run against a model
      with only Kildeverk's tools, to measure which tools are found, misused or missing.
- [x] Count tool calls, errors and cache hits per tool, and show them in `service_status`.

- [x] Accept municipality and county names wherever a code is accepted (`companies_search`,
      `schools_search`, `hazards_flood_landslide`, …), resolved through Klass, so an agent can
      skip a lookup call. Results say what a name was resolved to.
- [ ] A `compact` option on the tools with large results, returning only the fields most answers
      need, to save agents' context.
- [x] Make every literal `next_call` runnable as given: a test finds each one in the code and
      validates it against its tool's input model.

## More from the same publishers

- [ ] Entur journey planning from A to B.
- [ ] Kartverket return levels for storm surge (the 20-, 200- and 1000-year water levels).
- [ ] Stortinget questions to ministers.
- [ ] MET ocean forecast (waves and sea temperature).
- [ ] Statens vegvesen's national road database (NVDB): speed limits, tunnels, bridges.

## Release

- [ ] Version 0.2.0 with a changelog.
- [ ] Publish to PyPI so `uvx kildeverk` works without a Git URL **(needs owner)**.
