"""Serve every registered operation as an MCP tool."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import mcp_types as types
from mcp.server.lowlevel import Server

from kildeverk import __version__
from kildeverk.context import Context
from kildeverk.core.errors import ErrorCode, NextCall, ToolError
from kildeverk.sources.registry import operations

INSTRUCTIONS = """\
Live Norwegian public data. Every successful result has `data`, `provenance` (source, licence, \
exact upstream URL, retrieval time and a citation line to quote) and `notes` worth reading.
Every error has a `code`, a plain `message`, `retryable`, and often a `next_call` you can make as is.
For a place, start with place_overview (a coordinate) or municipality_profile (a code or name); their follow_up lists the next calls.
For statistics: statistics_search_tables -> statistics_describe_table -> statistics_get_data.
Call sources_list, or read the kildeverk://sources resources, to see what each source covers and its licence. The prompts give tested ways to answer common questions."""

GUIDE = """# Choosing a Kildeverk tool

- **A place given as a coordinate:** `place_overview`, then its `follow_up` calls.
- **A municipality:** `municipality_profile` (any code, old or current, or a name).
  Several: `compare_municipalities`.
- **A statistic:** `statistics_search_tables` (try Norwegian words too), then
  `statistics_describe_table` for codes, then `statistics_get_data`. For one region over time,
  `statistics_series` does it in one call and keeps the series unbroken across the reforms. To
  find the highest, lowest or fastest-growing regions, `statistics_rank`.
- **A company:** `companies_search`, then `companies_get`.
- **Weather:** `weather_forecast` ahead; `weather_find_stations` and `weather_observations` for
  what was measured; `weather_warnings` for official warnings.
- **Water and hazards:** `water_find_stations` and `water_observations`; `hazards_flood_landslide`,
  `hazards_avalanche`; `sea_level` on the coast; `energy_reservoirs` for hydropower.
- **Getting around:** `transit_find_stops`, then `transit_departures`; `traffic_find_points`, then
  `traffic_volumes` for road traffic.
- **Maps:** `addresses_search`, `places_search`, `terrain_elevation`, `regions_at_point`.
- **Money:** `currency_exchange_rates`, `rates_policy_rate`.
- **Parliament:** `parliament_cases`, then `parliament_case` for votes; `parliament_members`.
- **Schools:** `schools_search`, then `schools_get`.
- **Anything else:** `catalog_search` finds which public body publishes it.

Quote each result's `provenance[].citation` when you use its data, and read its `notes`.
"""

PROMPTS: dict[str, tuple[str, list[tuple[str, str, bool]], str]] = {
    "profile_place": (
        "Describe a place in Norway from live public data.",
        [("lat", "Latitude", True), ("lon", "Longitude", True)],
        (
            "Describe the place at latitude {lat}, longitude {lon} in Norway. Call place_overview "
            "first, then make the follow_up calls that help, such as departures from the nearest "
            "stop or a longer forecast. Mention any warnings first. Cite each source you use with "
            "the citation line from its provenance."
        ),
    ),
    "profile_municipality": (
        "Profile a Norwegian municipality: people, businesses, schools and warnings.",
        [("municipality", "A municipality code (old or current) or name", True)],
        (
            "Give a short profile of the Norwegian municipality '{municipality}'. Call "
            "municipality_profile, then statistics_search_tables for one or two figures that make "
            "it distinctive. Say which reforms its code went through if resolved_from is set. Cite "
            "each source with its provenance citation."
        ),
    ),
    "find_statistic": (
        "Find and fetch an official Norwegian statistic.",
        [
            ("topic", "What to measure, e.g. 'unemployment' or 'house prices'", True),
            ("region", "Optional: a municipality or county", False),
        ],
        (
            "Find the official Norwegian statistic for '{topic}'{region_part}. Search with "
            "statistics_search_tables in English and, if needed, Norwegian; read the table with "
            "statistics_describe_table; fetch only the cells you need with statistics_get_data. "
            "State the table id, the unit and the latest period, and cite the provenance."
        ),
    ),
    "compare_places": (
        "Compare two to five Norwegian municipalities.",
        [("municipalities", "Comma-separated codes or names", True)],
        (
            "Compare these Norwegian municipalities: {municipalities}. Call compare_municipalities "
            "with them as a list, then explain the main differences in population growth, business "
            "density and schools. Point out anything the notes say is incomplete. Cite the sources."
        ),
    ),
}

_ANNOTATIONS = types.ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


def _result(payload: dict[str, Any], *, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=is_error,
    )


