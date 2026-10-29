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


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _code(text: str, label: str, *, html: bool = False) -> str:
    """A code box with a label and a copy button. It wraps long lines and grows to fit."""

    body = text if html else _e(text)
    return f"""<div class="code"><div class="code-head"><span>{_e(label)}</span><button type="button" class="copy">Kopier</button></div><pre><code>{body}</code></pre></div>"""


def _origin() -> str:
    # Filled in by the script with the address the page is served from.
    return f'<span class="origin">{HOSTED_URL}</span>'


ICONS = {
    "provenance": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/><path d="m10 14.5 2 2 4-4"/>',
    "errors": '<path d="M12 3v18"/><path d="M5 6h11l3 3-3 3H5z"/>',
    "regions": '<path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
    "polite": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "feed": '<path d="M5 11a8 8 0 0 1 8 8M5 5a14 14 0 0 1 14 14"/><circle cx="6" cy="18" r="1.5"/>',
}


def _icon(name: str) -> str:
    return (
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>'
    )


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
        f'<a class="chip tool-link" href="#tool-{_e(t)}"><code>{_e(t)}</code></a>'
        for t in source["tools"]
    )
    return f"""
      <article class="card source" id="source-{_e(source["id"])}">
        <header>
          <h3>{_e(nb.name)}</h3>
          <p class="muted">{_e(nb.publisher)}</p>
        </header>
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


def _type(schema: dict[str, Any]) -> str:
    if "enum" in schema:
        return " | ".join(map(str, schema["enum"]))
    if "anyOf" in schema:
        return " | ".join(_type(s) for s in schema["anyOf"] if s.get("type") != "null") or "any"
    if schema.get("type") == "array":
        return f"list of {_type(schema.get('items', {}))}"
    return schema.get("type") or schema.get("$ref", "object").rsplit("/", 1)[-1]


def _tool_block(tool: dict[str, Any], source_names: dict[str, str], theme: str = "") -> str:
    nb = _tool_text(tool)
    example = tool["examples"][0] if tool["examples"] else {}
    method, path = tool["http"]["method"], tool["http"]["path"]
    params = tool["input_schema"].get("properties", {})
    rows = "".join(
        f"<tr><td><code>{_e(name)}</code></td><td>{_e(_type(schema))}</td>"
        f"<td>{_e(schema.get('description', ''))}</td></tr>"
        for name, schema in params.items()
    )
    sources = ", ".join(source_names.get(s, s) for s in tool["sources"]) or "Kildeverk selv"
    search = " ".join([tool["name"], nb.title, nb.summary, tool["title"], sources, theme]).lower()
    return f"""
      <details class="tool" id="tool-{_e(tool["name"])}" data-search="{_e(search)}">
        <summary>
          <span class="tool-title">{_e(nb.title)}</span>
          <code class="tool-name">{_e(tool["name"])}</code>
          <span class="tool-sum">{_e(nb.summary)}</span>
        </summary>
        <div class="tool-body">
          <p class="endpoint small"><span class="method">{_e(method)}</span> <code>{_e(path)}</code> <span class="muted">· Kilde: {_e(sources)}</span></p>
          <div class="try">
            <label class="small muted" for="args-{_e(tool["name"])}">Argumenter (JSON). Endre dem og trykk «Kjør».</label>
            <textarea id="args-{_e(tool["name"])}" spellcheck="false" data-tool="{_e(tool["name"])}" data-method="{_e(method)}" data-path="{_e(path)}">{_e(json.dumps(example, ensure_ascii=False, indent=2))}</textarea>
            <div class="actions">
              <button type="button" class="run">Kjør</button>
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


def _tool_sections(tools: list[dict[str, Any]], source_names: dict[str, str]) -> str:
    by_name = {t["name"]: t for t in tools}
    themed = [name for _, _, names in site_nb.THEMES for name in names]
    themes = list(site_nb.THEMES)
    rest = [t["name"] for t in tools if t["name"] not in themed]
    if rest:
        themes.append(("Andre verktøy", "", rest))
    return "".join(
        f"""
    <section class="theme">
      <h3>{_e(title)}</h3>
      <p class="muted">{_e(blurb)}</p>
      <div class="tool-list">{"".join(_tool_block(by_name[n], source_names, f"{title} {blurb}") for n in names if n in by_name)}</div>
    </section>"""
        for title, blurb, names in themes
    )


RECIPES = Path(__file__).parent / "recipes.json"


def _stored_recipes() -> dict[str, Any]:
    if not RECIPES.exists():
        return {"built_at": "", "recipes": []}
    return json.loads(RECIPES.read_text(encoding="utf-8"))


def _publishers(recipe: dict[str, Any]) -> list[str]:
    names = [site_nb.PUBLISHERS.get(s["publisher"], s["publisher"]) for s in recipe["sources"]]
    return list(dict.fromkeys(names))


