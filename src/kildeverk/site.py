"""Build the static website from the catalogue: `kildeverk site --out site/`.

Everything on the page comes from the registry, so the site cannot list a tool or a
licence the code does not have. The page is in Norwegian (the text is in `site_nb`); the
tools themselves, and what agents read, stay in English. The only script is for the page's
own controls and the "Kjør" button, which calls the same deployment's JSON API.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from kildeverk import site_nb
from kildeverk.catalogue import build_catalogue
from kildeverk.settings import REPO_URL

HOSTED_URL = "https://kildeverk.fly.dev"

# A short code and a short name per publisher, keyed by the catalogue's publisher up to the
# first comma. The codes label the source tiles and the chips on examples and tools; the
# short names run along the strip under the hero, in this order.
PUBLISHER_CODES: dict[str, tuple[str, str]] = {
    "Statistics Norway (SSB)": ("SSB", "SSB"),
    "Norwegian Meteorological Institute (MET Norway)": ("MET", "MET"),
    "Norwegian Water Resources and Energy Directorate (NVE)": ("NVE", "NVE"),
    "Norwegian Mapping Authority (Kartverket)": ("KV", "Kartverket"),
    "Norwegian Mapping Authority": ("KV", "Kartverket"),
    "Entur AS": ("ENTUR", "Entur"),
    "Brønnøysund Register Centre (Brønnøysundregistrene)": ("BRREG", "Brønnøysundregistrene"),
    "Norges Bank": ("NB", "Norges Bank"),
    "Stortinget (the Norwegian parliament)": ("STORT", "Stortinget"),
    "Norwegian Public Roads Administration (Statens vegvesen)": ("SVV", "Statens vegvesen"),
    "Norwegian Directorate for Education and Training (Udir)": ("UDIR", "Udir"),
    "Norwegian Digitalisation Agency (Digdir)": ("DIGDIR", "Digdir"),
    "Elhub AS": ("ELHUB", "Elhub"),
    "U.S. Geological Survey (USGS)": ("USGS", "USGS"),
    "University of Bergen and the Language Council of Norway (Språkrådet)": (
        "UIB",
        "UiB og Språkrådet",
    ),
    "Avinor AS": ("AVINOR", "Avinor"),
    "The World Bank": ("WB", "Verdensbanken"),
    "Eurostat (European Commission)": ("ESTAT", "Eurostat"),
}
STRIP_LENGTH = 10


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _code(text: str, label: str, *, html: bool = False) -> str:
    """A code box with a label and a copy button. It wraps long lines and grows to fit."""

    body = text if html else _e(text)
    return f"""<div class="code"><div class="code-head"><span>{_e(label)}</span><button type="button" class="copy">Kopier</button></div><pre><code>{body}</code></pre></div>"""


def _origin() -> str:
    # Filled in by the script with the address the page is served from.
    return f'<span class="origin">{HOSTED_URL}</span>'


def _publisher(english: str) -> tuple[str, str]:
    """(code, short name) for a publisher as the catalogue and the provenance write it."""

    base = english.split(",")[0].strip()
    if base in PUBLISHER_CODES:
        return PUBLISHER_CODES[base]
    initials = "".join(w[0] for w in base.split() if w[:1].isalpha()).upper()
    return initials or base.upper(), base


def _source_text(source: dict[str, Any]) -> site_nb.SourceText:
    return site_nb.SOURCES.get(
        source["id"],
        site_nb.SourceText(
            source["name"], source["publisher"], source["covers"], source["known_gaps"]
        ),
    )


def _tool_text(tool: dict[str, Any]) -> site_nb.ToolText:
    return site_nb.TOOLS.get(tool["name"], site_nb.ToolText(tool["title"], tool["description"]))


def _licence_badge(licence: dict[str, Any]) -> str:
    label = site_nb.LICENCES.get(licence["id"], licence["id"])
    return f'<a class="badge" href="{_e(licence["url"])}" title="{_e(licence["name"])}">{_e(label)}</a>'


def _chips(codes: list[str]) -> str:
    return "".join(f'<span class="chip">{_e(c)}</span>' for c in dict.fromkeys(codes))


def _source_card(source: dict[str, Any]) -> str:
    nb = _source_text(source)
    key = (
        '<span class="badge warn" title="Den offentlige tjenesten har en nøkkel. Kjører du '
        f'Kildeverk selv, sett {_e(", ".join(source["requires_env"]))}.">krever gratis nøkkel</span>'
        if source["requires_env"]
        else ""
    )
    covers = "".join(f"<li>{_e(c)}</li>" for c in nb.covers)
    gaps = "".join(f"<li>{_e(g)}</li>" for g in nb.gaps)
    tools = " ".join(
        f'<a class="chip tool-link" href="#tool-{_e(t)}">{_e(t)}</a>' for t in source["tools"]
    )
    return f"""
        <article class="source" id="source-{_e(source["id"])}">
          <h4>{_e(nb.name)}</h4>
          <p class="badges">{_licence_badge(source["licence"])}{key}</p>
          <ul class="covers">{covers}</ul>
          <p class="chips">{tools}</p>
          <details class="more">
            <summary>Begrensninger</summary>
            <ul>{gaps}</ul>
            <p class="muted small">Tjenesten bruker høyst {_e(source["this_service_max_per_minute"])} kall i minuttet mot denne kilden.</p>
          </details>
          <p class="links small">
            <a href="{_e(source["homepage"])}">Utgiver</a>
            <a href="{_e(source["docs_url"])}">API-dokumentasjon</a>
            <a href="{_e(source["terms_url"])}">Vilkår</a>
          </p>
        </article>"""


def _sources(sources: list[dict[str, Any]]) -> str:
    """A tile per publisher; a tile opens the cards of that publisher's sources below the grid."""

    groups: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        groups.setdefault(_publisher(source["publisher"])[0], []).append(source)
    tiles = "".join(
        f"""
      <button type="button" class="pub" data-pub="{_e(code)}" aria-expanded="false" aria-controls="pub-detail">
        <span class="pub-code">{_e(code)}</span>
        <span class="pub-name">{_e(_source_text(group[0]).publisher)}</span>
        <span class="pub-count">{len(group)} {"kilde" if len(group) == 1 else "kilder"}</span>
      </button>"""
        for code, group in groups.items()
    )
    details = "".join(
        f"""
      <div class="pub-group" data-pub="{_e(code)}" hidden>
        <p class="pub-title"><b>{_e(_source_text(group[0]).publisher)}</b><button type="button" class="pub-close">Lukk ×</button></p>
        <div class="source-grid">{"".join(_source_card(s) for s in group)}
        </div>
      </div>"""
        for code, group in groups.items()
    )
    return f"""
    <div class="pubs">{tiles}
    </div>
    <div class="pub-detail" id="pub-detail">{details}
    </div>"""


def _type(schema: dict[str, Any]) -> str:
    if "enum" in schema:
        return " | ".join(map(str, schema["enum"]))
    if "anyOf" in schema:
        return " | ".join(_type(s) for s in schema["anyOf"] if s.get("type") != "null") or "any"
    if schema.get("type") == "array":
        return f"list of {_type(schema.get('items', {}))}"
    return schema.get("type") or schema.get("$ref", "object").rsplit("/", 1)[-1]


