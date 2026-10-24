"""The public entry points. The dashboard, CLI, notebooks and sweeps call these and nothing else."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import xarray as xr

from .epi import SEIRResult
from .fdna import criticality as _criticality
from .scenario import SystemConfig, build


@dataclass
class RunResult:
    system: xr.Dataset           # time x hospital / patch / node
    epi: SEIRResult              # full SEIR output, time x patch x age

    def summary(self) -> dict:
        s = self.system
        return {
            "peak_occupancy_icu": float(s.occupancy_icu.max()),
            "hospital_days_on_diversion": int(s.on_diversion.sum()),
            "diverted_patients": float(s.diverted_patients.sum()),
            "overflow_patients": float(s.overflow.sum()),
            "lost_access_person_days": float(s.lost_person_days.sum()),
            "weighted_access_loss": float(s.weighted_loss.sum()),
            "deaths": float(self.epi.ds["new_deaths"].sum()),
        }


def load(path: str | Path) -> SystemConfig:
    return SystemConfig.from_yaml(path)


def run(cfg: SystemConfig, days: int | None = None,
        overrides: dict[str, float] | None = None) -> RunResult:
    days = days or cfg.epi.sim.days
    sim, seir, recorder = build(cfg, overrides)
    sim.run(days)
    X0 = seir.engine.initial_state(cfg.epi.seeding)
    epi = SEIRResult.from_records(seir.records, X0, seir.engine.structure, cfg.epi.population)
    return RunResult(system=recorder.to_dataset(), epi=epi)


def _loss(args) -> float:
    cfg, days, overrides = args
    return run(cfg, days, overrides).summary()["weighted_access_loss"]


class _Runner:
    """Picklable run(overrides) -> loss, so the sweep can use worker processes."""

    def __init__(self, cfg, days):
        self.cfg, self.days = cfg, days

    def __call__(self, overrides):
        return _loss((self.cfg, self.days, overrides))


def criticality(cfg: SystemConfig, days: int | None = None, nodes=None, level: float = 0.0,
                workers: int = 1):
    """Rank FDNA nodes by the extra vulnerability-weighted access loss when each is knocked out."""
    if nodes is None:
        sim, _, _ = build(cfg)
        nodes = [n for n in sim.module("fdna").graph.nodes if not n.endswith(".hospital")]
    return _criticality(_Runner(cfg, days), nodes, level, workers)
