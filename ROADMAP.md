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
- [ ] `municipality_profile`: one municipality's population and change (SSB), largest employers
      (Brreg), schools and pupils (NSR), traffic counting points, and current warnings, with
      codes harmonised to the current municipality map.
- [ ] `compare_municipalities`: the same figures side by side for two to five municipalities.

## Making it better for agents

- [ ] Expose the catalogue as MCP resources (one per source) and add a few MCP prompts, such as
      "profile a place" and "find a statistic and fetch it".
- [ ] An evaluation set: 30-40 realistic questions with checkable answers, run against a model
      with only Kildeverk's tools, to measure which tools are found, misused or missing.
- [ ] Count tool calls, errors and cache hits per tool, and show them in `service_status`.

## More from the same publishers

- [ ] Entur journey planning from A to B.
- [ ] Kartverket return levels for storm surge (the 20-, 200- and 1000-year water levels).
- [ ] Stortinget questions to ministers.
- [ ] MET ocean forecast (waves and sea temperature).
- [ ] Statens vegvesen's national road database (NVDB): speed limits, tunnels, bridges.

## Release

- [ ] Version 0.2.0 with a changelog.
- [ ] Publish to PyPI so `uvx kildeverk` works without a Git URL **(needs owner)**.
