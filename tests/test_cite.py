"""cite_sources: provenance into BibTeX and CSL-JSON, locally."""

from __future__ import annotations

from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


def prov(publisher, url, title="A table & more_100%"):
    return {
        "source_id": "x",
        "source_name": "Some API",
        "publisher": publisher,
        "title": title,
        "licence": {
            "id": "NLOD-2.0",
            "name": "NLOD 2.0",
            "url": "https://data.norge.no/nlod/en/2.0",
        },
        "request": {"method": "GET", "url": url, "body": None},
        "retrieved_at": "2026-10-28T07:02:11Z",
        "cache": {"hit": False, "age_s": 0.0, "stale": False},
        "citation": "c",
    }


async def test_repeated_requests_merge_and_keys_stay_unique(ctx):
    provenance = [
        prov("Statistics Norway (SSB)", "https://a.test/1"),
        prov("Statistics Norway (SSB)", "https://a.test/1"),
        prov("Statistics Norway (SSB)", "https://a.test/2"),
        prov("Brønnøysund Register Centre", "https://b.test/1"),
    ]
    result = await OPS["cite_sources"].invoke(ctx, {"provenance": provenance})
    data = result["data"]
    assert data["references"] == 3
    keys = [entry["id"] for entry in data["csl_json"]]
    assert keys == ["ssb2026", "ssb2026a", "bronnoysund2026"]
    assert data["bibtex"].count("@misc{") == 3


async def test_bibtex_escapes_special_characters(ctx):
    result = await OPS["cite_sources"].invoke(
        ctx,
        {"provenance": [prov("Statistics Norway (SSB)", "https://a.test/1")], "style": "bibtex"},
    )
    bib = result["data"]["bibtex"]
    assert r"title        = {A table \& more\_100\%}," in bib
    assert "author       = {{Statistics Norway (SSB)}}" in bib
    assert result["data"]["csl_json"] is None


async def test_csl_json_is_a_dataset_with_access_date(ctx):
    result = await OPS["cite_sources"].invoke(
        ctx, {"provenance": [prov("Norges Bank", "https://n.test")], "style": "csl_json"}
    )
    [item] = result["data"]["csl_json"]
    assert item["type"] == "dataset" and item["author"] == [{"literal": "Norges Bank"}]
    assert item["accessed"] == {"date-parts": [[2026, 10, 28]]}
    assert result["data"]["bibtex"] is None