def _tool_block(tool: dict[str, Any], source_codes: dict[str, str], theme: str = "") -> str:
    nb = _tool_text(tool)
    example = tool["examples"][0] if tool["examples"] else {}
    method, path = tool["http"]["method"], tool["http"]["path"]
    params = tool["input_schema"].get("properties", {})
    rows = "".join(
        f"<tr><td><code>{_e(name)}</code></td><td>{_e(_type(schema))}</td>"
        f"<td>{_e(schema.get('description', ''))}</td></tr>"
        for name, schema in params.items()
    )
    codes = list(dict.fromkeys(source_codes.get(s, s) for s in tool["sources"]))
    source = " · ".join(codes) if codes else "Kildeverk"
    search = " ".join([tool["name"], nb.title, nb.summary, tool["title"], source, theme]).lower()
    return f"""
        <details class="tool" id="tool-{_e(tool["name"])}" data-search="{_e(search)}">
          <summary>
            <span class="tool-head"><code class="tool-name">{_e(tool["name"])}</code><span class="chip">kilde: {_e(source)}</span></span>
            <span class="tool-title">{_e(nb.title)}</span>
            <span class="tool-sum">{_e(nb.summary)}</span>
          </summary>
          <div class="tool-body">
            <p class="endpoint"><span class="method">{_e(method)}</span> {_e(path)}</p>
            <div class="try">
              <label class="label" for="args-{_e(tool["name"])}">Argumenter (JSON)</label>
              <textarea id="args-{_e(tool["name"])}" spellcheck="false" data-tool="{_e(tool["name"])}" data-method="{_e(method)}" data-path="{_e(path)}">{_e(json.dumps(example, ensure_ascii=False, indent=2))}</textarea>
              <div class="actions">
                <button type="button" class="run">▶ Kjør</button>
                <button type="button" class="ghost copy-curl">Kopier som curl</button>
                <button type="button" class="ghost copy-mcp">Kopier som MCP-kall</button>
                <button type="button" class="ghost cite" hidden>Lag kildehenvisning</button>
              </div>
              <div class="result" hidden>
                <div class="code"><div class="code-head"><span class="status"></span><button type="button" class="copy">Kopier</button></div><pre class="out"></pre></div>
                <button type="button" class="ghost expand" hidden></button>
              </div>
              <div class="bib" hidden>
                <div class="code"><div class="code-head"><span>BibTeX</span><button type="button" class="copy">Kopier</button></div><pre class="bib-out"></pre></div>
              </div>
            </div>
            <details class="more spec">
              <summary>Teknisk beskrivelse (på engelsk, slik KI-assistenten leser den)</summary>
              <p class="small">{_e(tool["description"])}</p>
              <table><tbody>{rows or '<tr><td colspan="3">Ingen argumenter.</td></tr>'}</tbody></table>
            </details>
          </div>
        </details>"""


def _themes(tools: list[dict[str, Any]]) -> list[tuple[str, str, list[str]]]:
    themed = [name for _, _, names in site_nb.THEMES for name in names]
    themes = list(site_nb.THEMES)
    rest = [t["name"] for t in tools if t["name"] not in themed]
    if rest:
        themes.append(("Andre verktøy", "", rest))
    return themes


def _tool_nav(tools: list[dict[str, Any]]) -> str:
    return "".join(
        f'<button type="button" class="cat" data-theme="tema-{i}"><span>{_e(title)}</span><span class="cat-arrow" aria-hidden="true">→</span></button>'
        for i, (title, _, _) in enumerate(_themes(tools), 1)
    )


def _tool_sections(tools: list[dict[str, Any]], source_codes: dict[str, str]) -> str:
    by_name = {t["name"]: t for t in tools}
    return "".join(
        f"""
      <section class="theme" id="tema-{i}">
        <header class="theme-head"><h3>{_e(title)}</h3><p>{_e(blurb)}</p></header>
        <div class="tool-list">{"".join(_tool_block(by_name[n], source_codes, f"{title} {blurb}") for n in names if n in by_name)}</div>
      </section>"""
        for i, (title, blurb, names) in enumerate(_themes(tools), 1)
    )


RECIPES = Path(__file__).parent / "recipes.json"


def _stored_recipes() -> dict[str, Any]:
    if not RECIPES.exists():
        return {"built_at": "", "recipes": []}
    return json.loads(RECIPES.read_text(encoding="utf-8"))


def _day(stored: dict[str, Any]) -> str:
    built = stored["built_at"][:10]
    return f"{built[8:10]}.{built[5:7]}.{built[:4]}" if built else ""


def _recipe_codes(recipe: dict[str, Any]) -> list[str]:
    return [_publisher(s["publisher"])[0] for s in recipe["sources"]]


def _pct(value: float, digits: int = 0) -> str:
    return f"{value:+.{digits}f}".replace(".", ",").replace("-", "−") + " %"


def _slip(stored: dict[str, Any], names: dict[str, str]) -> str:
    """The hero's answer slip: a stored example with its figures as bars and its source as a note."""

    recipe = next((r for r in stored["recipes"] if r.get("figure")), None)
    if recipe is None:
        return ""
    figure = recipe["figure"]
    top = max(row["change_pct"] for row in figure["rows"])
    bars = "".join(
        f"""
          <div class="bar"><p><b>{_e(row["name"])}</b><span>{_pct(row["change_pct"])}</span></p>
            <div class="track"><div style="width: {94 * row["change_pct"] / top:.1f}%"></div></div></div>"""
        for row in figure["rows"]
    )
    if figure.get("country_pct") is not None:
        bars += f"""
          <div class="bar whole"><p><span>Hele Norge</span><span>{_pct(figure["country_pct"], 1)}</span></p>
            <div class="track"><div style="width: {94 * figure["country_pct"] / top:.1f}%"></div></div></div>"""
    publisher = recipe["sources"][0]["publisher"]
    name = names.get(publisher, _publisher(publisher)[1])
    least = recipe["arguments"].get("min_value")
    who = f"Kommuner med minst {least:,} innbyggere".replace(",", " ") if least else "Kommuner"
    return f"""
    <figure class="slip">
      <div class="slip-head"><span>{_e(recipe["tool"])} · {_e(recipe["upstream_calls"])} oppslag</span><span>kjørt {_e(_day(stored))}</span></div>
      <div class="slip-q"><p class="label">Spørsmål</p><p class="q">{_e(recipe.get("question_nb", recipe["question"]))}</p></div>
      <div class="bars">{bars}
      </div>
      <figcaption id="fotnote"><span class="fn">1</span><span><b>{_e(name)}.</b> {_e(who)}, endring {_e(figure["compare_to"])}–{_e(figure["period"])}.</span></figcaption>
    </figure>"""


def _recipes(stored: dict[str, Any]) -> str:
    """Worked questions, run live by scripts/build_recipes.py and stored with the code."""

    if not stored["recipes"]:
        return ""
    rows = "".join(
        f"""
      <li><details class="recipe" id="eksempel-{i}">
        <summary class="row"><span class="n">{i:02d}</span><span class="q">{_e(r.get("question_nb", r["question"]))}</span><span class="chips">{_chips(_recipe_codes(r))}</span><span class="arrow" aria-hidden="true">→</span></summary>
        <div class="recipe-body">
          <p class="answer">{_e(r.get("answer_nb", r["answer"]))}</p>
          <pre class="snippet">{_e(r["tool"])} {_e(json.dumps(r["arguments"], ensure_ascii=False))}</pre>
          <p class="recipe-foot"><span>Ett kall, {_e(r["upstream_calls"])} oppslag hos kildene</span>
          <a href="#tool-{_e(r["tool"])}" class="use-recipe" data-tool="{_e(r["tool"])}" data-args="{_e(json.dumps(r["arguments"], ensure_ascii=False))}">Prøv dette kallet →</a></p>
        </div>
      </details></li>"""
        for i, r in enumerate(stored["recipes"], 1)
    )
    return f"""
  <section id="eksempler" class="wrap block">
    <div class="block-head">
      <div><p class="sec">§ 02</p><h2>Spør som du ville spurt en person</h2></div>
      <p class="mono-note">Ekte svar, kjørt {_e(_day(stored))}</p>
    </div>
    <ul class="recipes">{rows}
    </ul>
  </section>"""