def _demo(stored: dict[str, Any]) -> str:
    """The hero's illustration: a question to an assistant, and the answer Kildeverk gave it."""

    slides = "".join(
        f"""
        <div class="slide{" active" if i == 0 else ""}" data-slide="{i}">
          <p class="msg user">{_e(r.get("question_nb", r["question"]))}</p>
          <p class="msg call"><span class="spark"></span><span>{_e(r["upstream_calls"])} oppslag hos kildene med <code>{_e(r["tool"])}</code></span></p>
          <div class="msg bot"><p>{_e(r.get("answer_nb", r["answer"]))}</p>
            <p class="chips">{"".join(f'<span class="chip">{_e(p)}</span>' for p in _publishers(r))}</p>
          </div>
        </div>"""
        for i, r in enumerate(stored["recipes"])
    )
    dots = "".join(
        f'<button type="button" class="dot{" active" if i == 0 else ""}" data-go="{i}" aria-label="Eksempel {i + 1}"></button>'
        for i in range(len(stored["recipes"]))
    )
    return f"""
      <div class="demo" aria-label="Eksempler på spørsmål og svar">
        <div class="demo-bar"><span></span><span></span><span></span><b>KI-assistent med Kildeverk</b></div>
        <div class="slides">{slides}
        </div>
        <div class="dots">{dots}</div>
      </div>"""


def _recipes(stored: dict[str, Any]) -> str:
    """Worked questions, run live by scripts/build_recipes.py and stored with the code."""

    if not stored["recipes"]:
        return ""
    cards = "".join(
        f"""
      <article class="card recipe">
        <h3>{_e(r.get("question_nb", r["question"]))}</h3>
        <p>{_e(r.get("answer_nb", r["answer"]))}</p>
        {_code(f"{r['tool']} {json.dumps(r['arguments'], ensure_ascii=False)}", "Kallet")}
        <p class="chips">{"".join(f'<span class="chip">{_e(p)}</span>' for p in _publishers(r))}</p>
        <p class="recipe-foot small"><span class="muted">Ett kall, {_e(r["upstream_calls"])} oppslag hos kildene</span>
        <a href="#tool-{_e(r["tool"])}" class="use-recipe" data-tool="{_e(r["tool"])}" data-args="{_e(json.dumps(r["arguments"], ensure_ascii=False))}">Prøv dette kallet →</a></p>
      </article>"""
        for r in stored["recipes"]
    )
    built = stored["built_at"][:10]
    day = f"{built[8:10]}.{built[5:7]}.{built[:4]}" if built else ""
    return f"""
  <section id="eksempler" class="wrap">
    <p class="eyebrow">Eksempler</p>
    <h2>Ekte spørsmål, besvart med ett kall</h2>
    <p class="lead-s">Kjørt {_e(day)}. Tallene er slik kildene hadde dem da; trykk «Prøv dette kallet» for å hente dem på nytt.</p>
    <div class="grid recipes">{cards}
    </div>
  </section>"""


EXAMPLE_QUESTIONS = [
    "Hvordan blir været i Tromsø i morgen?",
    "Hvilke kommuner har vokst mest siden 2015?",
    "Er det flom- eller jordskredvarsel i Bergen nå?",
    "Når går de neste togene fra Oslo S?",
    "Hvor fulle er vannmagasinene sammenlignet med normalt?",
    "Hva er styringsrenten, og når ble den sist endret?",
]


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
            "<p>Kjør dette i terminalen, så har Claude Code alle verktøyene:</p>"
            + _code(
                f"claude mcp add --transport http kildeverk {origin}/mcp", "Terminal", html=True
            ),
        ),
        (
            "apps",
            "Claude, ChatGPT og andre",
            "<p>I assistenter som støtter eksterne MCP-servere: legg til en egendefinert "
            "konnektor (ofte under <em>Innstillinger → Konnektorer</em>) og lim inn adressen:</p>"
            + _code(f"{origin}/mcp", "Adresse", html=True),
        ),
        (
            "config",
            "Cursor, VS Code m.fl.",
            "<p>Klienter som leser en konfigurasjonsfil, tar denne:</p>"
            + _code(_e(mcp_json).replace(_e(origin), origin), "JSON", html=True),
        ),
        (
            "api",
            "JSON-API",
            '<p>Hvert verktøy er også en vanlig nettadresse. Se <a href="/docs">API-dokumentasjonen</a>.</p>'
            + _code(
                f'curl "{origin}/v1/weather/forecast?lat=59.91&amp;lon=10.75&amp;hours=3"',
                "Terminal",
                html=True,
            ),
        ),
        (
            "local",
            "Kjør selv",
            "<p>Med egen kvote og eget mellomlager, over stdio. Krever "
            '<a href="https://docs.astral.sh/uv/">uv</a>.</p>' + _code(local_json, "JSON"),
        ),
    ]
    buttons = "".join(
        f'<button type="button" role="tab" id="tab-{key}" aria-controls="panel-{key}" '
        f'aria-selected="{"true" if i == 0 else "false"}">{_e(label)}</button>'
        for i, (key, label, _) in enumerate(tabs)
    )
    panels = "".join(
        f'<div role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}" class="tabpanel"'
        f"{'' if i == 0 else ' hidden'}>{body}</div>"
        for i, (key, _, body) in enumerate(tabs)
    )
    questions = "".join(
        f'<li><button type="button" class="ask" data-text="{_e(q)}">{_e(q)}</button></li>'
        for q in EXAMPLE_QUESTIONS
    )
    return f"""
  <section id="kom-i-gang" class="wrap">
    <p class="eyebrow">Kom i gang</p>
    <h2>Koble til på ett minutt</h2>
    <p class="lead-s">Kildeverk bruker MCP (Model Context Protocol), den åpne standarden som lar
    KI-assistenter bruke verktøy. Du trenger ingen konto og ingen nøkkel.</p>
    <div class="steps">
      <div class="card step">
        <p class="step-n"><span>1</span>Legg til serveren</p>
        <div class="tabs" role="tablist" aria-label="Velg klient">{buttons}</div>
        {panels}
      </div>
      <div class="card step">
        <p class="step-n"><span>2</span>Spør i vei</p>
        <p>Assistenten velger selv verktøyene og forteller hvor tallene kommer fra. Trykk på et
        spørsmål for å kopiere det.</p>
        <ul class="asks">{questions}</ul>
        <p class="muted small">Verktøyene svarer på engelsk, slik assistentene leser dem best,
        men du kan spørre på norsk.</p>
      </div>
    </div>
  </section>"""


