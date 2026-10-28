"""Region tools against recorded Klass history, using real reform cases.

Values are SSB population figures (table 07459) for the regions involved.
"""

from __future__ import annotations

import pytest

from kildeverk.core.errors import ToolError
from kildeverk.sources.registry import operations

OPS = {op.name: op for op in operations()}


async def call(ctx, tool, **arguments):
    return await OPS[tool].invoke(ctx, arguments)


async def harmonise(ctx, rows, *, target="2024", level="municipality", measure="additive"):
    result = await call(
        ctx,
        "regions_harmonise",
        level=level,
        target=target,
        measure=measure,
        rows=[{"region": r, "period": p, "value": v} for r, p, v in rows],
    )
    data = result["data"]
    converted = {(r["region"], r["period"]): r for r in data["rows"]}
    return data, converted, result


# --- list, resolve, changes ---------------------------------------------------


async def test_list_on_a_past_date_uses_the_codes_of_that_date(ctx):
    data = (await call(ctx, "regions_list", level="municipality", on_date="2019-06-30"))["data"]
    codes = {r["code"] for r in data["regions"]}
    assert "1201" in codes and "4601" not in codes
    assert data["count"] == len(data["regions"]) > 400


async def test_list_counties_today_has_the_2024_counties(ctx):
    codes = {
        r["code"] for r in (await call(ctx, "regions_list", level="county"))["data"]["regions"]
    }
    assert {"31", "32", "33", "39", "40", "55", "56"} <= codes
    assert not {"30", "38", "54"} & codes


async def test_resolve_finds_every_tromso_and_what_each_is_today(ctx):
    result = await call(ctx, "regions_resolve", query="Tromsø", level="municipality")
    matches = result["data"]["matches"]
    assert [m["code"] for m in matches[:3]] == ["5501", "5401", "1902"]
    assert matches[0]["status"] == "current"
    assert all(m["today"] == [{"code": "5501", "name": "Tromsø"}] for m in matches[:3])
    codes_prov, _ = result["provenance"]
    assert codes_prov["licence"]["id"] == "CC-BY-4.0"
    assert codes_prov["request"]["url"].endswith(
        "/classifications/131/codes?from=1960-01-01&to=2100-01-01"
    )


async def test_resolve_flags_a_region_that_was_later_split(ctx):
    matches = (await call(ctx, "regions_resolve", query="Viken"))["data"]["matches"]
    viken = next(m for m in matches if m["code"] == "30")
    assert viken["status"] == "ended" and viken["today_exact"] is False
    assert {r["code"] for r in viken["today"]} == {"31", "32", "33"}


async def test_county_changes_show_the_two_reforms(ctx):
    events = (
        await call(
            ctx, "regions_changes", level="county", from_date="2019-01-01", to_date="2024-12-31"
        )
    )["data"]["events"]
    kinds = {(e["date"], e["kind"], tuple(r["code"] for r in e["after"])) for e in events}
    assert ("2020-01-01", "merge", ("30",)) in kinds
    assert ("2024-01-01", "split", ("31", "32", "33")) in kinds


async def test_changes_for_one_code(ctx):
    events = (
        await call(
            ctx, "regions_changes", level="municipality", from_date="2019-01-01", code="1507"
        )
    )["data"]["events"]
    assert [(e["date"], e["kind"]) for e in events] == [
        ("2020-01-01", "merge"),
        ("2024-01-01", "split"),
    ]
    assert {r["code"] for r in events[1]["after"]} == {"1508", "1580"}


# --- harmonise ----------------------------------------------------------------


async def test_renumbering_is_followed(ctx):
    data, rows, result = await harmonise(ctx, [("1201", "2019", 281190), ("4601", "2023", 289330)])
    assert rows[("4601", "2019")]["value"] == 281190
    assert rows[("4601", "2019")]["method"] == "renumbered"
    assert rows[("4601", "2023")]["method"] == "unchanged"
    assert data["unconverted"] == []
    assert len(result["provenance"]) == 2


async def test_a_merger_is_summed_when_every_piece_is_there(ctx):
    data, rows, _ = await harmonise(
        ctx, [("1508", "2024", 58509), ("1580", "2024", 9357)], target="2020"
    )
    assert rows[("1507", "2024")]["value"] == 58509 + 9357
    assert rows[("1507", "2024")]["sources"] == ["1508", "1580"]
    assert {m["code"]: m["kind"] for m in data["mapping"]} == {"1508": "merged", "1580": "merged"}


async def test_a_merger_with_a_missing_piece_is_refused(ctx):
    data, rows, _ = await harmonise(
        ctx, [("1508", "2024", 58509), ("4601", "2024", 291940)], target="2020"
    )
    assert ("1507", "2024") not in rows and ("4601", "2024") in rows
    [refused] = data["unconverted"]
    assert refused["region"] == "1507" and "1580 Haram" in refused["reason"]


