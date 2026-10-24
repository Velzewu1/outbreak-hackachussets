"""One YAML file per scenario, and the one function that wires modules together."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, Field

from .allocation import Allocation
from .core import Simulation
from .epi import Constant, Product, ScenarioConfig, SEIREngine, SEIRModule, Signal
from .equity import Equity
from .fdna import Event, FDNAConfig, FDNAModule
from .network import Network, NetworkConfig
from .recorder import Recorder
from .reroute import Rerouting


class AllocationConfig(BaseModel):
    decay: float = Field(default=0.08, gt=0)     # per minute of drive time


class RerouteConfig(BaseModel):
    p_on: float = 40.0
    p_off: float = 50.0
    occ_on: float = 0.95
    occ_off: float = 0.90
    min_open: int = 1                            # never divert the last k hospitals


class EquityConfig(BaseModel):
    vulnerability: dict[str, float] = {}         # patch -> weight, default 1


class SystemConfig(BaseModel):
    epi: ScenarioConfig
    network: NetworkConfig
    allocation: AllocationConfig = AllocationConfig()
    fdna: FDNAConfig = FDNAConfig()
    rerouting: RerouteConfig = RerouteConfig()
    equity: EquityConfig = EquityConfig()
    events: list[Event] = []
    feedback_to_seir: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SystemConfig":
        path = Path(path)
        raw = yaml.safe_load(path.read_text())
        if isinstance(raw.get("epi"), str):        # epi: other_file.yaml, relative to this one
            raw["epi"] = yaml.safe_load((path.parent / raw["epi"]).read_text())
        return cls.model_validate(raw)


def build(cfg: SystemConfig, overrides: dict[str, float] | None = None
          ) -> tuple[Simulation, SEIRModule, Recorder]:
    """The composition root. The only place that knows every module exists."""
    epi = cfg.epi
    pop = epi.population
    net = Network.from_config(cfg.network, pop.patches)

    rate_overrides = {}
    if cfg.feedback_to_seir:
        base = Constant(epi.disease.by_age("p_death_icu", len(pop.ages)))
        rate_overrides["p_death_icu"] = Product(
            base, Signal("icu_mortality_multiplier", default=1.0, per_patch=True))
    engine = SEIREngine.from_config(epi, **rate_overrides)
    seir = SEIRModule(engine, epi.seeding)

    alloc = Allocation(net, cfg.allocation.decay, epi.disease.los_ward, epi.disease.los_icu)
    shares = alloc.shares
    vuln = np.array([cfg.equity.vulnerability.get(p, 1.0) for p in pop.patches])
    recorder = Recorder(net)
    sim = Simulation([
        seir,
        alloc,
        FDNAModule(net, shares, cfg.fdna, cfg.events, overrides),
        Rerouting(net, **cfg.rerouting.model_dump()),
        Equity(net, shares, pop.N.sum(axis=1), vuln),
        recorder,
    ])
    return sim, seir, recorder