def render(catalogue: dict[str, Any]) -> str:
    sources = catalogue["sources"]
    tools = catalogue["tools"]
    source_names = {s["id"]: _source_text(s).name for s in sources}
    # "Kartverket" and "Kartverket, Hydrographic Service" are one publisher.
    publishers = len({s["publisher"].split(",")[0].split("(")[0].strip() for s in sources})
    stored = _stored_recipes()
    parts = {
        "VERSION": _e(catalogue["version"]),
        "N_SOURCES": str(len(sources)),
        "N_TOOLS": str(len(tools)),
        "N_PUBLISHERS": str(publishers),
        "DEMO": _demo(stored),
        "CONNECT": _connect(),
        "RECIPES": _recipes(stored),
        "CARDS": "".join(_source_card(s) for s in sources),
        "TOOLS": _tool_sections(tools, source_names),
        "REPO": REPO_URL,
        "HOSTED": HOSTED_URL,
        "ICON_PROVENANCE": _icon("provenance"),
        "ICON_ERRORS": _icon("errors"),
        "ICON_REGIONS": _icon("regions"),
        "ICON_POLITE": _icon("polite"),
        "ICON_FEED": _icon("feed"),
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
<meta name="color-scheme" content="light dark">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%230e4d78'/><path d='M9 7v18M9 16l10-9M12 13l9 12' stroke='white' stroke-width='3' fill='none' stroke-linecap='round'/></svg>">
<style>
:root {
  --bg: #f5f3ee; --panel: #ffffff; --ink: #16202b; --muted: #5a6472; --line: #e3ded3;
  --accent: #0e4d78; --accent-strong: #0a3a5c; --accent-soft: #e4eef6; --accent-ink: #ffffff;
  --red: #b8202f; --warn: #7d5200; --warn-bg: #fff0cf; --ok: #1e6b3a; --err: #a12c2c;
  --code-bg: #f3f0e9; --code-head: #ebe7de; --chip: #eef2f5;
  --ridge-1: #d3e1ec; --ridge-2: #b2c9db; --ridge-3: #8eaec7;
  --shadow: 0 1px 2px rgba(22, 32, 43, .05), 0 10px 30px rgba(22, 32, 43, .07);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1318; --panel: #141d25; --ink: #e7ecf1; --muted: #9ba7b5; --line: #24313b;
    --accent: #7cc0f0; --accent-strong: #a9d6f7; --accent-soft: #11263a; --accent-ink: #0b1117;
    --red: #ff7683; --warn: #f2c46d; --warn-bg: #352a12; --ok: #7bd39a; --err: #ff9c9c;
    --code-bg: #0f171e; --code-head: #17222c; --chip: #1a2630;
    --ridge-1: #13273a; --ridge-2: #17314a; --ridge-3: #1d3d5b;
    --shadow: 0 1px 2px rgba(0, 0, 0, .3);
  }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html { scroll-behavior: smooth; scroll-padding-top: 76px; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 16.5px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased; }
a { color: var(--accent); text-underline-offset: 2px; }
code, pre, textarea { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .86em; }
:not(pre) > code { background: var(--chip); padding: .08em .38em; border-radius: 5px; overflow-wrap: anywhere; }
h1, h2, h3 { letter-spacing: -0.02em; line-height: 1.2; }
.wrap { max-width: 1120px; margin: 0 auto; padding-left: 16px; padding-right: 16px; }
.muted { color: var(--muted); }
.small { font-size: .88rem; }
.icon { width: 22px; height: 22px; flex: none; }

/* Navigation */
nav.top { position: sticky; top: 0; z-index: 10; background: color-mix(in srgb, var(--bg) 82%, transparent);
  backdrop-filter: saturate(1.4) blur(10px); -webkit-backdrop-filter: saturate(1.4) blur(10px);
  border-bottom: 1px solid color-mix(in srgb, var(--line) 70%, transparent); }
nav.top .wrap { display: flex; align-items: center; gap: 22px; height: 60px; }
.brand { display: flex; align-items: center; gap: 9px; font-weight: 800; font-size: 1.08rem; color: var(--ink); text-decoration: none; flex: none; }
.brand svg { width: 26px; height: 26px; }
.navlinks { display: flex; gap: 20px; overflow-x: auto; scrollbar-width: none; margin-left: auto; }
.navlinks::-webkit-scrollbar { display: none; }
.navlinks a { color: var(--muted); text-decoration: none; font-weight: 550; font-size: .95rem; white-space: nowrap; }
.navlinks a:hover { color: var(--ink); }

/* Hero */
.hero { position: relative; background: linear-gradient(180deg, var(--accent-soft), var(--bg) 92%); overflow: hidden; }
.hero .wrap { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr); gap: 48px; align-items: center; padding-top: 64px; padding-bottom: 120px; position: relative; z-index: 1; }
.kicker { display: inline-flex; align-items: center; gap: 8px; font-size: .85rem; font-weight: 650; color: var(--accent);
  background: var(--panel); border: 1px solid var(--line); border-radius: 99px; padding: 4px 12px 4px 8px; margin: 0 0 18px; }
