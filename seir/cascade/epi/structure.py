"""Model structure as data: compartments plus transitions between them.

The engine never hard-codes S, E, I or R. A new compartment (vaccinated,
asymptomatic, waning immunity) is a new entry here, not an engine change.
The helpers at the bottom (with_waning, with_vaccination, with_asymptomatic)
are worked examples of exactly that.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import Callable, Mapping

import numpy as np

# Receives the evaluated rates for this substep (plus "foi") and returns a
# per-capita rate per day, scalar or broadcastable to [patch, age].
RateFn = Callable[[Mapping[str, "float | np.ndarray"]], "float | np.ndarray"]
Rates = Mapping[str, "float | np.ndarray"]


@dataclass(frozen=True)
class Transition:
    src: str
    dst: str
    rate: RateFn
    flow: str  # name of the daily count this transition reports


@dataclass(frozen=True)
class ModelStructure:
    compartments: tuple[str, ...]
    transitions: tuple[Transition, ...]
    # Relative infectiousness of each compartment that transmits.
    infectious: Mapping[str, float] = field(default_factory=lambda: {"I": 1.0})
    susceptible: str = "S"
    # Where a new infection lands. R0 and R_eff follow the path from here.
    exposed: str = "E"

    def __post_init__(self):
        names = set(self.compartments)
        if len(names) != len(self.compartments):
            raise ValueError("compartment names must be unique")
        for t in self.transitions:
            if t.src not in names or t.dst not in names:
                raise ValueError(f"transition {t.flow} uses an unknown compartment")
            if t.src == t.dst:
                raise ValueError(f"transition {t.flow} goes from {t.src} to itself")
        flows = [t.flow for t in self.transitions]
        if len(flows) != len(set(flows)):
            raise ValueError("flow names must be unique")
        clash = set(flows) & names
        if clash:
            raise ValueError(f"flow names clash with compartment names: {sorted(clash)}")
        for c in (self.susceptible, self.exposed, *self.infectious):
            if c not in names:
                raise ValueError(f"{c!r} is not a compartment")
        if not self.infection_path:
            raise ValueError(f"no infectious compartment can be reached from {self.exposed!r}")

    def index(self, name: str) -> int:
        return self.compartments.index(name)

    @property
    def flows(self) -> tuple[str, ...]:
        return tuple(t.flow for t in self.transitions)

    def by_source(self) -> dict[str, list[Transition]]:
        out: dict[str, list[Transition]] = {}
        for t in self.transitions:
            out.setdefault(t.src, []).append(t)
        return out

    def extend(self, compartments=(), transitions=(), drop_flows=(), **kw) -> "ModelStructure":
        """A new structure with extra compartments and transitions; `drop_flows` removes some first."""
        kept = tuple(t for t in self.transitions if t.flow not in set(drop_flows))
        return replace(self, compartments=self.compartments + tuple(compartments),
                       transitions=kept + tuple(transitions), **kw)

    # ---- the infection path, for R0, R_eff and growth rates -------------
    @cached_property
    def infection_path(self) -> tuple[str, ...]:
        """Compartments a new infection passes through on its way to transmitting.

        Starts at `exposed`, follows transitions (never back through the
        susceptible compartment) and keeps the stages from which an
        infectious compartment can still be reached. (E, I) for seir_h().
        """
        succ: dict[str, set[str]] = {}
        for t in self.transitions:
            succ.setdefault(t.src, set()).add(t.dst)

        def reach(start: str) -> set[str]:
            seen, todo = {start}, [start]
            while todo:
                for d in succ.get(todo.pop(), ()):
                    if d not in seen and d != self.susceptible:
                        seen.add(d)
                        todo.append(d)
            return seen

        infectious = {c for c, w in self.infectious.items() if w > 0}
        from_entry = reach(self.exposed)
        return tuple(c for c in self.compartments
                     if c in from_entry and c != self.susceptible and reach(c) & infectious)

    def _path_system(self, rates: Rates):
        """Generator of the infection path: A = diag(exit) - G, plus weights w and entry e.

        Arrays have the broadcast shape of the rates involved (e.g. [age] when
        only p_hosp varies by age), not the full [patch, age] grid, so the
        linear algebra runs once per distinct cell type.
        """
        path = self.infection_path
        k = len(path)
        pos = {c: i for i, c in enumerate(path)}
        used = [(t, t.rate(rates)) for t in self.transitions if t.src in pos]
        core = np.broadcast_shapes(*(np.shape(r) for _, r in used)) if used else ()
        G = np.zeros(core + (k, k))
        exit_ = np.zeros(core + (k,))
        for t, r in used:
            exit_[..., pos[t.src]] += r
            if t.dst in pos:
                G[..., pos[t.src], pos[t.dst]] += r
        A = -G
        idx = np.arange(k)
        A[..., idx, idx] += np.maximum(exit_, 1e-12)
        w = np.array([self.infectious.get(c, 0.0) for c in path])
        e = np.zeros(k)
        e[pos[self.exposed]] = 1.0
        return A, w, e

    def infectious_days(self, rates: Rates, shape: tuple[int, ...], discount: float = 0.0) -> np.ndarray:
        """Infectiousness-weighted days one new infection spends infectious, per cell.

        Exact for any branching chain of exponential stages: the expected time
        in each stage, starting from `exposed`, is a row of (A + r I)^-1, where
        r = `discount`. With r = 0 this is 1 / gamma for seir() and seir_h();
        with r > 0 it is the Laplace transform used for growth rates.
        """
        A, w, e = self._path_system(rates)
        if discount:
            A = A + discount * np.eye(len(w))
        tau = np.linalg.solve(np.swapaxes(A, -1, -2), np.broadcast_to(e, A.shape[:-1])[..., None])[..., 0]
        return np.broadcast_to(tau @ w, shape)

    def generation_time(self, rates: Rates, shape: tuple[int, ...]) -> np.ndarray:
        """Mean time from infection to infecting someone else, per cell (days).

        For seir() this is latent_period + infectious_period.
        """
        A, w, e = self._path_system(rates)
        At = np.swapaxes(A, -1, -2)
        b = np.broadcast_to(e, A.shape[:-1])[..., None]
        first = np.linalg.solve(At, b)
        second = np.linalg.solve(At, first)
        return np.broadcast_to((second[..., 0] @ w) / (first[..., 0] @ w), shape)

    @cached_property
    def infected_from(self) -> tuple[str, ...]:
        """Compartments new infections come from: every source of a transition into
        `exposed` from outside the infection path. ("S",) for seir_h(), ("S", "V")
        with vaccination."""
        path = set(self.infection_path)
        return tuple(c for c in self.compartments
                     if any(t.src == c and t.dst == self.exposed for t in self.transitions)
                     and c not in path)

    def susceptibility(self, rates: Rates, shape: tuple[int, ...]) -> dict[str, np.ndarray]:
        """How strongly each compartment is infected, per unit force of infection.

        Read off every transition into `exposed` from outside the infection
        path: S gets 1, a vaccinated compartment infected at foi * (1 - VE)
        gets 1 - VE. Assumes those rates are linear in "foi".
        """
        out: dict[str, np.ndarray] = {}
        for t in self.transitions:
            if t.dst == self.exposed and t.src in self.infected_from:
                hi = np.asarray(t.rate({**rates, "foi": 1.0}), dtype=float)
                lo = np.asarray(t.rate({**rates, "foi": 0.0}), dtype=float)
                out[t.src] = out.get(t.src, 0.0) + np.broadcast_to(hi - lo, shape)
        return out


def seir() -> ModelStructure:
    return ModelStructure(
        compartments=("S", "E", "I", "R"),
        transitions=(
            Transition("S", "E", lambda r: r["foi"], "new_exposed"),
            Transition("E", "I", lambda r: r["sigma"], "new_infectious"),
            Transition("I", "R", lambda r: r["gamma"], "new_recovered"),
        ),
    )


def seir_h() -> ModelStructure:
    """SEIR plus ward (H), ICU (C) and death (D). Hospital patients do not transmit."""
    return seir().extend(
        compartments=("H", "C", "D"),
        drop_flows=("new_recovered",),
        transitions=(
            Transition("I", "R", lambda r: r["gamma"] * (1 - r["p_hosp"]), "new_recovered"),
            Transition("I", "H", lambda r: r["gamma"] * r["p_hosp"], "new_hosp"),
            Transition("H", "C", lambda r: r["ward_exit"] * r["p_icu"], "new_icu"),
            Transition("H", "R", lambda r: r["ward_exit"] * (1 - r["p_icu"]), "ward_discharges"),
            Transition("C", "D", lambda r: r["icu_exit"] * r["p_death_icu"], "new_deaths"),
            Transition("C", "R", lambda r: r["icu_exit"] * (1 - r["p_death_icu"]), "icu_discharges"),
        ),
    )


STRUCTURES: dict[str, Callable[[], ModelStructure]] = {"seir": seir, "seir_h": seir_h}


# ---- worked extensions: each is a structure change plus the rates it needs ----
def with_waning(structure: ModelStructure, source: str = "R") -> ModelStructure:
    """Immunity wanes: `source` -> S at rate "waning" (per day, e.g. 1/180)."""
    return structure.extend(transitions=(
        Transition(source, structure.susceptible, lambda r: r["waning"], "new_waned"),))


def with_vaccination(structure: ModelStructure) -> ModelStructure:
    """S -> V at rate "vax_rate"; V is infected at foi * (1 - "vax_efficacy")."""
    return structure.extend(
        compartments=("V",),
        transitions=(
            Transition(structure.susceptible, "V", lambda r: r["vax_rate"], "new_vaccinated"),
            Transition("V", structure.exposed, lambda r: r["foi"] * (1 - r["vax_efficacy"]),
                       "breakthrough_infections"),
        ))


def with_asymptomatic(structure: ModelStructure, relative_infectiousness: float = 0.5) -> ModelStructure:
    """A share "p_asym" of E becomes asymptomatic (A) instead of I.

    A transmits at `relative_infectiousness` of I, recovers at gamma and never
    needs a hospital. R0 and R_eff account for both stages automatically.
    """
    E = structure.exposed
    return structure.extend(
        compartments=("A",),
        drop_flows=("new_infectious",),
        transitions=(
            Transition(E, "I", lambda r: r["sigma"] * (1 - r["p_asym"]), "new_infectious"),
            Transition(E, "A", lambda r: r["sigma"] * r["p_asym"], "new_asymptomatic"),
            Transition("A", "R", lambda r: r["gamma"], "asymptomatic_recoveries"),
        ),
        infectious={**structure.infectious, "A": relative_infectiousness},
    )
