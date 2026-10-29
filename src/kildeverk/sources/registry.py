"""Every source and every tool the service offers. Nothing is registered anywhere else."""

from __future__ import annotations

from kildeverk.core.source import SourceSpec
from kildeverk.sources.avinor.spec import SPEC as AVINOR
from kildeverk.sources.brreg.spec import ACCOUNTS as BRREG_ACCOUNTS
from kildeverk.sources.brreg.spec import SPEC as BRREG
from kildeverk.sources.datanorge.spec import SPEC as DATANORGE
from kildeverk.sources.elhub.spec import SPEC as ELHUB
from kildeverk.sources.entur.spec import GEOCODER as ENTUR_GEOCODER
from kildeverk.sources.entur.spec import JOURNEY_PLANNER as ENTUR_JOURNEY_PLANNER
from kildeverk.sources.kartverket.spec import SPEC as KARTVERKET
from kildeverk.sources.kartverket_sea.spec import SPEC as KARTVERKET_SEA
from kildeverk.sources.met.spec import AIRQUALITY as MET_AIRQUALITY
from kildeverk.sources.met.spec import FROST as MET_FROST
from kildeverk.sources.met.spec import LOCATIONFORECAST as MET_LOCATIONFORECAST
from kildeverk.sources.met.spec import METALERTS as MET_METALERTS
from kildeverk.sources.met.spec import NOWCAST as MET_NOWCAST
from kildeverk.sources.met.spec import OCEANFORECAST as MET_OCEANFORECAST
from kildeverk.sources.norges_bank.spec import SPEC as NORGES_BANK
from kildeverk.sources.nve_hydapi.spec import SPEC as NVE_HYDAPI
from kildeverk.sources.nve_regobs.spec import SPEC as NVE_REGOBS
from kildeverk.sources.nve_reservoirs.spec import SPEC as NVE_RESERVOIRS
from kildeverk.sources.nve_varsom.spec import SPEC as NVE_VARSOM
from kildeverk.sources.ordbokene.spec import SPEC as ORDBOKENE
from kildeverk.sources.ssb_klass.spec import SPEC as SSB_KLASS
from kildeverk.sources.ssb_statbank.spec import SPEC as SSB_STATBANK
from kildeverk.sources.stortinget.spec import SPEC as STORTINGET
from kildeverk.sources.udir_nsr.spec import SPEC as UDIR_NSR
from kildeverk.sources.usgs.spec import SPEC as USGS_EARTHQUAKES
from kildeverk.sources.vegvesen_traffic.spec import SPEC as VEGVESEN_TRAFFIC

SOURCES: tuple[SourceSpec, ...] = (
    SSB_STATBANK,
    SSB_KLASS,
    BRREG,
    BRREG_ACCOUNTS,
    MET_LOCATIONFORECAST,
    MET_FROST,
    MET_METALERTS,
    MET_NOWCAST,
    MET_OCEANFORECAST,
    MET_AIRQUALITY,
    NVE_HYDAPI,
    ENTUR_GEOCODER,
    ENTUR_JOURNEY_PLANNER,
    KARTVERKET,
    NORGES_BANK,
    NVE_VARSOM,
    NVE_REGOBS,
    DATANORGE,
    KARTVERKET_SEA,
    NVE_RESERVOIRS,
    ELHUB,
    STORTINGET,
    VEGVESEN_TRAFFIC,
    UDIR_NSR,
    USGS_EARTHQUAKES,
    ORDBOKENE,
    AVINOR,
)


def operations():
    # Imported late: handlers need Context, and Context needs SOURCES.
    from kildeverk.sources import cite, composite, meta
    from kildeverk.sources.avinor.ops import OPERATIONS as AVINOR_OPS
    from kildeverk.sources.brreg.accounts import OPERATIONS as BRREG_ACCOUNTS_OPS
    from kildeverk.sources.brreg.ops import OPERATIONS as BRREG_OPS
    from kildeverk.sources.datanorge.ops import OPERATIONS as DATANORGE_OPS
    from kildeverk.sources.elhub.ops import OPERATIONS as ELHUB_OPS
    from kildeverk.sources.entur.ops import OPERATIONS as ENTUR_OPS
    from kildeverk.sources.kartverket.ops import OPERATIONS as KARTVERKET_OPS
    from kildeverk.sources.kartverket_sea.ops import OPERATIONS as KARTVERKET_SEA_OPS
    from kildeverk.sources.met.alerts import OPERATIONS as MET_ALERT_OPS
    from kildeverk.sources.met.normals import OPERATIONS as MET_NORMALS_OPS
    from kildeverk.sources.met.ops import OPERATIONS as MET_OPS
    from kildeverk.sources.met.products import OPERATIONS as MET_PRODUCT_OPS
    from kildeverk.sources.norges_bank.ops import OPERATIONS as NORGES_BANK_OPS
    from kildeverk.sources.nve_hydapi.ops import OPERATIONS as NVE_OPS
    from kildeverk.sources.nve_regobs.ops import OPERATIONS as NVE_REGOBS_OPS
    from kildeverk.sources.nve_reservoirs.ops import OPERATIONS as NVE_RESERVOIRS_OPS
    from kildeverk.sources.nve_varsom.ops import OPERATIONS as NVE_VARSOM_OPS
    from kildeverk.sources.ordbokene.ops import OPERATIONS as ORDBOKENE_OPS
    from kildeverk.sources.ssb_klass.ops import OPERATIONS as SSB_KLASS_OPS
    from kildeverk.sources.ssb_statbank.ops import OPERATIONS as SSB_STATBANK_OPS
    from kildeverk.sources.stortinget.ops import OPERATIONS as STORTINGET_OPS
    from kildeverk.sources.udir_nsr.ops import OPERATIONS as UDIR_NSR_OPS
    from kildeverk.sources.usgs.ops import OPERATIONS as USGS_OPS
    from kildeverk.sources.vegvesen_traffic.ops import OPERATIONS as VEGVESEN_TRAFFIC_OPS

    return (
        *SSB_STATBANK_OPS,
        *SSB_KLASS_OPS,
        *BRREG_OPS,
        *BRREG_ACCOUNTS_OPS,
        *MET_OPS,
        *MET_NORMALS_OPS,
        *MET_ALERT_OPS,
        *MET_PRODUCT_OPS,
        *NVE_OPS,
        *ENTUR_OPS,
        *KARTVERKET_OPS,
        *NORGES_BANK_OPS,
        *NVE_VARSOM_OPS,
        *NVE_REGOBS_OPS,
        *DATANORGE_OPS,
        *KARTVERKET_SEA_OPS,
        *NVE_RESERVOIRS_OPS,
        *ELHUB_OPS,
        *STORTINGET_OPS,
        *VEGVESEN_TRAFFIC_OPS,
        *UDIR_NSR_OPS,
        *USGS_OPS,
        *ORDBOKENE_OPS,
        *AVINOR_OPS,
        *composite.OPERATIONS,
        *cite.OPERATIONS,
        *meta.OPERATIONS,
    )
