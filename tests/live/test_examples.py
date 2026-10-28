"""Every tool's own examples, called live: the exact calls the docs and website advertise.

uv run pytest -m live tests/live/test_examples.py
"""

from __future__ import annotations

import pytest

from kildeverk.context import build_context
from kildeverk.core.cache import ResponseCache
from kildeverk.core.errors import ToolError
from kildeverk.settings import Settings
from kildeverk.sources.registry import SOURCES, operations

pytestmark = pytest.mark.live
NEEDS = {spec.id: spec.requires_env for spec in SOURCES}
CASES = [
    pytest.param(op, example, id=f"{op.name}[{n}]")
    for op in operations()
    for n, example in enumerate(op.examples)
]


@pytest.fixture
async def live():
    # Generous waits, so a busy upstream budget slows the run rather than failing it.
    ctx = build_context(Settings(_env_file=None, max_wait_s=90), cache=ResponseCache(":memory:"))
    yield ctx
    await ctx.aclose()


@pytest.mark.parametrize(("op", "example"), CASES)
async def test_example_runs(live, op, example):
    missing = [env for sid in op.source_ids for env in NEEDS.get(sid, []) if not _set(live, env)]
    if missing:
        pytest.skip(f"needs {', '.join(missing)}")
    try:
        result = await op.invoke(live, example)
    except ToolError as exc:
        pytest.fail(f"{op.name} {example} -> {exc.body.code}: {exc.body.message}")
    assert "data" in result


def _set(ctx, env: str) -> bool:
    field = env.removeprefix("KILDEVERK_").lower()
    return bool(getattr(ctx.settings, field, ""))
