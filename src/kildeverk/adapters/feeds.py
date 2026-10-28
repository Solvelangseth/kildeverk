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


def build_feed(
    base_url: str,
    code: str,
    name: str,
    weather: dict[str, Any] | None,
    hazards: dict[str, Any] | None,
    notes: list[str],
    now: dt.datetime,
) -> bytes:
    feed = ET.Element("feed", xmlns=ATOM)
    self_url = f"{base_url}/v1/feeds/warnings/{code}.atom"
    ET.SubElement(feed, "id").text = self_url
    ET.SubElement(feed, "title").text = f"Warnings for {name} ({code})"
    ET.SubElement(feed, "subtitle").text = (
        "Weather warnings from MET Norway (for the county) and flood and landslide warnings from "
        "NVE (for the municipality), via Kildeverk. Check varsom.no and yr.no before acting."
    )
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
            title=f"{w['level_name'].capitalize()} warning: {w['event']} ({w.get('area') or name})",
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
            title=f"{w['level_name'].capitalize()} {w['kind']} warning: {w.get('title') or name}",
            updated=stamp,
            summary=" ".join(part for part in (w.get("warning"), w.get("advice")) if part) or "",
            link="https://www.varsom.no/",
        )
    if not stamps:
        _entry(
            feed,
            id_=f"{self_url}#none-{now:%Y%m%d}",
            title=f"No warnings for {name} today",
            updated=now.isoformat(timespec="seconds"),
            summary="No weather, flood or landslide warning at yellow or above is in force. "
            + " ".join(notes),
            link=None,
        )
    updated.text = max(stamps) if stamps else now.isoformat(timespec="seconds")
    ET.indent(feed)
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(feed, encoding="utf-8")


def install(app: FastAPI) -> None:
    @app.get("/v1/feeds/warnings/{municipality}.atom", include_in_schema=False)
    async def warnings_feed(request: Request, municipality: str) -> Response:
        from kildeverk.sources import composite

        ctx = request.app.state.ctx
        code, level, _ = await composite._region_for_series(ctx, municipality)
        if level != "municipality":
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"'{municipality}' is not a municipality; feeds are per municipality.",
            )
        weather, hazards, region = await asyncio.gather(
            composite._part(ctx, "weather_warnings", {"county": code[:2]}),
            composite._part(ctx, "hazards_flood_landslide", {"municipality": code}),
            composite._part(
                ctx, "regions_resolve", {"query": code, "level": "municipality", "limit": 1}
            ),
        )
        notes = [
            f"{label} unavailable: {part.body.message}"
            for label, part in (
                ("Weather warnings", weather),
                ("Flood and landslide warnings", hazards),
            )
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
        )
        return Response(
            body,
            media_type="application/atom+xml",
            headers={"Cache-Control": "public, max-age=600"},
        )
