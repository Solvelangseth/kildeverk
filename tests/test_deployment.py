"""What only the public deployment does: per-client limits, health checks, the website."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kildeverk.adapters.limits import ClientBuckets
from kildeverk.app import create_app
from kildeverk.settings import Settings


def test_buckets_refill_over_time():
    now = [0.0]
    buckets = ClientBuckets(per_minute=60, burst=2, clock=lambda: now[0])
    assert buckets.take("a") == 0 and buckets.take("a") == 0
    assert buckets.take("a") == 1.0  # one token a second
    assert buckets.take("b") == 0  # every client has its own bucket
    now[0] += 1.0
    assert buckets.take("a") == 0


def _public(ctx, **settings) -> TestClient:
    return TestClient(
        create_app(Settings(_env_file=None, deployment="public", **settings), context=ctx)
    )


def test_public_deployment_limits_each_client(ctx):
    with _public(ctx, client_limit_per_minute=1, client_limit_burst=2) as http:
        assert http.get("/v1/sources").status_code == 200
        assert http.get("/v1/sources").status_code == 200
        limited = http.get("/v1/sources")
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1
        error = limited.json()["error"]
        assert error["code"] == "RATE_LIMITED" and error["retryable"] is True
        # The website, docs and health check never count.
        assert http.get("/healthz").status_code == 200
        assert http.get("/openapi.json").status_code == 200


def test_trusted_proxy_header_names_the_client(ctx):
    with _public(
        ctx, client_limit_per_minute=1, client_limit_burst=1, client_ip_header="Fly-Client-IP"
    ) as http:
        assert http.get("/v1/sources", headers={"Fly-Client-IP": "203.0.113.1"}).status_code == 200
        assert http.get("/v1/sources", headers={"Fly-Client-IP": "203.0.113.1"}).status_code == 429
        assert http.get("/v1/sources", headers={"Fly-Client-IP": "203.0.113.2"}).status_code == 200


def test_local_deployment_has_no_client_limit(ctx):
    app = create_app(
        Settings(_env_file=None, client_limit_per_minute=1, client_limit_burst=1), context=ctx
    )
    with TestClient(app) as http:
        assert all(http.get("/v1/sources").status_code == 200 for _ in range(3))


def test_site_is_served_at_the_root_when_built(ctx, tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Kildeverk</title>")
    app = create_app(Settings(_env_file=None, site_dir=tmp_path), context=ctx)
    with TestClient(app) as http:
        assert "<title>Kildeverk</title>" in http.get("/").text
        assert http.get("/v1").json()["mcp"] == "/mcp"
        assert http.get("/v1/sources").status_code == 200


def test_root_answers_json_without_a_site(ctx):
    with TestClient(create_app(Settings(_env_file=None), context=ctx)) as http:
        assert http.get("/").json()["api"] == "/v1"


def test_site_lists_every_source_and_tool(tmp_path: Path):
    from kildeverk.site import build_site
    from kildeverk.sources.registry import SOURCES, operations

    html = build_site(tmp_path).read_text()
    assert all(f'id="source-{spec.id}"' in html for spec in SOURCES)
    assert all(f'id="tool-{op.name}"' in html for op in operations())
    assert "<script>" in html and "{" not in html.split("<style>")[0].split("<title>")[0]
    assert (tmp_path / "catalogue.json").exists()
    assert html.count('class="ghost copy-curl"') == len(operations())
    assert 'data-tool="place_overview"' in html
    assert html.count('class="ghost cite" hidden') == len(operations())
    assert 'id="feed-form"' in html
    assert html.count('class="card recipe"') >= 3 and 'id="eksempler"' in html
    assert '<html lang="nb">' in html and "@@" not in html


def test_site_has_norwegian_text_for_every_source_and_tool():
    from kildeverk import site_nb
    from kildeverk.sources.registry import SOURCES, operations

    names = {op.name for op in operations()}
    assert {spec.id for spec in SOURCES} == set(site_nb.SOURCES)
    assert names == set(site_nb.TOOLS)
    themed = [name for _, _, group in site_nb.THEMES for name in group]
    assert sorted(themed) == sorted(names), "each tool belongs to exactly one theme on the site"
    publishers = {spec.publisher for spec in SOURCES}
    assert publishers <= set(site_nb.PUBLISHERS)
