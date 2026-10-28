"""Ask a model each question with only Kildeverk's tools, and score what it submits.

    uv run --group eval python -m eval.run --arms tools,notools --out eval/runs/run.jsonl
    uv run --group eval python -m eval.run --only s01,r03 --arms tools

Arms:
- `tools`: every Kildeverk tool, run in-process through the registry, plus `submit_answer`.
- `notools`: only `submit_answer`; the model answers from memory. This is the baseline.

Every run costs model tokens; the summary prints the token totals. Rebuild truth first
(`python -m eval.build_truth`) when questions marked `moves` are included.
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
from kildeverk.context import Context, build_context
from kildeverk.core.errors import ToolError
from kildeverk.settings import Settings
from kildeverk.sources.registry import operations

MODEL = "claude-opus-5-5"
MAX_TURNS = 20
MAX_RESULT_CHARS = 40_000
TRUTH = Path(__file__).parent / "truth.json"

SYSTEM = (
    "You answer questions about Norway with official public data. {tools_line} "
    "When you have the answer, call submit_answer with it: a number without units or "
    "thousands separators for numeric questions, otherwise the name or code asked for. "
    "Always finish by calling submit_answer, once."
)
TOOLS_LINE = (
    "Use the tools to look the answer up; do not answer from memory. Each result says where "
    "its data came from."
)
NOTOOLS_LINE = "You have no data tools: answer from your own knowledge as precisely as you can."

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
    tools = []
    if arm == "tools":
        tools = [
            {"name": op.name, "description": op.description, "input_schema": op.input_schema()}
            for op in operations()
        ]
    # The tool list is identical on every request, so it is cached once per run: the
    # breakpoint on the last definition covers all of them.
    return [*tools, {**SUBMIT, "cache_control": {"type": "ephemeral"}}]


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
    system = SYSTEM.format(tools_line=TOOLS_LINE if arm == "tools" else NOTOOLS_LINE)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question.question}]
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    calls: list[dict[str, Any]] = []
    submitted, stop, started = None, None, time.monotonic()

    for _turn in range(MAX_TURNS):
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
        stop = response.stop_reason
        if stop == "refusal":
            break
        # The whole content goes back, thinking blocks included, unchanged.
        messages.append({"role": "assistant", "content": response.content})

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
        "tools_called": [c["tool"] for c in calls],
        "tool_errors": sum(c["error"] for c in calls),
        "reference_tool_used": question.tool in {c["tool"] for c in calls},
        "usage": usage,
        "seconds": round(time.monotonic() - started, 1),
    }


def summarise(rows: list[dict[str, Any]]) -> str:
    lines = []
    for arm in sorted({r["arm"] for r in rows}):
        mine = [r for r in rows if r["arm"] == arm]
        right = sum(r["correct"] for r in mine)
        tokens = {
            k: sum(r["usage"][k] for r in mine)
            for k in ("input", "output", "cache_read", "cache_write")
        }
        line = f"{arm}: {right}/{len(mine)} correct"
        if arm == "tools":
            calls = sum(len(r["tools_called"]) for r in mine)
            ref = sum(r["reference_tool_used"] for r in mine)
            line += f", {calls / len(mine):.1f} tool calls a question, reference tool used in {ref}/{len(mine)}"
        lines.append(line + f"; tokens {tokens}")
        for cat in sorted({r["category"] for r in mine}):
            c = [r for r in mine if r["category"] == cat]
            lines.append(f"  {cat}: {sum(r['correct'] for r in c)}/{len(c)}")
    return "\n".join(lines)


def _append(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--arms", default="tools", help="Comma-separated: tools, notools.")
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
                print(f"{mark} {arm:7} {q.id} {row['submitted']!r} (truth {row['truth']!r})")
    finally:
        await ctx.aclose()
    print(summarise(rows))


if __name__ == "__main__":
    asyncio.run(main())
