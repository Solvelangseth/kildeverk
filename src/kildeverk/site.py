"""Build the static website from the catalogue: `kildeverk site --out site/`.

Everything on the page comes from the registry, so the site cannot list a tool or a
licence the code does not have. The only script is the "Try it" button, which calls the
same deployment's JSON API.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from kildeverk.catalogue import build_catalogue
from kildeverk.settings import REPO_URL


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _source_card(source: dict[str, Any]) -> str:
    licence = source["licence"]
    key = (
        f'<span class="badge warn" title="Set {_e(", ".join(source["requires_env"]))}">needs a free key</span>'
        if source["requires_env"]
        else ""
    )
    covers = "".join(f"<li>{_e(c)}</li>" for c in source["covers"])
    gaps = "".join(f"<li>{_e(g)}</li>" for g in source["known_gaps"])
    tools = " ".join(
        f'<a class="tool-link" href="#tool-{_e(t)}"><code>{_e(t)}</code></a>'
        for t in source["tools"]
    )
    return f"""
      <article class="card" id="source-{_e(source["id"])}">
        <header>
          <h3>{_e(source["name"])}</h3>
          <p class="muted">{_e(source["publisher"])}</p>
        </header>
        <p class="badges">
          <a class="badge" href="{_e(licence["url"])}" title="{_e(licence["name"])}">{_e(licence["id"])}</a>
          {key}
        </p>
        <ul class="covers">{covers}</ul>
        <p class="tools">{tools}</p>
        <details>
          <summary>Known gaps and limits</summary>
          <ul>{gaps}</ul>
          <p class="muted small">Upstream limit: {_e(source["upstream_limit"])}.
          This service spends at most {_e(source["this_service_max_per_minute"])} calls a minute.</p>
        </details>
        <p class="links small">
          <a href="{_e(source["homepage"])}">Publisher</a> ·
          <a href="{_e(source["docs_url"])}">API docs</a> ·
          <a href="{_e(source["terms_url"])}">Terms</a> ·
          <a href="{REPO_URL}#{_e(source["id"])}">Notes</a>
        </p>
      </article>"""


def _tool_block(tool: dict[str, Any]) -> str:
    example = tool["examples"][0] if tool["examples"] else {}
    method, path = tool["http"]["method"], tool["http"]["path"]
    params = tool["input_schema"].get("properties", {})
    rows = "".join(
        f"<tr><td><code>{_e(name)}</code></td><td>{_e(_type(schema))}</td>"
        f"<td>{_e(schema.get('description', ''))}</td></tr>"
        for name, schema in params.items()
    )
    return f"""
      <article class="tool" id="tool-{_e(tool["name"])}">
        <header>
          <h3><code>{_e(tool["name"])}</code></h3>
          <p class="muted">{_e(tool["title"])} · <span class="method">{_e(method)}</span> <code>{_e(path)}</code></p>
        </header>
        <p>{_e(tool["description"])}</p>
        <details>
          <summary>Arguments</summary>
          <table><tbody>{rows or '<tr><td colspan="3">None.</td></tr>'}</tbody></table>
        </details>
        <div class="try">
          <textarea spellcheck="false" aria-label="Arguments for {_e(tool["name"])}"
            data-tool="{_e(tool["name"])}" data-method="{_e(method)}" data-path="{_e(path)}">{_e(json.dumps(example, ensure_ascii=False, indent=2))}</textarea>
          <div class="actions">
            <button type="button" class="run">Try it</button>
            <button type="button" class="ghost copy-curl">Copy as curl</button>
            <button type="button" class="ghost copy-mcp">Copy as MCP call</button>
            <button type="button" class="ghost cite" hidden>Cite these sources</button>
          </div>
          <pre class="out" hidden></pre>
          <pre class="bib" hidden></pre>
        </div>
      </article>"""


def _type(schema: dict[str, Any]) -> str:
    if "enum" in schema:
        return " | ".join(map(str, schema["enum"]))
    if "anyOf" in schema:
        return " | ".join(_type(s) for s in schema["anyOf"] if s.get("type") != "null") or "any"
    if schema.get("type") == "array":
        return f"list of {_type(schema.get('items', {}))}"
    return schema.get("type") or schema.get("$ref", "object").rsplit("/", 1)[-1]


RECIPES = Path(__file__).parent / "recipes.json"


def _recipes() -> str:
    """Worked questions, run live by scripts/build_recipes.py and stored with the code."""

    if not RECIPES.exists():
        return ""
    stored = json.loads(RECIPES.read_text(encoding="utf-8"))
    cards = "".join(
        f"""
      <article class="panel recipe">
        <h3>{_e(r["question"])}</h3>
        <p>{_e(r["answer"])}</p>
        <pre><code>{_e(r["tool"])} {_e(json.dumps(r["arguments"], ensure_ascii=False))}</code></pre>
        <p class="muted small">One call, {_e(r["upstream_calls"])} upstream requests. Sources:
        {_e("; ".join(f"{s['publisher']} ({s['licence']})" for s in r["sources"]))}.</p>
        <p class="small"><a href="#tool-{_e(r["tool"])}">Try <code>{_e(r["tool"])}</code></a></p>
      </article>"""
        for r in stored["recipes"]
    )
    return f"""
  <section id="recipes">
    <h2>Recipes</h2>
    <p>Real questions, each answered with one call. Run on {_e(stored["built_at"][:10])}; the
    figures are as the publishers had them then.</p>
    <div class="recipes">{cards}
    </div>
  </section>"""


def render(catalogue: dict[str, Any]) -> str:
    sources = catalogue["sources"]
    tools = catalogue["tools"]
    order = {s["id"]: i for i, s in enumerate(sources)}
    tools = sorted(tools, key=lambda t: order.get(t["sources"][0], 999) if t["sources"] else 999)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for tool in tools:
        by_source.setdefault(tool["sources"][0] if tool["sources"] else "", []).append(tool)
    names = {s["id"]: s["name"] for s in sources}
    tool_sections = "".join(
        f'<section class="tool-group"><h3 class="group">{_e(names.get(sid, "About the service"))}</h3>'
        + "".join(_tool_block(t) for t in group)
        + "</section>"
        for sid, group in by_source.items()
    )
    cards = "".join(_source_card(s) for s in sources)
    # "Kartverket" and "Kartverket, Hydrographic Service" are one publisher.
    publishers = len({s["publisher"].split(",")[0].split("(")[0].strip() for s in sources})
    return PAGE.format(
        version=_e(catalogue["version"]),
        n_sources=len(sources),
        n_tools=len(tools),
        n_publishers=publishers,
        cards=cards,
        tools=tool_sections,
        recipes=_recipes(),
        repo=REPO_URL,
    )


def build_site(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    catalogue = build_catalogue()
    (out / "index.html").write_text(render(catalogue), encoding="utf-8")
    (out / "catalogue.json").write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out / "index.html"


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kildeverk</title>
<meta name="description" content="Live Norwegian public data for AI agents and people: an MCP server and JSON API over {n_sources} official sources, with provenance on every result.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%23184e77'/><path d='M9 7v18M9 16l10-9M12 13l9 12' stroke='white' stroke-width='3' fill='none' stroke-linecap='round'/></svg>">
<style>
:root {{
  --bg: #f7f6f2; --panel: #ffffff; --ink: #1d232b; --muted: #5d6673; --line: #e2e0d8;
  --accent: #184e77; --accent-ink: #ffffff; --warn: #8a5a00; --warn-bg: #fff4dc;
  --code-bg: #f0eee7; --ok: #1e6b3a; --err: #9b2c2c;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #12161b; --panel: #1a1f26; --ink: #e6e9ee; --muted: #9aa4b1; --line: #2a313a;
    --accent: #6fb1e3; --accent-ink: #0d1116; --warn: #f0c36b; --warn-bg: #3a2f17;
    --code-bg: #222831; --ok: #7bd39a; --err: #f19a9a;
  }}
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
a {{ color: var(--accent); }}
code, pre, textarea {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .88em; }}
code {{ background: var(--code-bg); padding: .1em .35em; border-radius: 4px; }}
.wrap {{ max-width: 1080px; margin: 0 auto; padding: 0 16px; }}
nav.top {{ display: flex; gap: 18px; align-items: center; padding: 18px 0; flex-wrap: wrap; }}
nav.top .brand {{ font-weight: 700; font-size: 1.1rem; color: var(--ink); text-decoration: none; margin-right: auto; }}
nav.top a {{ text-decoration: none; }}
.hero {{ padding: 40px 0 28px; }}
.hero h1 {{ font-size: clamp(2rem, 5vw, 3.1rem); line-height: 1.1; margin: 0 0 14px; letter-spacing: -0.02em; }}
.hero p.lead {{ font-size: 1.2rem; color: var(--muted); max-width: 46rem; margin: 0 0 22px; }}
.stats {{ display: flex; gap: 28px; flex-wrap: wrap; margin: 0 0 8px; }}
.stats div {{ font-size: .95rem; color: var(--muted); }}
.stats b {{ display: block; font-size: 1.7rem; color: var(--ink); }}
section {{ padding: 26px 0; }}
h2 {{ font-size: 1.6rem; margin: 0 0 6px; letter-spacing: -0.01em; }}
h2 + p {{ color: var(--muted); margin-top: 0; max-width: 46rem; }}
.connect {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
.panel, .card, .tool {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px; min-width: 0; }}
.panel h3 {{ margin: 0 0 8px; font-size: 1.05rem; }}
pre {{ background: var(--code-bg); padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0 0; }}
.copyline {{ display: flex; gap: 8px; align-items: center; }}
.copyline code {{ flex: 1; padding: 8px 10px; overflow-x: auto; white-space: nowrap; }}
button {{ font: inherit; border: 0; border-radius: 7px; padding: 7px 14px; cursor: pointer;
  background: var(--accent); color: var(--accent-ink); font-weight: 600; }}
button.ghost {{ background: transparent; color: var(--accent); border: 1px solid var(--line); }}
.promises {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 16px; }}
.promises h3 {{ margin: 0 0 4px; font-size: 1rem; }}
.promises p {{ margin: 0; color: var(--muted); font-size: .95rem; }}
.recipes {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
.recipe h3 {{ margin: 0 0 8px; font-size: 1.05rem; }}
.recipe p {{ margin: 0 0 8px; }}
.recipe pre {{ white-space: pre-wrap; word-break: break-word; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 16px; }}
.card header h3 {{ margin: 0; font-size: 1.1rem; }}
.card header p {{ margin: 2px 0 0; font-size: .9rem; }}
.muted {{ color: var(--muted); }}
.small {{ font-size: .85rem; }}
.badges {{ margin: 10px 0 4px; display: flex; gap: 6px; flex-wrap: wrap; }}
.badge {{ font-size: .78rem; font-weight: 600; padding: 2px 8px; border-radius: 99px; border: 1px solid var(--line); text-decoration: none; color: var(--ink); }}
.badge.warn {{ background: var(--warn-bg); color: var(--warn); border-color: transparent; }}
.covers {{ padding-left: 18px; margin: 8px 0; font-size: .93rem; }}
.covers li {{ margin: 3px 0; }}
.tools {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }}
.tool-link {{ text-decoration: none; }}
details summary {{ cursor: pointer; color: var(--accent); font-size: .92rem; }}
details ul {{ font-size: .9rem; padding-left: 18px; }}
.links {{ margin: 10px 0 0; }}
h3.group {{ margin: 26px 0 10px; font-size: 1.15rem; }}
.tool {{ margin: 0 0 12px; }}
.tool header h3 {{ margin: 0; font-size: 1.05rem; }}
.tool header p {{ margin: 2px 0 0; font-size: .88rem; }}
.method {{ font-weight: 700; font-size: .78rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: .87rem; margin-top: 8px; display: block; overflow-x: auto; }}
td {{ border-top: 1px solid var(--line); padding: 6px 8px 6px 0; vertical-align: top; }}
.try {{ margin-top: 12px; }}
.try textarea {{ width: 100%; min-height: 4.5em; resize: vertical; background: var(--code-bg); color: var(--ink);
  border: 1px solid var(--line); border-radius: 8px; padding: 10px; }}
.try .actions {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
.bib {{ max-height: 300px; overflow: auto; }}
.out {{ max-height: 420px; overflow: auto; }}
.out.error {{ outline: 2px solid var(--err); }}
footer {{ border-top: 1px solid var(--line); margin-top: 30px; padding: 22px 0 40px; color: var(--muted); font-size: .9rem; }}
@media (max-width: 600px) {{ .stats {{ gap: 18px; }} nav.top {{ gap: 12px; }} }}
</style>
</head>
<body>
<div class="wrap">
  <nav class="top">
    <a class="brand" href="#">Kildeverk</a>
    <a href="#connect">Connect</a>
    <a href="#recipes">Recipes</a>
    <a href="#sources">Sources</a>
    <a href="#tools">Tools</a>
    <a href="/docs">API docs</a>
    <a href="{repo}">GitHub</a>
  </nav>

  <header class="hero">
    <h1>Live Norwegian public data,<br>for agents and people.</h1>
    <p class="lead">An MCP server and a JSON API over official Norwegian sources: statistics,
    companies, weather, water, transport, maps, money, parliament and more. Every answer says
    exactly where it came from and under which licence.</p>
    <div class="stats">
      <div><b>{n_sources}</b>sources</div>
      <div><b>{n_publishers}</b>publishers</div>
      <div><b>{n_tools}</b>tools</div>
    </div>
  </header>

  <section id="connect">
    <h2>Connect</h2>
    <p>Point an MCP client at this server, call the JSON API, or run it yourself. No account and no key.</p>
    <div class="connect">
      <div class="panel">
        <h3>MCP (streamable HTTP)</h3>
        <div class="copyline"><code id="mcp-url">/mcp</code><button type="button" class="ghost" data-copy="mcp-url">Copy</button></div>
        <p class="muted small">Add it as a remote MCP server in Claude, ChatGPT, Cursor or any other client.</p>
      </div>
      <div class="panel">
        <h3>JSON API</h3>
        <pre><code id="curl">curl "/v1/weather/forecast?lat=59.91&amp;lon=10.75&amp;hours=3"</code></pre>
        <p class="muted small">Every tool is also a URL. <a href="/docs">OpenAPI docs</a>.</p>
      </div>
      <div class="panel">
        <h3>Locally, over stdio</h3>
<pre><code>{{"mcpServers": {{"kildeverk": {{
  "command": "uvx",
  "args": ["--from", "git+{repo}",
           "kildeverk", "serve"]}}}}}}</code></pre>
        <p class="muted small">Your own upstream budget and cache. MIT licensed.</p>
      </div>
    </div>
  </section>

  <section>
    <h2>What every answer carries</h2>
    <div class="promises">
      <div class="panel"><h3>Provenance</h3><p>The publisher, the licence, the exact upstream URL, when it was retrieved, and a citation line.</p></div>
      <div class="panel"><h3>Errors an agent can act on</h3><p>A code, a plain explanation, whether retrying helps and when, and often the next call to make.</p></div>
      <div class="panel"><h3>Regions that line up</h3><p>Municipality and county codes translated across the 2020 and 2024 reforms, so old and new data can be compared.</p></div>
      <div class="panel"><h3>Polite to publishers</h3><p>A budget below each published limit, caching, shared in-flight calls and conditional requests.</p></div>
    </div>
  </section>

{recipes}

  <section id="sources">
    <h2>Sources</h2>
    <p>Each source names its licence as the publisher states it. Some need a free key on the deployment; without one, their tools answer <code>NOT_CONFIGURED</code>.</p>
    <div class="cards">{cards}
    </div>
  </section>

  <section id="tools">
    <h2>Tools</h2>
    <p>The same {n_tools} tools over MCP and HTTP. Edit an example and press <em>Try it</em> to call this deployment.</p>
    {tools}
  </section>

  <footer>
    <p>Kildeverk {version} · a personal, non-commercial project · <a href="{repo}">source on GitHub</a> (MIT).
    Not affiliated with any of the publishers. The data belongs to them and comes under their licences, which every result states.</p>
  </footer>
</div>
<script>
(function () {{
  var origin = location.origin;
  var mcp = document.getElementById("mcp-url");
  if (mcp && origin.indexOf("http") === 0) mcp.textContent = origin + "/mcp";
  var curl = document.getElementById("curl");
  if (curl && origin.indexOf("http") === 0) curl.textContent = curl.textContent.replace('"/v1', '"' + origin + "/v1");

  document.querySelectorAll("[data-copy]").forEach(function (b) {{
    b.addEventListener("click", function () {{
      var text = document.getElementById(b.dataset.copy).textContent;
      navigator.clipboard.writeText(text).then(function () {{
        b.textContent = "Copied"; setTimeout(function () {{ b.textContent = "Copy"; }}, 1500);
      }});
    }});
  }});

  // The URL and body a tool call becomes over HTTP: path parameters filled in, then a JSON
  // body for POST or a query string for GET (lists as repeated parameters).
  function target(method, path, args) {{
    var rest = Object.assign({{}}, args);
    path = path.replace(/\\{{(\\w+)\\}}/g, function (_, name) {{
      var value = rest[name]; delete rest[name]; return encodeURIComponent(value);
    }});
    if (method === "POST") return {{ url: path, body: JSON.stringify(rest) }};
    var query = new URLSearchParams();
    Object.keys(rest).forEach(function (key) {{
      var value = rest[key];
      if (Array.isArray(value)) value.forEach(function (v) {{ query.append(key, v); }});
      else if (value !== null && typeof value === "object") query.append(key, JSON.stringify(value));
      else query.append(key, value);
    }});
    var qs = query.toString();
    return {{ url: path + (qs ? "?" + qs : ""), body: null }};
  }}

  function request(method, path, args) {{
    var t = target(method, path, args);
    if (t.body !== null) {{
      return fetch(t.url, {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: t.body }});
    }}
    return fetch(t.url);
  }}

  function shellQuote(text) {{ return "'" + text.replace(/'/g, "'\\''") + "'"; }}

  function asCurl(method, path, args) {{
    var t = target(method, path, args);
    var base = origin.indexOf("http") === 0 ? origin : "http://127.0.0.1:8000";
    if (t.body !== null) {{
      return "curl -X POST " + shellQuote(base + t.url) + " -H 'Content-Type: application/json' -d " + shellQuote(t.body);
    }}
    return "curl " + shellQuote(base + t.url);
  }}

  function asMcp(tool, args) {{
    return JSON.stringify({{ jsonrpc: "2.0", id: 1, method: "tools/call", params: {{ name: tool, arguments: args }} }}, null, 2);
  }}

  function flash(button, text) {{
    var label = button.textContent; button.textContent = text;
    setTimeout(function () {{ button.textContent = label; }}, 1500);
  }}

  document.querySelectorAll(".try").forEach(function (box) {{
    var area = box.querySelector("textarea"), out = box.querySelector(".out"), button = box.querySelector(".run");
    function args() {{
      try {{ return JSON.parse(area.value || "{{}}"); }}
      catch (e) {{ out.hidden = false; out.className = "out error"; out.textContent = "Arguments are not valid JSON: " + e.message; return null; }}
    }}
    box.querySelector(".copy-curl").addEventListener("click", function (e) {{
      var a = args(); if (a === null) return;
      navigator.clipboard.writeText(asCurl(area.dataset.method, area.dataset.path, a)).then(function () {{ flash(e.target, "Copied"); }});
    }});
    // After a result with provenance: turn it into BibTeX with cite_sources, on this server.
    var last = null, citeButton = box.querySelector(".cite"), bib = box.querySelector(".bib");
    citeButton.addEventListener("click", function () {{
      if (!last) return;
      citeButton.disabled = true;
      fetch("/v1/cite", {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify({{ provenance: last, style: "bibtex" }}) }})
        .then(function (r) {{ return r.json(); }})
        .then(function (body) {{
          bib.hidden = false;
          bib.textContent = body.data ? body.data.bibtex : JSON.stringify(body, null, 2);
        }})
        .finally(function () {{ citeButton.disabled = false; }});
    }});
    box.querySelector(".copy-mcp").addEventListener("click", function (e) {{
      var a = args(); if (a === null) return;
      navigator.clipboard.writeText(asMcp(area.dataset.tool, a)).then(function () {{ flash(e.target, "Copied"); }});
    }});
    button.addEventListener("click", function () {{
      var args;
      try {{ args = JSON.parse(area.value || "{{}}"); }}
      catch (e) {{ out.hidden = false; out.className = "out error"; out.textContent = "Arguments are not valid JSON: " + e.message; return; }}
      button.disabled = true; button.textContent = "Calling…";
      request(area.dataset.method, area.dataset.path, args)
        .then(function (r) {{ return r.json().then(function (body) {{ return [r.status, body]; }}); }})
        .then(function (res) {{
          out.hidden = false;
          out.className = res[0] >= 400 ? "out error" : "out";
          last = res[0] < 400 && res[1].provenance && res[1].provenance.length ? res[1].provenance : null;
          citeButton.hidden = !last;
          bib.hidden = true;
          var text = JSON.stringify(res[1], null, 2);
          out.textContent = text.length > 20000 ? text.slice(0, 20000) + "\\n… (cut here; the full result is longer)" : text;
        }})
        .catch(function (e) {{ out.hidden = false; out.className = "out error"; out.textContent = String(e); }})
        .finally(function () {{ button.disabled = false; button.textContent = "Try it"; }});
    }});
  }});
}})();
</script>
</body>
</html>
"""