.kicker i { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 25%, transparent); }
.hero h1 { font-size: clamp(2.3rem, 5.4vw, 3.7rem); font-weight: 820; letter-spacing: -0.035em; line-height: 1.04; margin: 0 0 18px; }
.hero h1 em { font-style: normal; color: var(--accent); }
.hero .lead { font-size: 1.16rem; color: var(--muted); margin: 0 0 26px; max-width: 34rem; }
.cta { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 30px; }
.button { display: inline-flex; align-items: center; gap: 8px; padding: 11px 20px; border-radius: 10px; font-weight: 650; text-decoration: none; }
.button.primary { background: var(--accent); color: var(--accent-ink); }
.button.primary:hover { background: var(--accent-strong); }
.button.secondary { background: var(--panel); color: var(--ink); border: 1px solid var(--line); }
.stats { display: flex; gap: 34px; flex-wrap: wrap; margin: 0; padding: 0; list-style: none; }
.stats li { color: var(--muted); font-size: .92rem; }
.stats b { display: block; font-size: 1.75rem; color: var(--ink); font-weight: 800; letter-spacing: -0.02em; line-height: 1.2; }
.ridges { position: absolute; left: 0; right: 0; bottom: -1px; width: 100%; height: 150px; z-index: 0; }

/* The illustration in the hero */
.demo { background: var(--panel); border: 1px solid var(--line); border-radius: 16px; box-shadow: var(--shadow); overflow: hidden; }
.demo-bar { display: flex; align-items: center; gap: 6px; padding: 11px 14px; border-bottom: 1px solid var(--line); font-size: .82rem; color: var(--muted); }
.demo-bar span { width: 10px; height: 10px; border-radius: 50%; background: var(--line); }
.demo-bar b { font-weight: 600; margin-left: 8px; }
.slides { display: grid; padding: 18px; }
.slide { grid-area: 1 / 1; opacity: 0; visibility: hidden; transition: opacity .45s ease, visibility .45s; }
.slide.active { opacity: 1; visibility: visible; }
.msg { margin: 0 0 12px; border-radius: 14px; padding: 11px 14px; font-size: .95rem; }
.msg.user { background: var(--accent); color: var(--accent-ink); margin-left: 18%; border-bottom-right-radius: 4px; font-weight: 550; }
.msg.call { background: transparent; color: var(--muted); padding: 0 2px; font-size: .84rem; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.spark { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); flex: none; }
.msg.bot { background: var(--code-bg); border-bottom-left-radius: 4px; margin-right: 6%; }
.msg.bot p { margin: 0; }
.msg.bot .chips { margin-top: 10px; }
.dots { display: flex; justify-content: center; gap: 8px; padding: 0 0 14px; }
.dot { width: 9px; height: 9px; padding: 0; border-radius: 50%; border: 0; background: var(--line); cursor: pointer; }
.dot.active { background: var(--accent); width: 22px; border-radius: 99px; }

