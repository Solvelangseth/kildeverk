"""Every source and every tool the service offers. Nothing is registered anywhere else."""

from __future__ import annotations

from kildeverk.core.source import SourceSpec
from kildeverk.sources.brreg.spec import SPEC as BRREG
from kildeverk.sources.entur.spec import GEOCODER as ENTUR_GEOCODER
from kildeverk.sources.entur.spec import JOURNEY_PLANNER as ENTUR_JOURNEY_PLANNER
from kildeverk.sources.met.spec import FROST as MET_FROST
from kildeverk.sources.met.spec import LOCATIONFORECAST as MET_LOCATIONFORECAST
from kildeverk.sources.nve_hydapi.spec import SPEC as NVE_HYDAPI
from kildeverk.sources.ssb_klass.spec import SPEC as SSB_KLASS
from kildeverk.sources.ssb_statbank.spec import SPEC as SSB_STATBANK

SOURCES: tuple[SourceSpec, ...] = (
    SSB_STATBANK,
    SSB_KLASS,
    BRREG,
    MET_LOCATIONFORECAST,
    MET_FROST,
    NVE_HYDAPI,
    ENTUR_GEOCODER,
    ENTUR_JOURNEY_PLANNER,
)


def operations():
    # Imported late: handlers need Context, and Context needs SOURCES.
    from kildeverk.sources import meta
    from kildeverk.sources.brreg.ops import OPERATIONS as BRREG_OPS
    from kildeverk.sources.entur.ops import OPERATIONS as ENTUR_OPS
    from kildeverk.sources.met.ops import OPERATIONS as MET_OPS
    from kildeverk.sources.nve_hydapi.ops import OPERATIONS as NVE_OPS
    from kildeverk.sources.ssb_klass.ops import OPERATIONS as SSB_KLASS_OPS
    from kildeverk.sources.ssb_statbank.ops import OPERATIONS as SSB_STATBANK_OPS

    return (
        *SSB_STATBANK_OPS,
        *SSB_KLASS_OPS,
        *BRREG_OPS,
        *MET_OPS,
        *NVE_OPS,
        *ENTUR_OPS,
        *meta.OPERATIONS,
    )
