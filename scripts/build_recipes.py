"""Run the website's worked questions live and save them for the site to show.

    uv run python scripts/build_recipes.py

Writes src/kildeverk/recipes.json: each question, the calls that answer it, a short answer
written from the results (in English for the MCP prompts, in Norwegian for the website), and the
sources they cite. The site renders that file, so building
the site needs no network. Re-run it to refresh the figures.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kildeverk.context import build_context
from kildeverk.settings import Settings
from kildeverk.sources.registry import operations

OUT = Path(__file__).resolve().parent.parent / "src" / "kildeverk" / "recipes.json"


def _fmt(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def place(r: dict) -> str:
    d = r["data"]
    w = d["weather"] or {}
    stop = d["nearest_stops"][0] if d["nearest_stops"] else None
    parts = [
        (
            f"The point is in {d['municipality']['name']} ({d['municipality']['county']}), "
            f"{d['elevation_m']:.0f} m above sea level."
        )
    ]
    if w:
        parts.append(
            f"It is {w['temperature_c']:.0f} °C with wind of {w['wind_speed_ms']:.0f} m/s, "
            + (
                f"and {w['next_6h_precipitation_mm']} mm of rain is expected in the next six hours."
                if w["next_6h_precipitation_mm"]
                else "and no rain is expected in the next six hours."
            )
        )
    parts.append(
        f"{len(d['warnings'])} warnings are in force."
        if d["warnings"]
        else "No warnings are in force."
    )
    if stop:
        parts.append(
            f"The nearest stop is {stop['name']}, {stop['distance_km'] * 1000:.0f} m away."
        )
    return " ".join(parts)


def rank(r: dict) -> str:
    d = r["data"]
    top = ", ".join(f"{x['name']} (+{x['change_pct']:.0f}%)" for x in d["rows"][:3])
    country = d["country"]["change_pct"] if d["country"] else None
    tail = f" Norway as a whole grew {country:.1f}%." if country is not None else ""
    return (
        f"Among municipalities with at least 10 000 people, the fastest growing from "
        f"{d['compare_to']} to {d['period']} were {top}.{tail}"
    )


def series(r: dict) -> str:
    d = r["data"]
    first, last = d["points"][0], d["points"][-1]
    change = (last["value"] - first["value"]) / first["value"] * 100
    return (
        f"{d['region_name']} had {_fmt(first['value'])} inhabitants in {first['period']} and "
        f"{_fmt(last['value'])} in {last['period']}, up {change:.1f}%, counted within today's "
        "borders across the 2020 and 2024 reforms."
    )


def vote(r: dict) -> str:
    d = r["data"]
    v = next(v for v in d["votes"] if v["recorded_by_name"])
    against = [p["party"] for p in v["parties"] if p["against_votes"] > p["for_votes"]]
    return (
        f"{d['short_title']}: the vote ended {v['for_count']}–{v['against_count']}, "
        f"{'adopted' if v['adopted'] else 'rejected'}. Parties mostly voting against: "
        f"{', '.join(against) or 'none'}."
    )


def compare(r: dict) -> str:
    rows = r["data"]["rows"]
    return " ".join(
        f"{x['name']}: {_fmt(x['population'])} people ({x['population_change_since_pct']:+.1f}% since "
        f"{x['population_change_since']}), {x['companies_per_1000']:.0f} companies per 1 000."
        for x in rows
    )


def _pct(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",").replace("-", "−")


def place_nb(r: dict) -> str:
    d = r["data"]
    w = d["weather"] or {}
    stop = d["nearest_stops"][0] if d["nearest_stops"] else None
    parts = [
        (
            f"Punktet ligger i {d['municipality']['name']} ({d['municipality']['county']}), "
            f"{d['elevation_m']:.0f} meter over havet."
        )
    ]
    if w:
        rain = w["next_6h_precipitation_mm"]
        parts.append(
            f"Det er {w['temperature_c']:.0f} °C og {w['wind_speed_ms']:.0f} m/s vind, "
            + (
                f"og det ventes {_pct(rain)} mm nedbør de neste seks timene."
                if rain
                else "og det ventes ikke nedbør de neste seks timene."
            )
        )
    parts.append(
        f"{len(d['warnings'])} farevarsler gjelder."
        if d["warnings"]
        else "Ingen farevarsler gjelder."
    )
    if stop:
        parts.append(
            f"Nærmeste holdeplass er {stop['name']}, {stop['distance_km'] * 1000:.0f} meter unna."
        )
    return " ".join(parts)


def rank_nb(r: dict) -> str:
    d = r["data"]
    country = d["country"]["change_pct"] if d["country"] else None
    tail = f" Landet som helhet vokste {_pct(country)} %." if country is not None else ""
    names = [f"{x['name']} (+{_pct(x['change_pct'], 0)} %)" for x in d["rows"][:3]]
    listed = ", ".join(names[:-1]) + f" og {names[-1]}" if len(names) > 1 else "".join(names)
    return (
        f"Blant kommuner med minst 10 000 innbyggere vokste disse mest fra {d['compare_to']} "
        f"til {d['period']}: {listed}.{tail}"
    )


def series_nb(r: dict) -> str:
    d = r["data"]
    first, last = d["points"][0], d["points"][-1]
    change = (last["value"] - first["value"]) / first["value"] * 100
    return (
        f"{d['region_name']} hadde {_fmt(first['value'])} innbyggere i {first['period']} og "
        f"{_fmt(last['value'])} i {last['period']}, en økning på {_pct(change)} %, regnet innenfor "
        "dagens grenser gjennom reformene i 2020 og 2024."
    )


def vote_nb(r: dict) -> str:
    d = r["data"]
    v = next(v for v in d["votes"] if v["recorded_by_name"])
    against = [p["party"] for p in v["parties"] if p["against_votes"] > p["for_votes"]]
    return (
        f"{d['short_title']}: voteringen endte {v['for_count']}–{v['against_count']}, og forslaget "
        f"ble {'vedtatt' if v['adopted'] else 'forkastet'}. Partier som for det meste stemte imot: "
        f"{', '.join(against) or 'ingen'}."
    )


def compare_nb(r: dict) -> str:
    rows = r["data"]["rows"]
    return " ".join(
        f"{x['name']}: {_fmt(x['population'])} innbyggere "
        f"({'+' if x['population_change_since_pct'] >= 0 else ''}"
        f"{_pct(x['population_change_since_pct'])} % siden {x['population_change_since']}), "
        f"{x['companies_per_1000']:.0f} foretak per 1 000."
        for x in rows
    )


RECIPES: list[dict[str, Any]] = [
    {
        "question": "What is it like at this spot in central Bergen right now?",
        "question_nb": "Hvordan er det på dette stedet i Bergen sentrum akkurat nå?",
        "tool": "place_overview",
        "arguments": {"lat": 60.3913, "lon": 5.3221},
        "answer": place,
        "answer_nb": place_nb,
    },
    {
        "question": "Which municipalities have grown fastest since 2015?",
        "question_nb": "Hvilke kommuner har vokst mest siden 2015?",
        "tool": "statistics_rank",
        "arguments": {"table_id": "07459", "compare_to": "2015", "min_value": 10000, "limit": 5},
        "answer": rank,
        "answer_nb": rank_nb,
    },
    {
        "question": "How has Tromsø's population changed since 2010, across the reforms?",
        "question_nb": "Hvordan har folketallet i Tromsø endret seg siden 2010, gjennom reformene?",
        "tool": "statistics_series",
        "arguments": {"table_id": "07459", "region": "Tromsø", "from_year": 2010},
        "answer": series,
        "answer_nb": series_nb,
    },
    {
        "question": "How did the parties vote on the proposal to curb energy prices?",
        "question_nb": "Hvordan stemte partiene over forslaget om å dempe energiprisene?",
        "tool": "parliament_case",
        "arguments": {"case_id": 200084},
        "answer": vote,
        "answer_nb": vote_nb,
    },
    {
        "question": "How do Bergen, Trondheim and Stavanger compare?",
        "question_nb": "Hvordan står Bergen, Trondheim og Stavanger seg mot hverandre?",
        "tool": "compare_municipalities",
        "arguments": {"municipalities": ["Bergen", "Trondheim", "Stavanger"]},
        "answer": compare,
        "answer_nb": compare_nb,
    },
]


async def main() -> None:
    ops = {op.name: op for op in operations()}
    ctx = build_context(Settings(max_wait_s=60))
    out = []
    for recipe in RECIPES:
        result = await ops[recipe["tool"]].invoke(ctx, recipe["arguments"])
        sources = sorted({(p["publisher"], p["licence"]["name"]) for p in result["provenance"]})
        out.append(
            {
                "question": recipe["question"],
                "question_nb": recipe["question_nb"],
                "tool": recipe["tool"],
                "arguments": recipe["arguments"],
                "answer": recipe["answer"](result),
                "answer_nb": recipe["answer_nb"](result),
                "sources": [{"publisher": p, "licence": licence} for p, licence in sources],
                "upstream_calls": len(result["provenance"]),
            }
        )
        print(f"{recipe['tool']}: {out[-1]['answer'][:100]}")
    await ctx.aclose()
    OUT.write_text(
        json.dumps(
            {"built_at": datetime.now(UTC).isoformat(timespec="minutes"), "recipes": out},
            ensure_ascii=False,
            indent=1,
        )
        + "\n"
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