def _connect() -> str:
    origin = _origin()
    mcp_json = (
        '{\n  "mcpServers": {\n    "kildeverk": {\n      "type": "http",\n'
        f'      "url": "{origin}/mcp"\n    }}\n  }}\n}}'
    )
    local_json = (
        '{\n  "mcpServers": {\n    "kildeverk": {\n      "command": "uvx",\n'
        f'      "args": ["--from", "git+{REPO_URL}",\n               "kildeverk", "serve"]\n'
        "    }\n  }\n}"
    )
    tabs = [
        (
            "claude-code",
            "Claude Code",
            "Kjør dette i terminalen:",
            f"claude mcp add --transport http kildeverk {origin}/mcp",
        ),
        (
            "apps",
            "Claude, ChatGPT og andre",
            "Legg til en egendefinert konnektor med denne adressen:",
            f"{origin}/mcp",
        ),
        (
            "config",
            "Cursor, VS Code m.fl.",
            "Legg til i MCP-konfigurasjonen:",
            _e(mcp_json).replace(_e(origin), origin),
        ),
        (
            "api",
            "JSON-API",
            "Hvert verktøy er også en vanlig nettadresse; alle står i API-dokumentasjonen:",
            f'curl "{origin}/v1/weather/forecast?lat=59.91&amp;lon=10.75&amp;hours=3"',
        ),
        (
            "local",
            "Kjør selv",
            "Med egen kvote og eget mellomlager, over stdio. Krever uv:",
            _e(local_json),
        ),
    ]
    buttons = "".join(
        f'<button type="button" role="tab" id="tab-{key}" aria-controls="panel-{key}" '
        f'aria-selected="{"true" if i == 0 else "false"}">{_e(label)}</button>'
        for i, (key, label, _, _) in enumerate(tabs)
    )
    panels = "".join(
        f'<div role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}" class="tabpanel"'
        f'{"" if i == 0 else " hidden"}><p>{_e(lead)}</p><pre class="snippet">{code}</pre></div>'
        for i, (key, _, lead, code) in enumerate(tabs)
    )
    return f"""
  <section id="kom-i-gang" class="wrap block">
    <div class="connect">
      <div class="connect-text">
        <p class="sec">§ 01</p>
        <h2>Kom i gang</h2>
        <p class="lead-s">To steg. Ingen nøkkel, ingen konto, ingen installasjon.</p>
        <ol class="steps">
          <li><span>1</span><div><p class="step-t">Legg til serveren</p><p>Velg klienten din og lim inn.</p></div></li>
          <li><span>2</span><div><p class="step-t">Spør i vei</p><p>Assistenten henter tallene og oppgir kilden. Du kan spørre på norsk.</p></div></li>
        </ol>
      </div>
      <div class="panel connect-panel">
        <div class="tabs" role="tablist" aria-label="Velg klient">{buttons}</div>
        <div class="panel-body">{panels}
          <div class="panel-foot">
            <p class="mono-note">MCP-endepunkt: {origin}/mcp</p>
            <button type="button" class="ghost copy-snippet">Kopier</button>
          </div>
        </div>
      </div>
    </div>
  </section>"""


def render(catalogue: dict[str, Any]) -> str:
    sources = catalogue["sources"]
    tools = catalogue["tools"]
    source_codes = {s["id"]: _publisher(s["publisher"])[0] for s in sources}
    # "Kartverket" and "Kartverket, Hydrographic Service" are one publisher.
    publishers = list(dict.fromkeys(_publisher(s["publisher"]) for s in sources))
    order = list(dict.fromkeys(code for code, _ in PUBLISHER_CODES.values()))
    strip = sorted(publishers, key=lambda p: order.index(p[0]) if p[0] in order else len(order))
    more = len(strip) - STRIP_LENGTH
    keyed = [_source_text(s).name for s in sources if s["requires_env"]]
    stored = _stored_recipes()
    parts = {
        "VERSION": _e(catalogue["version"]),
        "N_SOURCES": str(len(sources)),
        "N_TOOLS": str(len(tools)),
        "N_PUBLISHERS": str(len(publishers)),
        "SLIP": _slip(stored, {s["publisher"]: _source_text(s).publisher for s in sources}),
        "STRIP": "".join(f"<span>{_e(name)}</span>" for _, name in strip[:STRIP_LENGTH])
        + (f'<span class="more">+ {more} til</span>' if more > 0 else ""),
        "KEYED": (
            f"Bare {_e(' og '.join(keyed))} krever en gratis API-nøkkel; "
            "den offentlige tjenesten har dem."
            if keyed
            else "Ingen av kildene krever nøkkel."
        ),
        "CONNECT": _connect(),
        "RECIPES": _recipes(stored),
        "SOURCES": _sources(sources),
        "TOOL_NAV": _tool_nav(tools),
        "TOOLS": _tool_sections(tools, source_codes),
        "REPO": REPO_URL,
        "HOSTED": HOSTED_URL,
    }
    page = PAGE
    for key, value in parts.items():
        page = page.replace(f"@@{key}@@", value)
    return page


