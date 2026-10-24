"""The port between the SEIR layer and the rest of the system.

EpiSnapshot is the only thing allocation and FDNA should import from the
epidemic side. As long as it keeps its fields, the engine behind it can
change (more compartments, stochastic runs, a different solver). Fields are
only ever added, at the end and with a default, never renamed or removed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from ..core import SimState
from .config import ScenarioConfig, Seeding
from .engine import DayRecord, SEIREngine


def _per_patch(value, weights: np.ndarray):
    """Collapse a [patch, age] rate to [patch] using population weights; keep scalars."""
    if np.ndim(value) == 0:
        return float(value)
    v = np.broadcast_to(value, weights.shape)
    return (v * weights).sum(axis=1) / weights.sum(axis=1)


@dataclass(frozen=True)
class EpiSnapshot:
    day: int
    date: date
    patches: tuple[str, ...]
    population: np.ndarray          # [patch]
    infectious: np.ndarray          # [patch] people currently infectious (I, plus A etc. if the structure has them)
    prevalence: np.ndarray          # [patch] infectious / population, drives staff absenteeism in FDNA
    new_hosp: np.ndarray            # [patch] new ward admissions today
    new_icu: np.ndarray             # [patch] new ICU transfers today
    transmission_rate: "float | np.ndarray"   # beta(t), per day
    incubation_rate: "float | np.ndarray"     # sigma, per day
    recovery_rate: "float | np.ndarray"       # gamma, per day
    force_of_infection: np.ndarray  # [patch] per-capita infection rate, per day
    r_eff: float
    # Added after v1 (defaults keep older constructors working):
    susceptible: np.ndarray | None = None     # [patch] people in S at the end of the day
    exposed: np.ndarray | None = None         # [patch] people in E
    new_infections: np.ndarray | None = None  # [patch] new infections today
    new_deaths: np.ndarray | None = None      # [patch] deaths today
    ward_census: np.ndarray | None = None     # [patch] COVID patients on wards (H)
    icu_census: np.ndarray | None = None      # [patch] COVID patients in ICU (C)

    @classmethod
    def from_record(cls, rec: DayRecord, patches, N: np.ndarray,
                    infectious: tuple[str, ...] = ("I",), infection_flows: tuple[str, ...] = ("new_exposed",),
                    susceptible: str = "S", exposed: str = "E") -> "EpiSnapshot":
        zeros = np.zeros(len(patches))

        def patch_sum(name):
            if name in rec.compartments:
                return rec.compartments[name].sum(axis=1)
            if name in rec.flows:
                return rec.flows[name].sum(axis=1)
            return zeros.copy()

        pop = N.sum(axis=1)
        inf = sum(patch_sum(c) for c in infectious)
        return cls(
            day=rec.day, date=rec.date, patches=tuple(patches), population=pop,
            infectious=inf, prevalence=inf / pop,
            new_hosp=patch_sum("new_hosp"), new_icu=patch_sum("new_icu"),
            transmission_rate=_per_patch(rec.rates["beta"], N),
            incubation_rate=_per_patch(rec.rates["sigma"], N) if "sigma" in rec.rates else float("nan"),
            recovery_rate=_per_patch(rec.rates["gamma"], N) if "gamma" in rec.rates else float("nan"),
            force_of_infection=_per_patch(np.broadcast_to(rec.rates["foi"], N.shape), N),
            r_eff=rec.r_eff,
            susceptible=patch_sum(susceptible),
            exposed=patch_sum(exposed),
            new_infections=sum(patch_sum(f) for f in infection_flows),
            new_deaths=patch_sum("new_deaths"),
            ward_census=patch_sum("H"),
            icu_census=patch_sum("C"),
        )


class SEIRModule:
    """Wraps an SEIREngine as a Module for the shared simulation loop.

    Reads state.signals["seir"] (written by other modules the day before),
    advances one day and writes state.epi.
    """

    name = "seir"

    def __init__(self, engine: SEIREngine, seeding: Seeding):
        self.engine = engine
        self.seeding = seeding
        self.X = engine.initial_state(seeding)
        self.X0 = self.X.copy()
        self.records: list[DayRecord] = []
        st = engine.structure
        path = set(st.infection_path)
        self._snapshot_args = dict(
            infectious=tuple(st.infectious),
            infection_flows=tuple(t.flow for t in st.transitions
                                  if t.dst == st.exposed and t.src not in path),
            susceptible=st.susceptible, exposed=st.exposed,
        )

    @classmethod
    def from_config(cls, cfg: ScenarioConfig, **engine_kwargs) -> "SEIRModule":
        return cls(SEIREngine.from_config(cfg, **engine_kwargs), cfg.seeding)

    def step(self, state: SimState, t: int) -> SimState:
        signals = state.signals.get(self.name, {})
        self.X, rec = self.engine.step_day(self.X, t, signals)
        self.records.append(rec)
        state.epi = EpiSnapshot.from_record(rec, self.engine.population.patches,
                                            self.engine.population.N, **self._snapshot_args)
        return state

    def result(self):
        """Everything this module has simulated so far, as an SEIRResult."""
        from .results import SEIRResult

        return SEIRResult.from_records(self.records, self.X0, self.engine.structure,
                                       self.engine.population)
