"""Atom feeds: warnings for a municipality in a form any feed reader can follow.

A feed is built from the same tools as everything else (weather warnings for the county,
flood and landslide warnings for the municipality), so it shares their budgets and cache.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response

from kildeverk import __version__
from kildeverk.core.errors import ErrorCode, ToolError
from kildeverk.settings import REPO_URL

ATOM = "http://www.w3.org/2005/Atom"

# Everything the feed says itself, in English and Norwegian (bokmål). The warnings' own texts
# come from MET and NVE in the same language.
TEXT = {
    "en": {
        "title": "Warnings for {name} ({code})",
        "subtitle": (
            "Weather warnings from MET Norway (for the county); flood and landslide warnings and "
            "avalanche forecasts at moderate or above from NVE (for the municipality and its "
            "forecasting regions), via Kildeverk. Check varsom.no and yr.no before acting."
        ),
        "weather": "{level} warning: {event} ({area})",
        "hazard": "{level} {kind} warning: {title}",
        "kinds": {"flood": "flood", "landslide": "landslide"},
        "avalanche": "Avalanche danger {level} ({level_name}): {region}",
        "none_title": "No warnings for {name} today",
        "none_summary": (
            "No weather, flood or landslide warning at yellow or above, and no avalanche danger "
            "at moderate or above, is in force."
        ),
        "levels": {"yellow": "Yellow", "orange": "Orange", "red": "Red", "green": "Green"},
        "avalanche_levels": {},
        "unavailable": "{part} unavailable: {message}",
        "parts": ("Weather warnings", "Flood and landslide warnings"),
    },
    "nb": {
        "title": "Farevarsler for {name} ({code})",
        "subtitle": (
            "Farevarsler for vær fra Meteorologisk institutt (for fylket), og flom- og "
            "jordskredvarsler og snøskredvarsler på moderat faregrad eller høyere fra NVE (for "
            "kommunen og varslingsregionene), via Kildeverk. Sjekk varsom.no og yr.no før du "
            "handler."
        ),
        "weather": "{level} farevarsel: {event} ({area})",
        "hazard": "{level} farevarsel for {kind}: {title}",
        "kinds": {"flood": "flom", "landslide": "jordskred"},
        "avalanche": "Snøskredfare {level} ({level_name}): {region}",
        "none_title": "Ingen farevarsler for {name} i dag",
        "none_summary": (
            "Ingen farevarsler for vær, flom eller jordskred på gult nivå eller høyere, og ingen "
            "snøskredfare på moderat eller høyere, gjelder nå."
        ),
        "levels": {"yellow": "Gult", "orange": "Oransje", "red": "Rødt", "green": "Grønt"},
        "avalanche_levels": {
            1: "liten",
            2: "moderat",
            3: "betydelig",
            4: "stor",
            5: "meget stor",
        },
        "unavailable": "{part} er ikke tilgjengelige: {message}",
        "parts": ("Farevarsler for vær", "Flom- og jordskredvarsler"),
    },
}


def _entry(
    feed: ET.Element, *, id_: str, title: str, updated: str, summary: str, link: str | None
) -> None:
    entry = ET.SubElement(feed, "entry")
    ET.SubElement(entry, "id").text = id_
    ET.SubElement(entry, "title").text = title
    ET.SubElement(entry, "updated").text = updated
    ET.SubElement(entry, "summary").text = summary
    if link:
        ET.SubElement(entry, "link", href=link)


def feed_url(base_url: str, code: str, lang: str) -> str:
    """The feed's own address; the language is part of it, so a subscription keeps it."""

    return f"{base_url}/v1/feeds/warnings/{code}.atom" + ("?lang=nb" if lang == "nb" else "")