def build_site(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    catalogue = build_catalogue()
    (out / "index.html").write_text(render(catalogue), encoding="utf-8")
    (out / "catalogue.json").write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out / "index.html"


PAGE = """<!doctype html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kildeverk</title>
<meta name="description" content="Ferske norske offentlige data for KI-assistenter og folk: en MCP-server og et JSON-API over @@N_SOURCES@@ offisielle kilder, med kilde på hvert svar.">
<meta name="color-scheme" content="light">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect x='1.5' y='1.5' width='29' height='29' fill='%23F5F5F1' stroke='%2310161F' stroke-width='3'/><text x='16' y='21.5' font-family='monospace' font-weight='700' font-size='14' text-anchor='middle' fill='%2310161F'>[1]</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:ital,wght@0,400;0,500;0,600;0,700;0,800;1,500;1,700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
/* A printed reference work: off-white paper, black ink, one red for marks and footnotes,
   and a monospace for everything a machine reads. */
:root {
  --bg: #F5F5F1; --white: #FFFFFF; --ink: #10161F; --ink-2: #3E4652; --muted: #5A6370; --faint: #8A929C;
  --line: #D9DBD4; --line-2: #C9CCC5; --track: #EDEDE8; --hover: #ECECE6; --note: #FAFAF7;
  --red: #C8341C; --navy: #1D3B5C; --navy-line: #4F6A88; --navy-ink: #C9D4E0; --code-ink: #E9ECEF;
  --ok: #1E6B3A; --err: #A12C2C; --warn: #7D5200; --warn-bg: #F6E7C1;
  --sans: "Schibsted Grotesk", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html { scroll-behavior: smooth; scroll-padding-top: 24px; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.55 var(--sans); -webkit-font-smoothing: antialiased; }
a { color: var(--ink); text-underline-offset: 3px; }
a:hover { color: var(--red); }
a:focus-visible, button:focus-visible, summary:focus-visible { outline: 2px solid var(--red); outline-offset: 3px; }
code, pre, textarea { font-family: var(--mono); }
h1, h2, h3, h4 { margin: 0; }
.wrap { max-width: 1240px; margin: 0 auto; padding-left: 32px; padding-right: 32px; }
.muted { color: var(--muted); }
.small { font-size: .88rem; }
.label { margin: 0; font: 500 12px/1.4 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.mono-note { margin: 0; font: 13px/1.5 var(--mono); color: var(--muted); overflow-wrap: anywhere; }
.sec { margin: 0 0 14px; font: 13px var(--mono); color: var(--red); }
h2 { font-size: 48px; line-height: 1; letter-spacing: -0.03em; font-weight: 800; }
.lead-s { margin: 18px 0 32px; font-size: 18px; line-height: 1.55; color: var(--ink-2); max-width: 34ch; }
button { font: 600 15px var(--sans); cursor: pointer; border-radius: 0; }
.btn { display: inline-flex; align-items: center; padding: 14px 24px; font-weight: 600; text-decoration: none; border: 1.5px solid var(--ink); transition: transform .12s ease; }
.btn:hover { transform: translateY(-1px); }
.btn.dark { background: var(--ink); color: var(--bg); }
.btn.dark:hover { color: var(--bg); }
.chip { display: inline-block; font: 12px/1.3 var(--mono); padding: 5px 9px; border: 1px solid var(--line-2); color: var(--ink-2); background: var(--white); text-decoration: none; white-space: nowrap; }
a.chip:hover { border-color: var(--ink); color: var(--ink); }

/* Navigation */
header.top { border-bottom: 1px solid var(--line); }
header.top .wrap { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; padding-top: 14px; padding-bottom: 14px; }
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); }
.brand .mark { display: inline-flex; width: 30px; height: 30px; border: 2px solid var(--ink); align-items: center; justify-content: center; font: 600 15px var(--mono); }
.brand b { font-size: 22px; font-weight: 800; letter-spacing: -0.02em; }
.brand:hover { color: var(--ink); }
nav.menu { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 22px; }
nav.menu a { text-decoration: none; color: var(--ink-2); font-size: 15px; font-weight: 500; padding: 10px 4px; }
nav.menu a:hover { color: var(--ink); }
nav.menu a.gh { border: 1.5px solid var(--ink); padding: 9px 16px; color: var(--ink); font-weight: 600; }

/* Hero */
.hero { display: flex; flex-wrap: wrap; gap: 56px; align-items: flex-start; padding-top: 72px; padding-bottom: 56px; }
.hero-text { flex: 1 1 520px; min-width: 0; display: flex; flex-direction: column; gap: 28px; }
.kicker { margin: 0; font: 13px var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
h1 { font-size: clamp(44px, 6.4vw, 88px); line-height: .98; letter-spacing: -0.035em; font-weight: 800; }
h1 em { font-weight: 700; color: var(--red); }
h1 sup { font: 500 .28em var(--mono); margin-left: 4px; }
h1 sup a { color: var(--red); text-decoration: none; }
.lead { margin: 0; font-size: 20px; line-height: 1.5; color: var(--ink-2); max-width: 34ch; }
.cta { display: flex; flex-wrap: wrap; gap: 12px; }
.stats { margin: 12px 0 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); border-top: 1px solid var(--ink); }
.stats div { padding: 16px 16px 0; border-right: 1px solid var(--line); }
.stats div:first-child { padding-left: 0; }
.stats div:last-child { border-right: 0; }
.stats dt { font-size: 13px; color: var(--muted); }
.stats dd { margin: 4px 0 0; font-size: 40px; font-weight: 700; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }

/* The answer slip */
.slip { flex: 1 1 420px; min-width: 0; margin: 0; background: var(--white); border: 1px solid var(--ink); box-shadow: 8px 8px 0 var(--ink); }
.slip-head { display: flex; justify-content: space-between; gap: 12px; padding: 14px 20px; border-bottom: 1px solid var(--line); font: 12px var(--mono); color: var(--muted); }
.slip-q { padding: 24px 24px 8px; }
.slip-q .label { margin-bottom: 6px; }
.slip-q .q { margin: 0; font-size: 22px; font-weight: 600; line-height: 1.3; letter-spacing: -0.01em; }
.bars { padding: 20px 24px 8px; display: flex; flex-direction: column; gap: 14px; }
.bar p { display: flex; justify-content: space-between; margin: 0 0 6px; font-size: 15px; }
.bar p span:last-child { font: 600 15px var(--mono); }
.track { height: 12px; background: var(--track); }
.track div { height: 12px; background: var(--ink); }
.bar.whole { padding-top: 6px; border-top: 1px dashed var(--line); color: var(--muted); }
.bar.whole p span:last-child { font-weight: 400; }
.bar.whole .track div { background: var(--faint); }
.slip figcaption { margin-top: 16px; padding: 14px 24px 18px; border-top: 1px solid var(--line); background: var(--note); display: flex; gap: 10px; font-size: 13px; line-height: 1.5; color: var(--ink-2); }
.slip figcaption b { color: var(--ink); }
.fn { font: 600 13px var(--mono); color: var(--red); }

/* Publisher strip */
.strip { background: var(--ink); color: var(--bg); }
.strip .wrap { display: flex; flex-wrap: wrap; gap: 8px 28px; align-items: center; padding-top: 16px; padding-bottom: 16px; font-size: 14px; }
.strip .label { color: #A9B0B9; }
.strip .more { color: #A9B0B9; }

/* Sections */
.block { padding-top: 104px; padding-bottom: 40px; }
.block-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 16px 64px; margin-bottom: 36px; }
.block-head > div { flex: 1 1 420px; min-width: 0; }
.block-head > p { flex: 1 1 360px; margin: 0; font-size: 17px; line-height: 1.55; color: var(--ink-2); }
.block-head > p.mono-note { flex: 0 1 auto; font-size: 13px; color: var(--muted); }
.panel { border: 1px solid var(--ink); background: var(--white); }
pre.snippet { margin: 0; background: var(--ink); color: var(--code-ink); padding: 22px 24px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }

/* § 01 Getting started */
.connect { display: flex; flex-wrap: wrap; gap: 40px 64px; }
.connect-text { flex: 1 1 300px; min-width: 0; }
.steps { margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--line); }
.steps li { display: flex; gap: 18px; padding: 18px 0; border-bottom: 1px solid var(--line); }
.steps li > span { font: 600 16px var(--mono); color: var(--red); }
.steps p { margin: 0; color: var(--muted); font-size: 15px; line-height: 1.5; }
.steps p.step-t { margin: 0 0 4px; color: var(--ink); font-weight: 700; font-size: 18px; }
.connect-panel { flex: 2 1 560px; min-width: 0; }
.tabs { display: flex; flex-wrap: wrap; border-bottom: 1px solid var(--ink); }
.tabs button { padding: 16px 17px; min-height: 52px; border: 0; border-right: 1px solid var(--line); background: var(--white); color: var(--ink-2); font-size: 14px; }
.tabs button[aria-selected="true"] { background: var(--ink); color: var(--bg); }
.panel-body { padding: 28px; }
.tabpanel > p { margin: 0 0 14px; font-size: 15px; color: var(--ink-2); }
.panel-foot { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; margin-top: 16px; }
button.ghost { background: var(--white); color: var(--ink); border: 1.5px solid var(--ink); padding: 11px 18px; min-height: 44px; transition: transform .12s ease; }
button.ghost:hover { transform: translateY(-1px); }
.panel-foot button.ghost { background: var(--bg); }

/* § 02 Examples */
.recipes { margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--ink); }
.recipes > li { border-bottom: 1px solid var(--line); }
.recipe > summary { list-style: none; cursor: pointer; display: flex; flex-wrap: wrap; align-items: center; gap: 12px 28px; padding: 26px 8px; transition: background .12s ease; }
.recipe > summary::-webkit-details-marker { display: none; }
.recipe > summary:hover { background: var(--hover); }
.recipe .n { font: 14px var(--mono); color: var(--faint); width: 28px; }
.recipe .q { flex: 1 1 420px; min-width: 0; font-size: 24px; font-weight: 600; letter-spacing: -0.015em; line-height: 1.3; }
.recipe .chips { display: flex; flex-wrap: wrap; gap: 6px; }
.recipe .arrow { font-size: 22px; transition: transform .2s ease; }
.recipe[open] .arrow { transform: rotate(90deg); color: var(--red); }
.recipe-body { padding: 0 8px 28px 64px; display: flex; flex-direction: column; gap: 14px; max-width: 900px; }
.recipe-body .answer { margin: 0; font-size: 17px; line-height: 1.6; color: var(--ink-2); }
.recipe-body pre.snippet { padding: 14px 18px; font-size: 13px; }
.recipe-foot { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; margin: 0; font-size: 14px; color: var(--muted); }
.recipe-foot a { font-weight: 600; color: var(--red); text-decoration: none; }

/* § 03 Warnings */
.band { margin-top: 96px; background: var(--navy); color: var(--bg); }
.band .wrap { display: flex; flex-wrap: wrap; gap: 48px; align-items: center; padding-top: 88px; padding-bottom: 88px; }
.band-text { flex: 1 1 440px; min-width: 0; }
.band .sec { color: #FF9E8A; }
.band-text p.body { margin: 18px 0 0; font-size: 18px; line-height: 1.55; color: var(--navy-ink); max-width: 40ch; }
#feed-form { flex: 1 1 400px; min-width: 0; border: 1px solid var(--navy-line); padding: 28px; display: flex; flex-direction: column; gap: 14px; }
#feed-form .label { color: var(--navy-ink); }
#feed-form input { font: 16px var(--sans); padding: 13px 14px; border: 1.5px solid var(--navy-line); background: transparent; color: var(--bg); min-height: 48px; }
#feed-form input::placeholder { color: #8FA3BA; }
#feed-form input:focus { outline: 2px solid #FF9E8A; outline-offset: 1px; }
.kinds { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 6px; }
.kind { padding: 11px 16px; min-height: 44px; background: transparent; color: var(--bg); border: 1.5px solid #6C86A3; }
.kind[aria-pressed="true"] { background: var(--bg); color: var(--navy); border-color: var(--bg); }
.kind::before { content: "+ "; }
.kind[aria-pressed="true"]::before { content: "✓ "; }
#feed-form button[type="submit"] { align-self: flex-start; background: var(--bg); color: var(--navy); border: 0; padding: 15px 24px; font-weight: 700; font-size: 16px; min-height: 48px; }
#feed-form button:disabled { opacity: .6; cursor: progress; }
#feed-result { font-size: 15px; color: var(--navy-ink); }
#feed-result p { margin: 0 0 10px; }
#feed-result a { color: var(--bg); }
#feed-result.err { color: #FFB4A6; }
#feed-result .code { border-color: var(--navy-line); }

/* § 04 Sources */
.pubs { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); border-top: 1px solid var(--ink); border-left: 1px solid var(--line); }
.pub { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; min-height: 120px; padding: 18px 20px; border: 0; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); background: transparent; color: var(--ink); text-align: left; font-weight: 400; }
.pub:hover { background: var(--white); }
.pub[aria-expanded="true"] { background: var(--ink); color: var(--bg); }
.pub[aria-expanded="true"] .pub-name, .pub[aria-expanded="true"] .pub-count { color: #C9CED6; }
.pub-code { font: 600 22px var(--mono); letter-spacing: -0.01em; margin-bottom: auto; }
.pub-name { font-size: 14px; line-height: 1.35; color: var(--ink-2); padding-top: 12px; }
.pub-count { font: 12px var(--mono); color: var(--faint); }
.pub-group { margin-top: 24px; border: 1px solid var(--ink); background: var(--white); padding: 24px 28px 28px; }
.pub-title { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 0 0 18px; font-size: 20px; }
.pub-close { background: none; border: 0; font: 500 14px var(--mono); color: var(--muted); padding: 6px 0; }
.pub-close:hover { color: var(--red); }
.source-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 28px 36px; }
.source { border-top: 1px solid var(--ink); padding-top: 14px; min-width: 0; font-size: 15px; }
.source h4 { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.badge { font: 500 12px var(--mono); padding: 3px 8px; border: 1px solid var(--line-2); text-decoration: none; color: var(--ink-2); }
.badge.warn { background: var(--warn-bg); color: var(--warn); border-color: transparent; }
.covers { padding-left: 18px; margin: 10px 0; color: var(--ink-2); }
.covers li { margin: 4px 0; }
.covers li::marker { color: var(--red); }
.source .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
details.more > summary { cursor: pointer; font-size: 14px; font-weight: 600; }
details.more ul { font-size: 14px; padding-left: 18px; color: var(--ink-2); }
.links { display: flex; flex-wrap: wrap; gap: 14px; margin: 12px 0 0; }

/* § 05 Tools */
#verktoy { padding-bottom: 112px; }
.workbench { display: flex; flex-wrap: wrap; gap: 32px 48px; align-items: flex-start; }
.cats { flex: 1 1 240px; min-width: 0; border-top: 1px solid var(--ink); position: sticky; top: 16px; }
#tool-search { width: 100%; font: 15px var(--sans); padding: 14px 4px; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: var(--ink); }
#tool-search:focus { outline: none; border-bottom-color: var(--red); }
.cat { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 12px; text-align: left; padding: 14px 4px; min-height: 50px; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: var(--ink); font-size: 16px; }
.cat:hover { color: var(--red); }
.cat .cat-arrow { visibility: hidden; }
.cat[aria-current="true"] { color: var(--red); }
.cat[aria-current="true"] .cat-arrow { visibility: visible; }
.cats p { margin: 18px 0 0; font-size: 14px; color: var(--muted); }
.bench { flex: 3 1 560px; min-width: 0; }
.theme { border: 1px solid var(--ink); background: var(--white); }
.theme + .theme { margin-top: 24px; }
.theme-head { padding: 22px 28px 18px; border-bottom: 1px solid var(--ink); }
.theme-head h3 { font-size: 24px; font-weight: 800; letter-spacing: -0.02em; }
.theme-head p { margin: 6px 0 0; color: var(--muted); font-size: 15px; }
.theme-head p:empty { display: none; }
.tool + .tool { border-top: 1px solid var(--line); }
.tool > summary { list-style: none; cursor: pointer; padding: 20px 28px; display: flex; flex-direction: column; gap: 6px; transition: background .12s ease; }
.tool > summary::-webkit-details-marker { display: none; }
.tool > summary:hover { background: var(--note); }
.tool-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 8px 12px; }
.tool-name { font: 600 19px var(--mono); overflow-wrap: anywhere; }
.tool-head .chip { white-space: normal; }
.tool[open] .tool-name { color: var(--red); }
.tool-title { font-weight: 700; font-size: 16px; }
.tool-sum { font-size: 15px; line-height: 1.55; color: var(--ink-2); max-width: 62ch; }
.tool-body { padding: 4px 28px 26px; display: flex; flex-direction: column; gap: 12px; }
.endpoint { margin: 0; font: 13px var(--mono); color: var(--muted); overflow-wrap: anywhere; }
.method { font-weight: 600; color: var(--red); margin-right: 4px; }
.try { display: flex; flex-direction: column; gap: 10px; }
.try textarea { width: 100%; min-height: 3.4em; resize: vertical; overflow: hidden; background: var(--ink); color: var(--code-ink); border: 0; padding: 18px 20px; font-size: 14px; line-height: 1.7; }
.try textarea:focus { outline: 2px solid var(--red); outline-offset: 2px; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 6px; }
button.run { background: var(--red); color: #FFFFFF; border: 0; padding: 13px 22px; font-weight: 700; min-height: 44px; transition: transform .12s ease; }
button.run:hover { transform: translateY(-1px); }
button:disabled { opacity: .6; cursor: progress; }
.code { border: 1px solid var(--line-2); background: var(--note); margin: 4px 0 0; }
.code-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 6px 6px 14px; border-bottom: 1px solid var(--line); font: 12px var(--mono); color: var(--muted); }
.code-head .copy { padding: 4px 10px; font: 500 12px var(--mono); background: var(--white); color: var(--ink); border: 1px solid var(--line-2); }
.code pre { margin: 0; padding: 14px 16px; font-size: 13px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ink); }
.band .code { background: transparent; }
.band .code-head { color: var(--navy-ink); border-color: var(--navy-line); }
.band .code pre { color: var(--bg); }
.status.ok { color: var(--ok); }
.status.err { color: var(--err); }
.result.collapsed pre { max-height: 30em; overflow: hidden; -webkit-mask-image: linear-gradient(180deg, #000 75%, transparent); mask-image: linear-gradient(180deg, #000 75%, transparent); }
.expand { align-self: flex-start; }
.spec summary { cursor: pointer; font-size: 14px; color: var(--muted); }
.spec p { margin: 10px 0 0; color: var(--ink-2); }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 10px; }
td { border-top: 1px solid var(--line); padding: 7px 10px 7px 0; vertical-align: top; overflow-wrap: anywhere; }
td:first-child { white-space: nowrap; }
#no-match { margin: 0; padding: 28px; border: 1px solid var(--ink); background: var(--white); }

/* Footer */
footer { background: var(--ink); color: #C9CED6; }
footer .wrap { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 32px; padding-top: 56px; padding-bottom: 40px; }
footer .about { display: flex; flex-direction: column; gap: 10px; max-width: 380px; }
footer .about b { font-size: 28px; font-weight: 800; letter-spacing: -0.02em; color: var(--bg); }
footer .about p { margin: 0; font-size: 15px; line-height: 1.55; }
footer nav { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 48px; font-size: 15px; align-content: start; }
footer nav a { color: var(--bg); }
footer nav a:hover { color: #FF9E8A; }
footer .fine { display: block; padding-top: 18px; padding-bottom: 28px; border-top: 1px solid #2A333F; font: 12px var(--mono); color: var(--faint); }

@media (max-width: 720px) {
  .wrap { padding-left: 16px; padding-right: 16px; }
  nav.menu { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; width: 100%; gap: 18px; -webkit-mask-image: linear-gradient(90deg, #000 85%, transparent); mask-image: linear-gradient(90deg, #000 85%, transparent); padding-right: 24px; }
  nav.menu::-webkit-scrollbar { display: none; }
  nav.menu a { white-space: nowrap; }
  .hero { padding-top: 40px; gap: 40px; }
  .hero-text, .slip, .connect-panel, .bench, .cats, .band-text, #feed-form { flex-basis: 100%; }
  .lead { font-size: 18px; }
  .stats { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .stats div { padding: 14px 10px 0; }
  .stats dd { font-size: 28px; }
  .slip { box-shadow: 6px 6px 0 var(--ink); }
  h2 { font-size: 36px; }
  .block { padding-top: 72px; }
  .band { margin-top: 72px; }
  .band .wrap { padding-top: 64px; padding-bottom: 64px; }
  .panel-body, .pub-group { padding: 20px; }
  .recipe .q { font-size: 20px; flex-basis: calc(100% - 60px); }
  .recipe-body { padding-left: 8px; }
  .pubs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pub { min-height: 104px; padding: 14px; }
  .cats { position: static; }
  .tool > summary, .theme-head { padding-left: 18px; padding-right: 18px; }
  .tool-body { padding: 4px 18px 22px; }
}
</style>
</head>
<body>
<header class="top">
  <div class="wrap">
    <a class="brand" href="#top"><span class="mark" aria-hidden="true">[1]</span><b>kildeverk</b></a>
    <nav class="menu" aria-label="Hovedmeny">
      <a href="#kom-i-gang">Kom i gang</a>
      <a href="#eksempler">Eksempler</a>
      <a href="#varsler">Varsler</a>
      <a href="#kilder">Kilder</a>
      <a href="#verktoy">Verktøy</a>
      <a href="/docs">API</a>
      <a class="gh" href="@@REPO@@">GitHub ↗</a>
    </nav>
  </div>
</header>

<main>
  <section id="top" class="wrap hero">
    <div class="hero-text">
      <p class="kicker">MCP-server · JSON-API · Gratis, ingen konto</p>
      <h1>Norske offentlige data, <em>rett fra kilden.</em><sup><a href="#fotnote" aria-label="Fotnote 1">1</a></sup></h1>
      <p class="lead">Ferske tall fra @@N_SOURCES@@ offentlige kilder, for KI-assistenter og utviklere. Hvert svar sier nøyaktig hvor det kommer fra.</p>
      <div class="cta">
        <a class="btn dark" href="#kom-i-gang">Kom i gang →</a>
        <a class="btn" href="#verktoy">Prøv verktøyene</a>
      </div>
      <dl class="stats">
        <div><dt>kilder</dt><dd>@@N_SOURCES@@</dd></div>
        <div><dt>utgivere</dt><dd>@@N_PUBLISHERS@@</dd></div>
        <div><dt>verktøy</dt><dd>@@N_TOOLS@@</dd></div>
        <div><dt>kontoer</dt><dd>0</dd></div>
      </dl>
    </div>
    @@SLIP@@
  </section>

  <div class="strip">
    <div class="wrap"><span class="label">Data fra</span>@@STRIP@@</div>
  </div>

@@CONNECT@@

@@RECIPES@@

  <section id="varsler" class="band">
    <div class="wrap">
      <div class="band-text">
        <p class="sec">§ 03</p>
        <h2>Alle farevarsler i én feed</h2>
        <p class="body">Vær, flom, jordskred og snøskred fra MET og NVE, samlet i én Atom-feed. Velg
        det du vil følge, og abonner i en hvilken som helst feedleser. Sjekk alltid varsom.no og
        yr.no før du handler.</p>
      </div>
      <form id="feed-form">
        <label class="label" for="feed-name">Kommune</label>
        <input id="feed-name" type="text" placeholder="F.eks. Tromsø eller 4601" autocomplete="off">
        <p class="label">Ta med</p>
        <div class="kinds">
          <button type="button" class="kind" data-kind="weather" aria-pressed="true">Vær</button>
          <button type="button" class="kind" data-kind="flood" aria-pressed="true">Flom</button>
          <button type="button" class="kind" data-kind="landslide" aria-pressed="true">Jordskred</button>
          <button type="button" class="kind" data-kind="avalanche" aria-pressed="true">Snøskred</button>
        </div>
        <button type="submit">Lag feed →</button>
        <div id="feed-result" hidden></div>
      </form>
    </div>
  </section>

  <section id="kilder" class="wrap block">
    <div class="block-head">
      <div><p class="sec">§ 04</p><h2>@@N_SOURCES@@ kilder, @@N_PUBLISHERS@@ utgivere</h2></div>
      <p>Hver kilde oppgir lisensen slik utgiveren skriver den, og hvert svar gjentar den. @@KEYED@@
      Flere kilder legges til fortløpende.</p>
    </div>
    @@SOURCES@@
  </section>

  <section id="verktoy" class="wrap block">
    <p class="sec">§ 05</p>
    <h2 style="margin-bottom: 36px">@@N_TOOLS@@ verktøy. Prøv dem her.</h2>
    <div class="workbench">
      <nav class="cats" aria-label="Verktøykategorier">
        <input id="tool-search" type="search" placeholder="Søk, f.eks. «skole» eller «tog»" aria-label="Søk blant verktøyene">
        @@TOOL_NAV@@
        <p>Hvert verktøy kan kjøres her i nettleseren, eller kopieres som curl- eller MCP-kall.</p>
      </nav>
      <div class="bench">
        <p id="no-match" hidden>Ingen verktøy passer søket.</p>
        @@TOOLS@@
      </div>
    </div>
  </section>
</main>

<footer>
  <div class="wrap">
    <div class="about">
      <b>kildeverk</b>
      <p>Norske offentlige data for KI-assistenter og utviklere. Gratis, uten konto, og alltid med
      kilde. Versjon @@VERSION@@, åpen kildekode (MIT), ikke tilknyttet utgiverne.</p>
    </div>
    <nav aria-label="Bunnmeny">
      <a href="/docs">API-dokumentasjon</a>
      <a href="@@REPO@@">GitHub</a>
      <a href="@@REPO@@/blob/main/CHANGELOG.md">Endringslogg</a>
      <a href="#kom-i-gang">MCP-endepunkt</a>
      <a href="/openapi.json">OpenAPI</a>
      <a href="catalogue.json">Katalog (JSON)</a>
    </nav>
  </div>
  <div class="wrap fine">Data © de respektive utgiverne. Lisens oppgis per kilde og i hvert svar.</div>
</footer>

<script>
(function () {
  var served = location.origin.indexOf("http") === 0;
  var origin = served ? location.origin : "@@HOSTED@@";
  document.querySelectorAll(".origin").forEach(function (el) { el.textContent = origin; });

  function copyText(text, button, done) {
    navigator.clipboard.writeText(text).then(function () { flash(button, done || "Kopiert ✓"); });
  }
  function flash(button, text) {
    var label = button.dataset.label || button.textContent;
    button.dataset.label = label; button.textContent = text;
    setTimeout(function () { button.textContent = label; }, 1500);
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest(".code .copy");
    if (b) copyText(b.closest(".code").querySelector("pre").textContent, b);
  });

  // Tabs in "Kom i gang"; the copy button takes the snippet of the open tab.
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  tabs.forEach(function (tab, i) {
    tab.addEventListener("click", function () { select(i); });
    tab.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        var next = (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
        select(next); tabs[next].focus();
      }
    });
  });
  function select(i) {
    tabs.forEach(function (t, j) {
      t.setAttribute("aria-selected", String(i === j));
      t.tabIndex = i === j ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = i !== j;
    });
  }
  if (tabs.length) select(0);
  var copySnippet = document.querySelector(".copy-snippet");
  if (copySnippet) copySnippet.addEventListener("click", function () {
    var open = document.querySelector('.tabpanel:not([hidden]) pre');
    if (open) copyText(open.textContent, copySnippet);
  });

  // A textarea grows to show all of its arguments.
  function fit(area) { area.style.height = "auto"; area.style.height = area.scrollHeight + 2 + "px"; }
  document.querySelectorAll(".try textarea").forEach(function (area) {
    area.addEventListener("input", function () { fit(area); });
  });
  document.querySelectorAll("details.tool").forEach(function (d) {
    d.addEventListener("toggle", function () { if (d.open) fit(d.querySelector("textarea")); });
  });

  // The workbench shows one theme at a time; a search shows every theme with a match.
  var cats = Array.prototype.slice.call(document.querySelectorAll(".cat"));
  var themes = Array.prototype.slice.call(document.querySelectorAll(".theme"));
  var search = document.getElementById("tool-search"), noMatch = document.getElementById("no-match");
  var currentTheme = themes.length ? themes[0].id : null;
  function showTheme(id, openFirst) {
    currentTheme = id;
    if (search) search.value = "";
    noMatch.hidden = true;
    themes.forEach(function (t) {
      t.hidden = t.id !== id;
      t.querySelectorAll("details.tool").forEach(function (tool) { tool.hidden = false; });
    });
    cats.forEach(function (c) { c.setAttribute("aria-current", String(c.dataset.theme === id)); });
    var theme = document.getElementById(id);
    if (openFirst && theme && !theme.querySelector("details.tool[open]")) {
      var first = theme.querySelector("details.tool");
      if (first) first.open = true;
    }
  }
  cats.forEach(function (c) {
    c.addEventListener("click", function () {
      showTheme(c.dataset.theme, true);
      if (innerWidth <= 720) document.getElementById(c.dataset.theme).scrollIntoView({ block: "start" });
    });
  });
  if (currentTheme) showTheme(currentTheme, true);
  if (search) search.addEventListener("input", function () {
    var words = search.value.toLowerCase().trim().split(/\\s+/).filter(Boolean), any = false;
    if (!words.length) { var keep = currentTheme; showTheme(keep, false); return; }
    cats.forEach(function (c) { c.setAttribute("aria-current", "false"); });
    themes.forEach(function (theme) {
      var shown = 0;
      theme.querySelectorAll("details.tool").forEach(function (tool) {
        var hit = words.every(function (w) { return tool.dataset.search.indexOf(w) !== -1; });
        tool.hidden = !hit; if (hit) shown++;
      });
      theme.hidden = shown === 0; if (shown) any = true;
    });
    noMatch.hidden = any;
  });

  // Publisher tiles open the cards of that publisher's sources.
  var pubs = Array.prototype.slice.call(document.querySelectorAll(".pub"));
  function showPub(code) {
    pubs.forEach(function (p) { p.setAttribute("aria-expanded", String(p.dataset.pub === code)); });
    document.querySelectorAll(".pub-group").forEach(function (g) { g.hidden = g.dataset.pub !== code; });
  }
  pubs.forEach(function (p) {
    p.addEventListener("click", function () {
      var open = p.getAttribute("aria-expanded") === "true";
      showPub(open ? null : p.dataset.pub);
      if (!open) document.querySelector('.pub-group[data-pub="' + p.dataset.pub + '"]').scrollIntoView({ block: "nearest" });
    });
  });
  document.querySelectorAll(".pub-close").forEach(function (b) {
    b.addEventListener("click", function () { showPub(null); });
  });

  // A link to a tool, a theme, a source or an example opens it, wherever it is hidden.
  function openFromHash() {
    var id = decodeURIComponent(location.hash.slice(1));
    var el = id && document.getElementById(id);
    if (!el) return;
    if (el.matches("details.tool")) {
      showTheme(el.closest(".theme").id, false);
      el.open = true; fit(el.querySelector("textarea"));
    } else if (el.matches(".theme")) {
      showTheme(id, true);
    } else if (el.matches(".source")) {
      showPub(el.closest(".pub-group").dataset.pub);
    } else if (el.matches("details.recipe")) {
      el.open = true;
    } else {
      return;
    }
    el.scrollIntoView({ block: "start" });
  }
  window.addEventListener("hashchange", openFromHash);
  openFromHash();

  document.querySelectorAll(".use-recipe").forEach(function (a) {
    a.addEventListener("click", function () {
      var area = document.querySelector('textarea[data-tool="' + a.dataset.tool + '"]');
      if (area) area.value = JSON.stringify(JSON.parse(a.dataset.args), null, 2);
      setTimeout(openFromHash, 0);
    });
  });

  // The URL and body a tool call becomes over HTTP: path parameters filled in, then a JSON
  // body for POST or a query string for GET (lists as repeated parameters).
  function target(method, path, args) {
    var rest = Object.assign({}, args);
    path = path.replace(/\\{(\\w+)\\}/g, function (_, name) {
      var value = rest[name]; delete rest[name]; return encodeURIComponent(value);
    });
    if (method === "POST") return { url: path, body: JSON.stringify(rest) };
    var query = new URLSearchParams();
    Object.keys(rest).forEach(function (key) {
      var value = rest[key];
      if (Array.isArray(value)) value.forEach(function (v) { query.append(key, v); });
      else if (value !== null && typeof value === "object") query.append(key, JSON.stringify(value));
      else query.append(key, value);
    });
    var qs = query.toString();
    return { url: path + (qs ? "?" + qs : ""), body: null };
  }

  function request(method, path, args) {
    var t = target(method, path, args);
    if (t.body !== null) {
      return fetch(t.url, { method: "POST", headers: { "Content-Type": "application/json" }, body: t.body });
    }
    return fetch(t.url);
  }

  // The warning kinds to follow; the feed's address carries them.
  var kinds = Array.prototype.slice.call(document.querySelectorAll(".kind"));
  kinds.forEach(function (k) {
    k.addEventListener("click", function () {
      k.setAttribute("aria-pressed", String(k.getAttribute("aria-pressed") !== "true"));
    });
  });

  // Check the name resolves (the feed answers JSON errors) before offering the link.
  var feedForm = document.getElementById("feed-form");
  if (feedForm) feedForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var name = document.getElementById("feed-name").value.trim();
    var result = document.getElementById("feed-result");
    var chosen = kinds.filter(function (k) { return k.getAttribute("aria-pressed") === "true"; })
      .map(function (k) { return k.dataset.kind; });
    result.hidden = false; result.className = "err";
    if (!name) { result.textContent = "Skriv inn en kommune først."; return; }
    if (!chosen.length) { result.textContent = "Velg minst én type varsel."; return; }
    var button = feedForm.querySelector('button[type="submit"]'); button.disabled = true;
    result.className = ""; result.textContent = "Henter varslene …";
    // The Norwegian feed, to match the page; its own self link keeps lang and kinds for the reader.
    var url = "/v1/feeds/warnings/" + encodeURIComponent(name) + ".atom?lang=nb"
      + (chosen.length < kinds.length ? "&kinds=" + chosen.join(",") : "");
    fetch(url).then(function (r) {
      result.className = "";
      if (r.ok) return r.text().then(function (xml) {
        var doc = new DOMParser().parseFromString(xml, "application/xml");
        // The feed's own self link uses the municipality number, so it survives spelling.
        var self = doc.querySelector('feed > link[rel="self"]');
        var full = self ? self.getAttribute("href") : (origin + url);
        var title = (doc.querySelector("feed > title") || {}).textContent || "";
        var place = (title.match(/for (.+)$/) || [])[1] || name;
        var entries = doc.querySelectorAll("feed > entry").length;
        var none = doc.querySelector("feed > entry > id") && /#none-/.test(doc.querySelector("feed > entry > id").textContent);
        result.innerHTML = "";
        var p = document.createElement("p");
        p.textContent = "Feed for " + place + (none ? " · ingen varsler akkurat nå." : " · " + entries + " varsel" + (entries === 1 ? "" : "er") + " nå.");
        var box = document.createElement("div"); box.className = "code";
        box.innerHTML = '<div class="code-head"><span>Lim inn i feedleseren</span><button type="button" class="copy">Kopier</button></div><pre></pre>';
        box.querySelector("pre").textContent = full;
        var open = document.createElement("p");
        var a = document.createElement("a"); a.href = full; a.textContent = "Åpne feeden";
        open.style.marginTop = "10px"; open.append(a);
        result.append(p, box, open);
      });
      return r.json().then(function () {
        result.className = "err";
        result.textContent = "Fant ingen kommune som heter «" + name + "». Prøv navnet eller det firesifrede kommunenummeret.";
      });
    }).catch(function () {
      result.className = "err"; result.textContent = "Fikk ikke kontakt med tjenesten. Prøv igjen om litt.";
    }).finally(function () { button.disabled = false; });
  });

  function shellQuote(text) { return "'" + text.replace(/'/g, "'\\\\''") + "'"; }

  function asCurl(method, path, args) {
    var t = target(method, path, args);
    if (t.body !== null) {
      return "curl -X POST " + shellQuote(origin + t.url) + " -H 'Content-Type: application/json' -d " + shellQuote(t.body);
    }
    return "curl " + shellQuote(origin + t.url);
  }

  function asMcp(tool, args) {
    return JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: tool, arguments: args } }, null, 2);
  }

  var LONG_LINES = 60, MAX_CHARS = 500000;

  document.querySelectorAll(".try").forEach(function (box) {
    var area = box.querySelector("textarea"), button = box.querySelector(".run");
    var result = box.querySelector(".result"), out = box.querySelector(".out"), status = box.querySelector(".status");
    var expand = box.querySelector(".expand");
    function showError(text) {
      result.hidden = false; result.classList.remove("collapsed"); expand.hidden = true;
      status.className = "status err"; status.textContent = "Feil"; out.textContent = text;
    }
    function args() {
      try { return JSON.parse(area.value || "{}"); }
      catch (e) { showError("Argumentene er ikke gyldig JSON: " + e.message); return null; }
    }
    box.querySelector(".copy-curl").addEventListener("click", function (e) {
      var a = args(); if (a !== null) copyText(asCurl(area.dataset.method, area.dataset.path, a), e.target);
    });
    box.querySelector(".copy-mcp").addEventListener("click", function (e) {
      var a = args(); if (a !== null) copyText(asMcp(area.dataset.tool, a), e.target);
    });
    expand.addEventListener("click", function () {
      var collapsed = result.classList.toggle("collapsed");
      expand.textContent = collapsed ? expand.dataset.more : "Vis mindre";
    });
    // After a result with provenance: turn it into BibTeX with cite_sources, on this server.
    var last = null, citeButton = box.querySelector(".cite"), bib = box.querySelector(".bib");
    citeButton.addEventListener("click", function () {
      if (!last) return;
      citeButton.disabled = true;
      fetch("/v1/cite", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provenance: last, style: "bibtex" }) })
        .then(function (r) { return r.json(); })
        .then(function (body) {
          bib.hidden = false;
          bib.querySelector("pre").textContent = body.data ? body.data.bibtex : JSON.stringify(body, null, 2);
        })
        .finally(function () { citeButton.disabled = false; });
    });
    button.addEventListener("click", function () {
      var a = args(); if (a === null) return;
      button.disabled = true; button.textContent = "Henter …";
      var started = performance.now();
      request(area.dataset.method, area.dataset.path, a)
        .then(function (r) { return r.json().then(function (body) { return [r.status, body]; }); })
        .then(function (res) {
          var ok = res[0] < 400, body = res[1];
          var seconds = ((performance.now() - started) / 1000).toFixed(1).replace(".", ",");
          result.hidden = false; bib.hidden = true;
          last = ok && body.provenance && body.provenance.length ? body.provenance : null;
          citeButton.hidden = !last;
          var sources = body.summary && body.summary.publishers ? body.summary.publishers.length : 0;
          status.className = ok ? "status ok" : "status err";
          status.textContent = ok
            ? "Svar på " + seconds + " s" + (sources ? " · " + sources + " kilde" + (sources === 1 ? "" : "r") : "")
            : "Feil " + res[0] + (body.error ? " · " + body.error.code : "");
          var text = JSON.stringify(body, null, 2);
          if (text.length > MAX_CHARS) text = text.slice(0, MAX_CHARS) + "\\n… (svaret er for langt til å vises her; bruk «Kopier som curl» for å hente alt)";
          out.textContent = text;
          var lines = text.split("\\n").length;
          var long = lines > LONG_LINES;
          result.classList.toggle("collapsed", long);
          expand.hidden = !long;
          expand.dataset.more = "Vis hele svaret (" + lines.toLocaleString("nb-NO") + " linjer)";
          expand.textContent = expand.dataset.more;
        })
        .catch(function (e) { showError("Fikk ikke kontakt med tjenesten: " + e); })
        .finally(function () { button.disabled = false; button.textContent = "▶ Kjør"; });
    });
  });
})();
</script>
</body>
</html>
"""