def _recipe_prompts() -> dict[str, tuple[str, str]]:
    """name -> (description, text) for each stored website recipe."""

    from kildeverk.site import RECIPES

    if not RECIPES.exists():
        return {}
    stored = json.loads(RECIPES.read_text(encoding="utf-8"))
    prompts = {}
    for recipe in stored["recipes"]:
        arguments = json.dumps(recipe["arguments"], ensure_ascii=False)
        prompts[f"recipe_{recipe['tool']}"] = (
            f"Worked example: {recipe['question']}",
            (
                f"{recipe['question']} Answer with Kildeverk: call {recipe['tool']} with {arguments}, "
                "make any follow-up calls its result suggests, and cite each source with the "
                "citation line from its provenance."
            ),
        )
    return prompts


def build_mcp_server(get_context: Callable[[], Context]) -> Server:
    ops = {op.name: op for op in operations()}
    tools = [
        types.Tool(
            name=op.name,
            title=op.title,
            description=op.description,
            input_schema=op.input_schema(),
            output_schema=op.output_schema(),
            annotations=_ANNOTATIONS,
        )
        for op in ops.values()
    ]

    async def on_list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        op = ops.get(params.name)
        if op is None:
            error = ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"There is no tool named '{params.name}'.",
                next_call=NextCall(tool="sources_list", arguments={}),
            )
            return _result(error.envelope(), is_error=True)
        try:
            payload = await op.invoke(get_context(), params.arguments or {})
        except ToolError as exc:
            return _result(exc.envelope(), is_error=True)
        return _result(payload)

    from kildeverk.sources.meta import source_infos

    sources = {info.id: info for info in source_infos()}
    resources = [
        types.Resource(
            uri="kildeverk://guide",
            name="guide",
            title="Choosing a tool",
            description="Which tool answers which kind of question.",
            mime_type="text/markdown",
        ),
        types.Resource(
            uri="kildeverk://sources",
            name="sources",
            title="All sources",
            description="Every source with its licence, limits, coverage, gaps and tools.",
            mime_type="application/json",
        ),
        *(
            types.Resource(
                uri=f"kildeverk://sources/{info.id}",
                name=info.id,
                title=info.name,
                description=f"{info.publisher}. Licence: {info.licence.name}.",
                mime_type="application/json",
            )
            for info in sources.values()
        ),
    ]

    async def on_list_resources(_ctx: Any, _params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=resources)

    async def on_read_resource(
        _ctx: Any, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        uri = str(params.uri)
        if uri == "kildeverk://guide":
            text, mime = GUIDE, "text/markdown"
        elif uri == "kildeverk://sources":
            text = json.dumps(
                [i.model_dump(mode="json") for i in sources.values()], ensure_ascii=False
            )
            mime = "application/json"
        elif uri.startswith("kildeverk://sources/") and uri.rsplit("/", 1)[-1] in sources:
            text = sources[uri.rsplit("/", 1)[-1]].model_dump_json()
            mime = "application/json"
        else:
            raise ValueError(f"No resource {uri}. List them with resources/list.")
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=uri, mime_type=mime, text=text)]
        )

    prompts = [
        types.Prompt(
            name=name,
            description=description,
            arguments=[
                types.PromptArgument(name=a, description=d, required=required)
                for a, d, required in arguments
            ],
        )
        for name, (description, arguments, _) in PROMPTS.items()
    ]

    # The website's worked questions, as ready prompts with no arguments.
    recipes = _recipe_prompts()
    prompts += [
        types.Prompt(name=name, description=description, arguments=[])
        for name, (description, _) in recipes.items()
    ]

    async def on_list_prompts(_ctx: Any, _params: Any) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=prompts)

    async def on_get_prompt(
        _ctx: Any, params: types.GetPromptRequestParams
    ) -> types.GetPromptResult:
        if params.name in recipes:
            description, text = recipes[params.name]
            return types.GetPromptResult(
                description=description,
                messages=[
                    types.PromptMessage(
                        role="user", content=types.TextContent(type="text", text=text)
                    )
                ],
            )
        if params.name not in PROMPTS:
            raise ValueError(f"No prompt {params.name}. List them with prompts/list.")
        description, arguments, template = PROMPTS[params.name]
        given = dict(params.arguments or {})
        missing = [a for a, _, required in arguments if required and not given.get(a)]
        if missing:
            raise ValueError(f"Prompt {params.name} needs: {', '.join(missing)}.")
        region = given.get("region")
        text = template.format(
            **{a: given.get(a, "") for a, _, _ in arguments},
            region_part=f" for {region}" if region else "",
        )
        return types.GetPromptResult(
            description=description,
            messages=[
                types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))
            ],
        )

    return Server(
        "kildeverk",
        version=__version__,
        title="Kildeverk: Norwegian public data",
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
        on_list_prompts=on_list_prompts,
        on_get_prompt=on_get_prompt,
    )