/* Sections */
main > section, main > .band { padding-top: 64px; padding-bottom: 8px; }
.eyebrow { margin: 0 0 6px; font-size: .8rem; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; color: var(--red); }
h2 { font-size: clamp(1.6rem, 3.2vw, 2.2rem); font-weight: 780; margin: 0 0 10px; }
.lead-s { color: var(--muted); max-width: 44rem; margin: 0 0 26px; font-size: 1.04rem; }
.grid { display: grid; gap: 18px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 22px; min-width: 0; box-shadow: var(--shadow); }
.card h3 { margin: 0 0 8px; font-size: 1.1rem; }

/* Getting started */
.steps { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); gap: 18px; align-items: start; }
.step-n { display: flex; align-items: center; gap: 10px; font-weight: 750; font-size: 1.08rem; margin: 0 0 14px; }
.step-n span { display: inline-grid; place-items: center; width: 28px; height: 28px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); font-size: .9rem; }
.tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 14px; }
.tabs button { background: transparent; color: var(--muted); border: 1px solid var(--line); font-weight: 600; padding: 6px 12px; border-radius: 99px; font-size: .88rem; }
.tabs button[aria-selected="true"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.tabpanel > p { margin: 0 0 10px; }
.asks { list-style: none; padding: 0; margin: 12px 0; display: grid; gap: 8px; }
.ask { width: 100%; text-align: left; background: var(--code-bg); color: var(--ink); border: 1px solid var(--line); font-weight: 500; padding: 9px 13px; border-radius: 10px; }
.ask:hover { border-color: var(--accent); }
.ask.copied { border-color: var(--ok); color: var(--ok); }

/* Code boxes: they wrap and grow, so nothing is hidden behind a scrollbar. */
.code { border: 1px solid var(--line); border-radius: 10px; background: var(--code-bg); overflow: hidden; margin: 10px 0 0; }
.code-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 5px 6px 5px 12px; background: var(--code-head); font-size: .78rem; color: var(--muted); font-weight: 600; }
.code-head .copy { padding: 3px 10px; font-size: .78rem; background: transparent; color: var(--accent); border: 1px solid var(--line); }
.code pre { margin: 0; padding: 12px 14px; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.55; color: var(--ink); }
.code pre code { background: none; padding: 0; font-size: 1em; }
.status.ok { color: var(--ok); }
.status.err { color: var(--err); }