def build_feed(
    base_url: str,
    code: str,
    name: str,
    weather: dict[str, Any] | None,
    hazards: dict[str, Any] | None,
    notes: list[str],
    now: dt.datetime,
    avalanche: list[dict[str, Any]] | None = None,
    lang: str = "en",
) -> bytes:
    text = TEXT[lang]
    feed = ET.Element("feed", xmlns=ATOM)
    if lang == "nb":
        feed.set("xml:lang", "nb")
    self_url = feed_url(base_url, code, lang)
    ET.SubElement(feed, "id").text = self_url
    ET.SubElement(feed, "title").text = text["title"].format(name=name, code=code)
    ET.SubElement(feed, "subtitle").text = text["subtitle"]
    ET.SubElement(feed, "link", rel="self", href=self_url)
    ET.SubElement(feed, "generator", uri=REPO_URL, version=__version__).text = "Kildeverk"
    updated = ET.SubElement(feed, "updated")
    stamps: list[str] = []

    for w in (weather or {}).get("data", {}).get("warnings", []):
        stamp = w.get("valid_from") or now.isoformat()
        stamps.append(stamp)
        _entry(
            feed,
            id_=f"urn:metalerts:{w['id']}",
            title=text["weather"].format(
                level=text["levels"].get(w["level_name"], w["level_name"].capitalize()),
                event=w["event"],
                area=w.get("area") or name,
            ),
            updated=stamp,
            summary=" ".join(
                part
                for part in (w.get("description"), w.get("consequences"), w.get("instruction"))
                if part
            )
            or (w.get("title") or ""),
            link=w.get("web"),
        )
    for w in (hazards or {}).get("data", {}).get("warnings", []):
        stamp = w.get("published") or w.get("valid_from") or now.isoformat()
        stamps.append(stamp)
        _entry(
            feed,
            id_=f"urn:varsom:{w['kind']}:{w['id']}",
            title=text["hazard"].format(
                level=text["levels"].get(w["level_name"], w["level_name"].capitalize()),
                kind=text["kinds"].get(w["kind"], w["kind"]),
                title=w.get("title") or name,
            ),
            updated=stamp,
            summary=" ".join(part for part in (w.get("warning"), w.get("advice")) if part) or "",
            link="https://www.varsom.no/",
        )
    for f in avalanche or []:
        stamp = f.get("published") or f"{f['date']}T00:00:00+00:00"
        stamps.append(stamp)
        _entry(
            feed,
            id_=f"urn:varsom:avalanche:{f['region_id']}:{f['date']}",
            title=text["avalanche"].format(
                level=f["level"],
                level_name=text["avalanche_levels"].get(f["level"], f["level_name"]),
                region=f["region"],
            ),
            updated=stamp,
            summary=f.get("summary") or "",
            link="https://www.varsom.no/",
        )
    if not stamps:
        _entry(
            feed,
            id_=f"{self_url}#none-{now:%Y%m%d}",
            title=text["none_title"].format(name=name),
            updated=now.isoformat(timespec="seconds"),
            summary=" ".join([text["none_summary"], *notes]),
            link=None,
        )
    updated.text = max(stamps) if stamps else now.isoformat(timespec="seconds")
    ET.indent(feed)
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(feed, encoding="utf-8")


AVALANCHE_FROM_LEVEL = 2  # moderate: the level from which Varsom asks people to take care


async def _avalanche(ctx: Any, municipality: str, lang: str = "en") -> list[dict[str, Any]]:
    """Today's avalanche forecasts at moderate or above for the regions covering a municipality.

    Most municipalities are in no forecasting region; outside the season every level is 0.
    """

    from kildeverk.sources import composite
    from kildeverk.sources.nve_varsom.ops import avalanche_regions_for

    try:
        regions = await avalanche_regions_for(ctx, municipality)
    except ToolError:
        return []
    if not regions:
        return []
    summary = await composite._part(ctx, "hazards_avalanche", {"language": lang})
    if isinstance(summary, ToolError):
        return []
    today = min((f["date"] for f in summary["data"]["forecasts"]), default=None)
    return [
        f
        for f in summary["data"]["forecasts"]
        if f["region_id"] in regions and f["date"] == today and f["level"] >= AVALANCHE_FROM_LEVEL
    ]


def install(app: FastAPI) -> None:
    @app.get("/v1/feeds/warnings/{municipality}.atom", include_in_schema=False)
    async def warnings_feed(request: Request, municipality: str, lang: str = "en") -> Response:
        if lang not in TEXT:
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "lang is 'en' or 'nb'.")
        from kildeverk.sources import composite

        ctx = request.app.state.ctx
        code, level, _ = await composite._region_for_series(ctx, municipality)
        if level != "municipality":
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"'{municipality}' is not a municipality; feeds are per municipality.",
            )
        weather, hazards, region, avalanche = await asyncio.gather(
            composite._part(ctx, "weather_warnings", {"county": code[:2], "language": lang}),
            composite._part(
                ctx, "hazards_flood_landslide", {"municipality": code, "language": lang}
            ),
            composite._part(
                ctx, "regions_resolve", {"query": code, "level": "municipality", "limit": 1}
            ),
            _avalanche(ctx, code, lang),
        )
        text = TEXT[lang]
        notes = [
            text["unavailable"].format(part=label, message=part.body.message)
            for label, part in zip(text["parts"], (weather, hazards), strict=True)
            if isinstance(part, ToolError)
        ]
        name = (
            region["data"]["matches"][0]["name"]
            if isinstance(region, dict) and region["data"]["matches"]
            else code
        )
        body = build_feed(
            str(request.base_url).rstrip("/"),
            code,
            name,
            weather if isinstance(weather, dict) else None,
            hazards if isinstance(hazards, dict) else None,
            notes,
            dt.datetime.now(dt.UTC),
            avalanche=avalanche,
            lang=lang,
        )
        return Response(
            body,
            media_type="application/atom+xml",
            headers={"Cache-Control": "public, max-age=600"},
        )
