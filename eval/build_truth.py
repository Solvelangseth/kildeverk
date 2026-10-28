"""Run each question's reference call live and store the answers in eval/truth.json.

    uv run python eval/build_truth.py

Needs the Frost and HydAPI keys for the questions that use them. Questions marked `moves`
follow the latest figures, so rebuild truth right before a run.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from eval.questions import QUESTIONS
from kildeverk.context import build_context
from kildeverk.core.errors import ToolError
from kildeverk.settings import Settings
from kildeverk.sources.registry import operations

OUT = Path(__file__).parent / "truth.json"


async def main() -> None:
    ops = {op.name: op for op in operations()}
    ctx = build_context(Settings(max_wait_s=90))
    truth, failed = {}, []
    for q in QUESTIONS:
        try:
            result = await ops[q.tool].invoke(ctx, q.arguments)
            answer = q.extract(result)
        except (ToolError, KeyError, StopIteration, IndexError, TypeError) as exc:
            failed.append(q.id)
            print(f"{q.id} FAILED: {exc}")
            continue
        truth[q.id] = {
            "answer": answer,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "citations": sorted({p["citation"] for p in result["provenance"]})[:3],
        }
        print(f"{q.id} {q.tool}: {answer!r}")
    await ctx.aclose()
    OUT.write_text(json.dumps(truth, ensure_ascii=False, indent=1) + "\n")
    print(
        f"wrote {len(truth)} answers to {OUT}"
        + (f"; failed: {', '.join(failed)}" if failed else "")
    )


if __name__ == "__main__":
    asyncio.run(main())
