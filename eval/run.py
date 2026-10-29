"""Ask a model each question three ways, and score what it submits.

    uv run --group eval python -m eval.run --arms tools,web,notools --out eval/runs/run.jsonl
    uv run --group eval python -m eval.run --only s01,r03 --arms tools,web

Arms:
- `tools`: every Kildeverk tool, run in-process through the registry, plus `submit_answer`.
- `web`: Anthropic's web search and web fetch tools, plus `submit_answer`: the model finds the
  answer on the open web itself. This is the arm Kildeverk has to beat.
- `notools`: only `submit_answer`; the model answers from memory. The floor.

Each row records the answer, whether it is right, the tokens by kind, web searches, wall time
and the cost at list prices, so the arms can be compared on accuracy and on what it took to get
there. Every run costs model tokens (and $10 per 1,000 web searches); the summary prints the
totals. Rebuild truth first (`python -m eval.build_truth`) when questions marked `moves` are
included.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import anthropic

from eval.questions import QUESTIONS, Question
from eval.score import correct
from kildeverk.adapters.mcp import _lean
from kildeverk.context import Context, build_context
from kildeverk.core.errors import ToolError
from kildeverk.settings import Settings
from kildeverk.sources.registry import operations

MODEL = "claude-opus-5-5"
MAX_TURNS = 20
MAX_RESULT_CHARS = 40_000
TRUTH = Path(__file__).parent / "truth.json"

# List prices in USD per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing
# (read 2026-10-29): base input, 5-minute cache writes, cache hits, output.
PRICES = {
    "claude-opus-5-5": {"input": 4.0, "cache_write": 5.0, "cache_read": 0.20, "output": 20.0},
    "claude-sonnet-5-5": {"input": 2.0, "cache_write": 2.5, "cache_read": 0.10, "output": 10.0},
}
WEB_SEARCH_USD = 10.0 / 1000  # web fetch has no charge beyond its tokens

SYSTEM = (
    "You answer questions about Norway with official public data. {tools_line} "
    "When you have the answer, call submit_answer with it: a number without units or "
    "thousands separators for numeric questions, otherwise the name or code asked for. "
    "Always finish by calling submit_answer, once."
)
LINES = {
    "tools": (
        "Use the tools to look the answer up; do not answer from memory. Each result says where "
        "its data came from."
    ),
    "web": (
        "Use web search and web fetch to find the answer in official sources (Statistics Norway, "
        "MET Norway, Kartverket, the registers and so on); do not answer from memory."
    ),
    "notools": "You have no data tools: answer from your own knowledge as precisely as you can.",
}
WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]

SUBMIT = {
    "name": "submit_answer",
    "description": "Submit your final answer. Call it exactly once, when you are done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "The answer alone, e.g. '68' or 'Karmøy'."},
            "explanation": {"type": "string", "description": "One sentence on how you found it."},
        },
        "required": ["answer", "explanation"],
        "additionalProperties": False,
    },
}


def tool_definitions(arm: str) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    if arm == "tools":
        # The same lean schemas an MCP client receives.
        tools = [
            {
                "name": op.name,
                "description": op.description,
                "input_schema": _lean(op.input_schema()),
            }
            for op in operations()
        ]
    elif arm == "web":
        tools = list(WEB_TOOLS)
    # The tool list is identical on every request, so it is cached once per run: the
    # breakpoint on the last definition covers all of them.
    return [*tools, {**SUBMIT, "cache_control": {"type": "ephemeral"}}]


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    tokens = sum(usage[kind] * price[kind] for kind in price) / 1_000_000
    return round(tokens + usage.get("web_searches", 0) * WEB_SEARCH_USD, 4)


async def call_tool(ctx: Context, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    ops = {op.name: op for op in operations()}
    if name not in ops:
        return json.dumps({"error": f"no tool named {name}"}), True
    try:
        result = await ops[name].invoke(ctx, arguments)
        is_error = False
    except ToolError as exc:
        result, is_error = exc.envelope(), True
    text = json.dumps(result, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        # Say so rather than cut silently: the model can narrow its call.
        text = text[:MAX_RESULT_CHARS] + '..." [result cut at 40,000 characters; ask for less]'
    return text, is_error


async def ask(
    client: anthropic.AsyncAnthropic,
    ctx: Context,
    question: Question,
    arm: str,
    *,
    model: str,
    effort: str,
) -> dict[str, Any]:
    tools = tool_definitions(arm)
    system = SYSTEM.format(tools_line=LINES[arm])
    messages: list[dict[str, Any]] = [{"role": "user", "content": question.question}]
    usage = {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write": 0,
        "web_searches": 0,
        "web_fetches": 0,
    }
    calls: list[dict[str, Any]] = []
    submitted, stop, turns, started = None, None, 0, time.monotonic()

    for _turn in range(MAX_TURNS):
        turns += 1
        response = await client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": effort},
            # On a policy decline the request is re-run on a fallback model in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        u = response.usage
        usage["input"] += u.input_tokens
        usage["output"] += u.output_tokens
        usage["cache_read"] += u.cache_read_input_tokens or 0
        usage["cache_write"] += u.cache_creation_input_tokens or 0
        server = getattr(u, "server_tool_use", None)
        if server is not None:
            usage["web_searches"] += getattr(server, "web_search_requests", 0) or 0
            usage["web_fetches"] += getattr(server, "web_fetch_requests", 0) or 0
        stop = response.stop_reason
        if stop == "refusal":
            break
        # The whole content goes back, thinking and server-tool blocks included, unchanged.
        messages.append({"role": "assistant", "content": response.content})
        # Searches and fetches count whether or not the turn paused after them.
        calls += [
            {"tool": b.name, "arguments": b.input, "error": False}
            for b in response.content
            if b.type == "server_tool_use"
        ]
        if stop == "pause_turn":
            # A long server-tool turn paused; sending the conversation back resumes it.
            continue

        uses = [b for b in response.content if b.type == "tool_use"]
        if not uses:
            messages.append({"role": "user", "content": "Call submit_answer with your answer now."})
            continue
        results = []
        for use in uses:
            if use.name == "submit_answer":
                submitted = (use.input or {}).get("answer")
                results.append(
                    {"type": "tool_result", "tool_use_id": use.id, "content": "Received."}
                )
                continue
            text, is_error = await call_tool(ctx, use.name, use.input or {})
            calls.append({"tool": use.name, "arguments": use.input, "error": is_error})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use.id,
                    "content": text,
                    "is_error": is_error,
                }
            )
        # All results for one assistant turn go back in a single user message.
        messages.append({"role": "user", "content": results})
        if submitted is not None:
            break

    return {
        "id": question.id,
        "arm": arm,
        "model": model,
        "effort": effort,
        "category": question.category,
        "submitted": submitted,
        "stop_reason": stop,
        "turns": turns,
        "tools_called": [c["tool"] for c in calls],
        "tool_errors": sum(c["error"] for c in calls),
        "reference_tool_used": question.tool in {c["tool"] for c in calls},
        "usage": usage,
        "cost_usd": cost_usd(model, usage),
        "seconds": round(time.monotonic() - started, 1),
    }


def summarise(rows: list[dict[str, Any]]) -> str:
    lines = [
        (
            f"{'arm':8} {'correct':>9} {'tokens/q':>9} {'output/q':>9} {'searches':>9} "
            f"{'calls/q':>8} {'sec/q':>7} {'USD/q':>8} {'USD':>8}"
        )
    ]
    for arm in ("tools", "web", "notools"):
        mine = [r for r in rows if r["arm"] == arm]
        if not mine:
            continue
        n = len(mine)
        right = sum(r["correct"] for r in mine)
        tokens = sum(
            r["usage"]["input"] + r["usage"]["cache_read"] + r["usage"]["cache_write"] for r in mine
        )
        output = sum(r["usage"]["output"] for r in mine)
        searches = sum(r["usage"].get("web_searches", 0) for r in mine)
        calls = sum(len(r["tools_called"]) for r in mine)
        seconds = sum(r.get("seconds", 0) for r in mine)
        costs = [r.get("cost_usd") for r in mine]
        total = (
            sum(c for c in costs if c is not None) if all(c is not None for c in costs) else None
        )
        lines.append(
            f"{arm:8} {f'{right}/{n}':>9} {tokens // n:>9,} {output // n:>9,} {searches:>9} "
            f"{calls / n:>8.1f} {seconds / n:>7.1f} "
            + (f"{total / n:>8.3f} {total:>8.2f}" if total is not None else f"{'?':>8} {'?':>8}")
        )
    lines.append("By category (correct):")
    categories = sorted({r["category"] for r in rows})
    arms = [a for a in ("tools", "web", "notools") if any(r["arm"] == a for r in rows)]
    for category in categories:
        parts = []
        for arm in arms:
            mine = [r for r in rows if r["arm"] == arm and r["category"] == category]
            if mine:
                parts.append(f"{arm} {sum(r['correct'] for r in mine)}/{len(mine)}")
        lines.append(f"  {category:10} " + ", ".join(parts))
    return "\n".join(lines)


def _append(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--arms", default="tools", help="Comma-separated: tools, web, notools.")
    parser.add_argument("--only", default="", help="Comma-separated question ids.")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument(
        "--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"]
    )
    parser.add_argument("--out", default="eval/runs/run.jsonl")
    args = parser.parse_args()

    truth = json.loads(TRUTH.read_text())
    wanted = set(filter(None, args.only.split(",")))
    questions = [q for q in QUESTIONS if not wanted or q.id in wanted]
    client = anthropic.AsyncAnthropic()
    ctx = build_context(Settings(max_wait_s=90))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for arm in args.arms.split(","):
            for q in questions:
                row = await ask(client, ctx, q, arm, model=args.model, effort=args.effort)
                row["truth"] = truth[q.id]["answer"]
                row["correct"] = row["submitted"] is not None and correct(
                    q, row["submitted"], row["truth"]
                )
                rows.append(row)
                # Each row is written as it finishes, so a stopped run keeps what it paid for.
                line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
                await asyncio.to_thread(_append, out, line)
                mark = "ok " if row["correct"] else "MISS"
                print(
                    f"{mark} {arm:7} {q.id} {row['submitted']!r} (truth {row['truth']!r}) "
                    f"{row['seconds']}s ${row['cost_usd']}"
                )
    finally:
        await ctx.aclose()
    print(summarise(rows))


if __name__ == "__main__":
    asyncio.run(main())