async def test_a_split_is_never_estimated(ctx):
    data, rows, _ = await harmonise(ctx, [("1507", "2023", 67520), ("4601", "2023", 289330)])
    assert list(rows) == [("4601", "2023")]
    [refused] = data["unconverted"]
    assert "was split into 1508 Ålesund, 1580 Haram" in refused["reason"]
    split = next(m for m in data["mapping"] if m["code"] == "1507")
    assert split["kind"] == "split" and split["exact"] is False


async def test_going_back_across_a_merger_is_a_split(ctx):
    # Stavanger kept code 1103 when it absorbed Finnøy and Rennesøy in 2020.
    data, rows, _ = await harmonise(
        ctx, [("1103", "2024", 150000), ("4601", "2024", 291940)], target="2019-01-01"
    )
    assert list(rows) == [("1201", "2024")]
    assert "1103 Stavanger (2020-) was formed from" in data["unconverted"][0]["reason"]


async def test_rates_are_renumbered_but_never_summed(ctx):
    data, rows, _ = await harmonise(
        ctx,
        [("1201", "2019", 1.2), ("1508", "2024", 0.8), ("1580", "2024", 0.4)],
        target="2020",
        measure="non_additive",
    )
    assert rows[("4601", "2019")]["value"] == 1.2
    assert ("1507", "2024") not in rows
    assert any("cannot be combined without weights" in u["reason"] for u in data["unconverted"])


async def test_ssb_placeholder_zeros_and_missing_values_are_dropped(ctx):
    data, rows, _ = await harmonise(
        ctx,
        [
            ("1201", "2020", 0),
            ("4601", "2018", 0),
            ("4601", "2020", 283929),
            ("4601", "2021", None),
        ],
    )
    assert list(rows) == [("4601", "2020")]
    assert data["skipped_placeholders"] == 2 and data["skipped_missing"] == 1


async def test_two_vintages_for_one_period_are_not_double_counted(ctx):
    data, rows, result = await harmonise(
        ctx, [("1201", "2019", 281190), ("4601", "2019", 281190), ("4601", "2023", 289330)]
    )
    assert list(rows) == [("4601", "2023")]
    assert "different border vintages" in data["unconverted"][0]["reason"]
    assert any("back-casts" in note for note in result["notes"])


async def test_a_reused_code_is_read_by_its_period(ctx):
    # 0712 was Skoger until 1964 and Larvik from 2018.
    data, rows, _ = await harmonise(
        ctx, [("0712", "1962", 1000), ("0712", "2019", 46000)], target="latest"
    )
    assert {(m["name"], m["valid"]) for m in data["mapping"]} == {
        ("Skoger", "1960-1963"),
        ("Larvik", "2018-2019"),
    }
    assert rows[("3909", "2019")]["region_name"] == "Larvik"
    # Skoger is one of several pieces of today's Drammen, and the others are not in the input.
    [refused] = data["unconverted"]
    assert refused["region"] == "3301" and "values for those are needed too" in refused["reason"]


async def test_counties_across_both_reforms(ctx):
    _, rows, _ = await harmonise(
        ctx,
        [("31", "2024", 1), ("32", "2024", 2), ("33", "2024", 3), ("30", "2023", 10)],
        level="county",
        target="2020",
    )
    assert rows[("30", "2024")]["value"] == 6 and rows[("30", "2023")]["method"] == "unchanged"


async def test_nothing_convertible_is_an_error_with_a_next_step(ctx):
    with pytest.raises(ToolError) as caught:
        await harmonise(ctx, [("5012", "2019", 900)])
    body = caught.value.envelope()["error"]
    assert body["code"] == "NOT_CONVERTIBLE"
    assert "Snillfjord" in body["message"]
    assert body["next_call"] == {
        "tool": "regions_changes",
        "arguments": {"level": "municipality", "from_date": "2019-01-01"},
    }


async def test_unknown_codes_and_future_targets(ctx):
    data, _, _ = await harmonise(ctx, [("9876", "2019", 1), ("4601", "2023", 2)])
    assert "no municipality code 9876" in data["unconverted"][0]["reason"]
    with pytest.raises(ToolError) as caught:
        await harmonise(ctx, [("4601", "2023", 2)], target="2999-01-01")
    assert caught.value.body.code == "INVALID_ARGUMENT"


async def test_the_history_is_parsed_once(ctx, replay):
    await harmonise(ctx, [("4601", "2023", 2)])
    graph = next(v for k, v in ctx.memo.items() if k[0] == "klass_history")
    await harmonise(ctx, [("4601", "2024", 2)])
    assert next(v for k, v in ctx.memo.items() if k[0] == "klass_history") is graph
