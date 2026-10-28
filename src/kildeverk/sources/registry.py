"""Every source and every tool the service offers. Nothing is registered anywhere else."""

from __future__ import annotations

from kildeverk.core.source import SourceSpec
from kildeverk.sources.ssb_klass.spec import SPEC as SSB_KLASS
from kildeverk.sources.ssb_statbank.spec import SPEC as SSB_STATBANK

SOURCES: tuple[SourceSpec, ...] = (SSB_STATBANK, SSB_KLASS)


def operations():
    # Imported late: handlers need Context, and Context needs SOURCES.
    from kildeverk.sources import meta
    from kildeverk.sources.ssb_klass.ops import OPERATIONS as SSB_KLASS_OPS
    from kildeverk.sources.ssb_statbank.ops import OPERATIONS as SSB_STATBANK_OPS

    return (*SSB_STATBANK_OPS, *SSB_KLASS_OPS, *meta.OPERATIONS)
