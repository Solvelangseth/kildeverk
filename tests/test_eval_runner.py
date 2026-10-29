"""The eval runner's loop, against a scripted fake model: no API calls, no cost."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

pytest.importorskip("anthropic")

from eval.questions import QUESTIONS
from eval.run import ask, cost_usd, summarise, tool_definitions


def _usage(searches=0):
    return NS(
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=50,
        cache_creation_input_tokens=0,
        server_tool_use=NS(web_search_requests=searches, web_fetch_requests=0),
    )


def _reply(*blocks, stop="tool_use", searches=0):
    return NS(content=list(blocks), stop_reason=stop, usage=_usage(searches))


def _tool(id_, name, **input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    async def create(self, **kwargs):
        # The runner keeps appending to one list; record it as it was at this call.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


def _client(replies):
    messages = FakeMessages(replies)
    return NS(beta=NS(messages=messages)), messages


Q = next(q for q in QUESTIONS if q.id == "r01")  # Bergen's municipality number, via regions_resolve


async def test_tools_arm_calls_a_tool_then_submits(ctx):
    client, messages = _client(
        [
            _reply(
                NS(type="text", text="Looking it up."),
                _tool("t1", "regions_resolve", query="Bergen", level="municipality"),
            ),
            _reply(_tool("t2", "submit_answer", answer="4601", explanation="Klass")),
        ]
    )
    row = await ask(client, ctx, Q, "tools", model="m", effort="low")
    assert row["submitted"] == "4601" and row["tools_called"] == ["regions_resolve"]
    assert row["reference_tool_used"] and row["tool_errors"] == 0
    assert row["usage"] == {
        "input": 200,
        "output": 40,
        "cache_read": 100,
        "cache_write": 0,
        "web_searches": 0,
        "web_fetches": 0,
    }
    assert row["turns"] == 2 and row["cost_usd"] is None  # 'm' has no price
    first = messages.requests[0]
    assert first["output_config"] == {"effort": "low"} and first["fallbacks"] == "default"
    assert first["tools"][-1]["name"] == "submit_answer" and "cache_control" in first["tools"][-1]
    # The tool result went back as one user message after the assistant's whole content.
    second = messages.requests[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-1]["content"][0]["tool_use_id"] == "t1"
    assert '"4601"' in second[-1]["content"][0]["content"]


async def test_a_turn_without_a_tool_call_is_nudged_to_submit(ctx):
    client, messages = _client(
        [
            _reply(NS(type="text", text="Bergen is 4601."), stop="end_turn"),
            _reply(_tool("t1", "submit_answer", answer="4601", explanation="memory")),
        ]
    )
    row = await ask(client, ctx, Q, "notools", model="m", effort="low")
    assert row["submitted"] == "4601"
    assert messages.requests[1]["messages"][-1]["content"].startswith("Call submit_answer")
    assert [t["name"] for t in messages.requests[0]["tools"]] == ["submit_answer"]


async def test_tool_errors_are_returned_as_errors(ctx):
    client, messages = _client(
        [
            _reply(_tool("t1", "regions_resolve", query="", level="municipality")),
            _reply(_tool("t2", "submit_answer", answer="?", explanation="failed")),
        ]
    )
    row = await ask(client, ctx, Q, "tools", model="m", effort="low")
    result = messages.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "INVALID_ARGUMENT" in result["content"]
    assert row["tool_errors"] == 1


def test_tools_arm_offers_every_tool():
    names = [t["name"] for t in tool_definitions("tools")]
    assert "place_overview" in names and names[-1] == "submit_answer"
    assert len(names) == len(set(names))


async def test_web_arm_searches_resumes_a_paused_turn_and_counts_the_cost(ctx):
    client, messages = _client(
        [
            _reply(
                NS(type="server_tool_use", id="s1", name="web_search", input={"query": "x"}),
                stop="pause_turn",
                searches=1,
            ),
            _reply(
                NS(type="server_tool_use", id="s2", name="web_fetch", input={"url": "u"}),
                _tool("t1", "submit_answer", answer="4601", explanation="web"),
                searches=2,
            ),
        ]
    )
    row = await ask(client, ctx, Q, "web", model="claude-opus-5-5", effort="low")
    assert row["submitted"] == "4601" and row["turns"] == 2
    assert row["tools_called"] == ["web_search", "web_fetch"]
    assert row["usage"]["web_searches"] == 3
    # The paused turn went back as the assistant's content, with no user message after it.
    resumed = messages.requests[1]["messages"]
    assert resumed[-1]["role"] == "assistant"
    types = [t.get("type") for t in messages.requests[0]["tools"]]
    assert types[:2] == ["web_search_20260209", "web_fetch_20260209"]
    # 200 input, 40 output, 100 cache reads at Opus 5.5 prices, plus three searches.
    assert row["cost_usd"] == round((200 * 4 + 40 * 20 + 100 * 0.2) / 1e6 + 3 * 0.01, 4)


def test_cost_is_unknown_for_unpriced_models():
    usage = {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0, "web_searches": 0}
    assert cost_usd("some-model", usage) is None


def test_tool_schemas_are_the_lean_ones_clients_get():
    tools = {t["name"]: t for t in tool_definitions("tools")}
    assert "title" not in tools["statistics_get_data"]["input_schema"]


def test_summary_reads_per_arm_and_category():
    rows = [
        {
            "arm": "tools",
            "category": "lookup",
            "correct": True,
            "tools_called": ["a"],
            "reference_tool_used": True,
            "usage": {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0},
        },
        {
            "arm": "notools",
            "category": "lookup",
            "correct": False,
            "tools_called": [],
            "reference_tool_used": False,
            "usage": {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0},
        },
    ]
    text = summarise(rows)
    lines = text.splitlines()
    assert lines[1].startswith("tools") and "1/1" in lines[1]
    assert lines[2].startswith("notools") and "0/1" in lines[2]
    assert "tools 1/1, notools 0/1" in text