/* Promises */
.promises { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.promise .icon { color: var(--accent); width: 26px; height: 26px; margin-bottom: 10px; }
.promise p { margin: 0; color: var(--muted); font-size: .95rem; }

/* Recipes */
.recipes { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.recipe { display: flex; flex-direction: column; }
.recipe > p { margin: 0 0 6px; }
.recipe .chips { margin: 12px 0 0; }
.recipe-foot { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin: auto 0 0 !important; padding-top: 14px; }
.recipe-foot a { font-weight: 650; text-decoration: none; }

/* Feed */
.feed { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 28px; align-items: center; }
.feed h2 { display: flex; align-items: center; gap: 10px; }
.feed h2 .icon { color: var(--red); width: 28px; height: 28px; }
.feed form { display: flex; gap: 8px; }
.feed input { flex: 1; min-width: 0; font: inherit; padding: 11px 14px; border-radius: 10px; border: 1px solid var(--line); background: var(--bg); color: var(--ink); }
#feed-result { margin: 12px 0 0; }
#feed-result.err { color: var(--err); }

/* Sources */
.cards { grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); }
.source header p { margin: 0; font-size: .92rem; }
.badges { margin: 12px 0 6px; display: flex; gap: 6px; flex-wrap: wrap; }
.badge { font-size: .76rem; font-weight: 650; padding: 2px 9px; border-radius: 99px; border: 1px solid var(--line); text-decoration: none; color: var(--ink); }
.badge.warn { background: var(--warn-bg); color: var(--warn); border-color: transparent; }
.covers { padding-left: 18px; margin: 10px 0; font-size: .93rem; }
.covers li { margin: 4px 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.chip { font-size: .78rem; background: var(--chip); color: var(--ink); padding: 3px 9px; border-radius: 99px; text-decoration: none; }
.chip code { background: none; padding: 0; }
a.chip:hover { background: var(--accent-soft); color: var(--accent); }
details.more > summary { cursor: pointer; color: var(--accent); font-size: .9rem; font-weight: 600; }
details.more ul { font-size: .9rem; padding-left: 18px; }
.links { display: flex; gap: 14px; flex-wrap: wrap; margin: 12px 0 0; }

/* Tools */
.finder { display: flex; align-items: center; gap: 10px; margin: 0 0 8px; }
.finder input { flex: 1; min-width: 0; font: inherit; padding: 12px 16px; border-radius: 12px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); box-shadow: var(--shadow); }
#no-match { margin: 18px 0; }
.theme { margin-top: 30px; }
.theme > h3 { margin: 0 0 2px; font-size: 1.2rem; }
.theme > p { margin: 0 0 12px; font-size: .95rem; }
.tool-list { display: grid; gap: 10px; }
.tool { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; }
.tool[open] { box-shadow: var(--shadow); }
.tool > summary { list-style: none; cursor: pointer; padding: 14px 44px 14px 18px; position: relative; display: grid; grid-template-columns: auto 1fr; column-gap: 12px; row-gap: 2px; align-items: baseline; }
.tool > summary::-webkit-details-marker { display: none; }
.tool > summary::after { content: ""; position: absolute; right: 18px; top: 21px; width: 8px; height: 8px; border-right: 2px solid var(--muted); border-bottom: 2px solid var(--muted); transform: rotate(45deg); transition: transform .2s; }
.tool[open] > summary::after { transform: rotate(-135deg); top: 25px; }
.tool-title { font-weight: 700; }
.tool-name { justify-self: start; font-size: .78rem; color: var(--muted); }
.tool-sum { grid-column: 1 / -1; color: var(--muted); font-size: .93rem; }
.tool-body { padding: 0 18px 18px; border-top: 1px solid var(--line); }
.endpoint { margin: 14px 0 12px; }
.method { font-weight: 800; font-size: .72rem; color: var(--accent); background: var(--accent-soft); padding: 2px 7px; border-radius: 5px; }
.try label { display: block; margin-bottom: 6px; }
.try textarea { display: block; width: 100%; min-height: 3.2em; resize: vertical; overflow: hidden; background: var(--code-bg); color: var(--ink);
  border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; line-height: 1.55; }
.try textarea:focus, .finder input:focus, .feed input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
button { font: inherit; border: 0; border-radius: 9px; padding: 8px 15px; cursor: pointer; background: var(--accent); color: var(--accent-ink); font-weight: 650; }
button:hover { filter: brightness(1.06); }
button:disabled { opacity: .6; cursor: progress; }
button.ghost { background: transparent; color: var(--accent); border: 1px solid var(--line); }
.result .code { margin-top: 14px; }
.result.collapsed pre { max-height: 30em; overflow: hidden; -webkit-mask-image: linear-gradient(180deg, #000 75%, transparent); mask-image: linear-gradient(180deg, #000 75%, transparent); }
.expand { margin-top: 8px; }
.bib .code { margin-top: 10px; }
.spec { margin-top: 16px; }
.spec p { margin: 10px 0 0; }
table { border-collapse: collapse; width: 100%; font-size: .85rem; margin-top: 10px; }
td { border-top: 1px solid var(--line); padding: 7px 10px 7px 0; vertical-align: top; overflow-wrap: anywhere; }
td:first-child { white-space: nowrap; }

footer { border-top: 1px solid var(--line); margin-top: 72px; padding: 28px 0 48px; color: var(--muted); font-size: .9rem; }
footer .wrap { display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; }
footer p { margin: 0; max-width: 40rem; }
footer nav { display: flex; gap: 16px; flex-wrap: wrap; }

@media (max-width: 900px) {
  .hero .wrap { grid-template-columns: minmax(0, 1fr); gap: 36px; padding-top: 40px; padding-bottom: 100px; }
  .steps, .feed { grid-template-columns: minmax(0, 1fr); }
  .promises { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  nav.top .wrap { gap: 14px; }
  .navlinks { gap: 14px; padding-right: 18px; -webkit-mask-image: linear-gradient(90deg, #000 85%, transparent); mask-image: linear-gradient(90deg, #000 85%, transparent); }
  .stats { gap: 22px; }
  .card { padding: 18px; }
  .recipes, .cards, .promises { grid-template-columns: minmax(0, 1fr); }
  .msg.user { margin-left: 8%; }
  .feed form { flex-direction: column; }
}
</style>
</head>
<body>
<nav class="top">
  <div class="wrap">
    <a class="brand" href="#"><svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="var(--accent)"/><path d="M9 7v18M9 16l10-9M12 13l9 12" stroke="var(--accent-ink)" stroke-width="3" fill="none" stroke-linecap="round"/></svg>Kildeverk</a>
    <div class="navlinks">
      <a href="#kom-i-gang">Kom i gang</a>
      <a href="#eksempler">Eksempler</a>
      <a href="#varsler">Varsler</a>
      <a href="#kilder">Kilder</a>
      <a href="#verktoy">Verktøy</a>
      <a href="/docs">API</a>
      <a href="@@REPO@@">GitHub</a>
    </div>
  </div>
</nav>

<header class="hero">
  <div class="wrap">
    <div>
      <p class="kicker"><i></i>Åpent, gratis og uten konto</p>
      <h1>Norske offentlige data, <em>rett fra kilden.</em></h1>
      <p class="lead">Kildeverk gir KI-assistenter og utviklere ferske tall fra SSB,
      Meteorologisk institutt, NVE, Kartverket, Entur, Brønnøysundregistrene og flere.
      Hvert svar sier nøyaktig hvor det kommer fra.</p>
      <div class="cta">
        <a class="button primary" href="#kom-i-gang">Kom i gang</a>
        <a class="button secondary" href="#verktoy">Prøv verktøyene</a>
      </div>
      <ul class="stats">
        <li><b>@@N_SOURCES@@</b>kilder</li>
        <li><b>@@N_PUBLISHERS@@</b>utgivere</li>
        <li><b>@@N_TOOLS@@</b>verktøy</li>
      </ul>
    </div>
    @@DEMO@@
  </div>
  <svg class="ridges" viewBox="0 0 1440 150" preserveAspectRatio="none" aria-hidden="true">
    <path style="fill: var(--ridge-1)" d="M0 92 120 52l100 30 120-58 130 56 120-40 130 52 130-68 130 56 130-34 130 44 100-30 100 22V150H0Z"/>
    <path style="fill: var(--ridge-2)" d="M0 118 160 80l140 30 120-38 140 46 140-40 160 48 140-36 150 40 140-34 150 28V150H0Z"/>
    <path style="fill: var(--ridge-3); opacity: .55" d="M0 134 200 112l180 26 160-22 220 28 200-24 220 26 260-18V150H0Z"/>
    <path style="fill: var(--bg)" d="M0 150V140l240-8 260 12 280-10 300 12 360-8V150Z"/>
  </svg>
</header>

<main>
@@CONNECT@@

  <section class="wrap">
    <p class="eyebrow">Hvorfor Kildeverk</p>
    <h2>Svar du kan stole på og sitere</h2>
    <p class="lead-s">Kildeverk henter alt direkte fra utgiverne, i det øyeblikket du spør. Ingenting er kopiert eller gjettet.</p>
    <div class="grid promises">
      <div class="card promise">@@ICON_PROVENANCE@@<h3>Kilden står på hvert svar</h3><p>Utgiver, lisens, nøyaktig adresse til dataene, når de ble hentet, og en ferdig kildehenvisning.</p></div>
      <div class="card promise">@@ICON_ERRORS@@<h3>Feil som forklarer seg</h3><p>Hver feil har en kode, en forklaring, om det hjelper å prøve igjen, og ofte det neste kallet å gjøre.</p></div>
      <div class="card promise">@@ICON_REGIONS@@<h3>Kommuner som henger sammen</h3><p>Kommune- og fylkesnumre følges gjennom reformene i 2020 og 2024, så gamle og nye tall kan sammenlignes.</p></div>
      <div class="card promise">@@ICON_POLITE@@<h3>Høflig mot kildene</h3><p>En kvote under hver kildes grense, mellomlagring og felles kall, så tjenestene ikke belastes.</p></div>
    </div>
  </section>

@@RECIPES@@

  <section id="varsler" class="wrap">
    <div class="card feed">
      <div>
        <p class="eyebrow">Farevarsler</p>
        <h2>@@ICON_FEED@@Varsler for din kommune</h2>
        <p class="muted">Farevarsler for vær, flom, jordskred og snøskred samlet i én Atom-feed, som du kan
        følge i en hvilken som helst feedleser. Sjekk alltid varsom.no og yr.no før du handler.</p>
      </div>
      <div>
        <form id="feed-form">
          <input id="feed-name" type="text" placeholder="Kommune, f.eks. Tromsø eller 4601" aria-label="Kommunenavn eller kommunenummer" autocomplete="off">
          <button type="submit">Lag feed</button>
        </form>
        <div id="feed-result" class="small" hidden></div>
      </div>
    </div>
  </section>

  <section id="kilder" class="wrap">
    <p class="eyebrow">Kilder</p>
    <h2>@@N_SOURCES@@ kilder fra @@N_PUBLISHERS@@ utgivere</h2>
    <p class="lead-s">Hver kilde oppgir lisensen slik utgiveren skriver den, og hvert svar gjentar den.
    To av kildene krever en gratis nøkkel; den offentlige tjenesten har begge.</p>
    <div class="grid cards">@@CARDS@@
    </div>
  </section>

  <section id="verktoy" class="wrap">
    <p class="eyebrow">Verktøy</p>
    <h2>Prøv verktøyene her</h2>
    <p class="lead-s">De samme @@N_TOOLS@@ verktøyene finnes over MCP og som nettadresser. Åpne et
    verktøy, endre eksempelet om du vil, og trykk «Kjør» for å hente ferske data.</p>
    <div class="finder">
      <input id="tool-search" type="search" placeholder="Søk blant @@N_TOOLS@@ verktøy, f.eks. «vær», «skole» eller «tog»" aria-label="Søk blant verktøyene">
    </div>
    <p id="no-match" class="muted" hidden>Ingen verktøy passer søket.</p>
    @@TOOLS@@
  </section>
</main>

<footer>
  <div class="wrap">
    <p>Kildeverk @@VERSION@@ er et personlig, ikke-kommersielt prosjekt med åpen kildekode (MIT).
    Det er ikke tilknyttet noen av utgiverne. Dataene tilhører dem og kommer under deres lisenser,
    som hvert svar oppgir.</p>
    <nav>
      <a href="@@REPO@@">GitHub</a>
      <a href="/docs">API-dokumentasjon</a>
      <a href="/openapi.json">OpenAPI</a>
      <a href="catalogue.json">Katalog (JSON)</a>
      <a href="@@REPO@@/blob/main/CHANGELOG.md">Endringslogg</a>
    </nav>
  </div>
</footer>

<script>
(function () {
  var served = location.origin.indexOf("http") === 0;
  var origin = served ? location.origin : "@@HOSTED@@";
  document.querySelectorAll(".origin").forEach(function (el) { el.textContent = origin; });

  function copyText(text, button, done) {
    navigator.clipboard.writeText(text).then(function () { flash(button, done || "Kopiert"); });
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

  // Tabs in "Kom i gang".
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

  document.querySelectorAll(".ask").forEach(function (b) {
    b.addEventListener("click", function () {
      navigator.clipboard.writeText(b.dataset.text).then(function () {
        b.classList.add("copied"); var t = b.textContent; b.textContent = "Kopiert: " + t;
        setTimeout(function () { b.classList.remove("copied"); b.textContent = t; }, 1600);
      });
    });
  });

  // The hero's examples take turns, unless the reader prefers less motion or is reading one.
  var slides = document.querySelectorAll(".slide"), dots = document.querySelectorAll(".dot"), current = 0, paused = false;
  function show(i) {
    current = i;
    slides.forEach(function (s, j) { s.classList.toggle("active", i === j); });
    dots.forEach(function (d, j) { d.classList.toggle("active", i === j); });
  }
  dots.forEach(function (d) { d.addEventListener("click", function () { show(Number(d.dataset.go)); paused = true; }); });
  var demo = document.querySelector(".demo");
  if (demo) {
    demo.addEventListener("mouseenter", function () { paused = true; });
    demo.addEventListener("mouseleave", function () { paused = false; });
  }
  if (slides.length > 1 && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    setInterval(function () { if (!paused && !document.hidden) show((current + 1) % slides.length); }, 7000);
  }

  // A textarea grows to show all of its arguments.
  function fit(area) { area.style.height = "auto"; area.style.height = area.scrollHeight + 2 + "px"; }
  document.querySelectorAll(".try textarea").forEach(function (area) {
    area.addEventListener("input", function () { fit(area); });
  });
  document.querySelectorAll("details.tool").forEach(function (d) {
    d.addEventListener("toggle", function () { if (d.open) fit(d.querySelector("textarea")); });
  });

  // A link to a tool opens it.
  function openFromHash() {
    var id = decodeURIComponent(location.hash.slice(1));
    var el = id && document.getElementById(id);
    if (el && el.matches("details.tool")) { el.open = true; fit(el.querySelector("textarea")); }
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

  // Search among the tools.
  var search = document.getElementById("tool-search"), noMatch = document.getElementById("no-match");
  if (search) search.addEventListener("input", function () {
    var words = search.value.toLowerCase().trim().split(/\\s+/).filter(Boolean), any = false;
    document.querySelectorAll(".theme").forEach(function (theme) {
      var shown = 0;
      theme.querySelectorAll("details.tool").forEach(function (tool) {
        var hit = words.every(function (w) { return tool.dataset.search.indexOf(w) !== -1; });
        tool.hidden = !hit; if (hit) shown++;
      });
      theme.hidden = shown === 0; if (shown) any = true;
    });
    noMatch.hidden = any;
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

  // Check the name resolves (the feed answers JSON errors) before offering the link.
  var feedForm = document.getElementById("feed-form");
  if (feedForm) feedForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var name = document.getElementById("feed-name").value.trim();
    var result = document.getElementById("feed-result");
    if (!name) return;
    var button = feedForm.querySelector("button"); button.disabled = true;
    // The Norwegian feed, to match the page; its own self link keeps ?lang=nb for the reader.
    var url = "/v1/feeds/warnings/" + encodeURIComponent(name) + ".atom?lang=nb";
    fetch(url).then(function (r) {
      result.hidden = false; result.className = "small";
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
        open.append(a);
        result.append(p, box, open);
      });
      return r.json().then(function () {
        result.className = "small err";
        result.textContent = "Fant ingen kommune som heter «" + name + "». Prøv navnet eller det firesifrede kommunenummeret.";
      });
    }).catch(function () {
      result.hidden = false; result.className = "small err"; result.textContent = "Fikk ikke kontakt med tjenesten. Prøv igjen om litt.";
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
        .finally(function () { button.disabled = false; button.textContent = "Kjør"; });
    });
  });
})();
</script>
</body>
</html>
"""
