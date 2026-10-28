"""The eval runner's loop, against a scripted fake model: no API calls, no cost."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

pytest.importorskip("anthropic")

from eval.questions import QUESTIONS
from eval.run import ask, summarise, tool_definitions


def _usage():
    return NS(
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=50,
        cache_creation_input_tokens=0,
    )


def _reply(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop, usage=_usage())


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
    assert row["usage"] == {"input": 200, "output": 40, "cache_read": 100, "cache_write": 0}
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
    assert "tools: 1/1 correct" in text and "notools: 0/1 correct" in text
