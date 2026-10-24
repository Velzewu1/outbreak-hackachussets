"""The SEIR engine: advances any ModelStructure one day at a time.

Each day is split into `substeps` of length dt. Every move in a substep is
computed from the state at its start and then all are applied together, so
the order of transitions never matters. A compartment's outflow is shared
by its transitions in proportion to their rates (competing risks),

    p_k = p_leave * rate_k / sum(rates),

and p_leave depends on what kind of compartment it is:

    infection (S, and V with vaccination):  p_leave = 1 - exp(-sum(rates) * dt)
    every stay after that (E, I, H, C...):  p_leave = sum(rates) * dt

The first is the exact chance of infection while the force of infection is
held over the substep, and it never exceeds 1. The second keeps the mean of
every stay at exactly 1 / rate. Someone who arrives during a substep can only
leave from the next one; with 1 - exp(-rate * dt) that lost part-step adds
about dt / 2 to every stay, which inflates R0 by gamma * dt / 2 (2.5% at four
substeps) and hospital census by about dt / (2 * length of stay). With the
two rules above R0, the final size and the mean stays match the
continuous-time model at any step size. What remains is a slight lag: the
growth factor per substep is 1 + r * dt rather than exp(r * dt), so early
growth is about r * dt / 2 slower (2% at four substeps for r = 0.15/day).
A stay whose rates add up to more than 1 / dt cannot be represented: the
engine refuses to build, or caps it and warns if a signal pushes it there
mid-run.

Both steppers use the same probabilities: the deterministic stepper moves
n * p, the chain-binomial stepper draws whole people.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Callable, Iterable, Protocol

import numpy as np
from scipy.optimize import brentq

from .config import Population, ScenarioConfig, Seeding
from .mixing import MixingOperator
from .rates import (Elastic, Piecewise, RateProvider, RateSet, Signals, TimeSeries,
                    default_rates, with_feedback)
from .structure import ModelStructure, seir_h

if TYPE_CHECKING:
    from .results import SEIRResult


class Stepper(Protocol):
    def move(self, n: np.ndarray, probs: list[np.ndarray]) -> list[np.ndarray]: ...


class Deterministic:
    """Moves the expected number of people: n * p for every transition."""

    integer = False

    def move(self, n, probs):
        return [n * p for p in probs]


class ChainBinomial:
    """Integer draws: each transition takes a binomial share of who is left.

    Drawing transitions one after another with conditional probabilities is
    the same as one multinomial draw per cell, so counts stay whole and
    never go negative.
    """

    integer = True

    def __init__(self, seed: int | None = None):
        self.rng = np.random.default_rng(seed)

    def move(self, n, probs):
        remaining = np.maximum(np.rint(n), 0).astype(np.int64)
        left = np.ones(np.shape(n))
        out = []
        for p in probs:
            cond = np.clip(np.divide(p, left, out=np.zeros(left.shape), where=left > 1e-12), 0.0, 1.0)
            k = self.rng.binomial(remaining, cond)
            out.append(k.astype(float))
            remaining -= k
            left = left - p
        return out


@dataclass
class DayRecord:
    day: int
    date: date
    compartments: dict[str, np.ndarray]   # end of day, [P, A]
    flows: dict[str, np.ndarray]          # people moved during the day, [P, A]
    rates: dict[str, "float | np.ndarray"]  # day-averaged rates in effect, incl. "foi"
    r_eff: float


def _round_rows(x: np.ndarray) -> np.ndarray:
    """Whole numbers that keep each row's (rounded) total: largest remainder per row."""
    floor = np.floor(x)
    short = (np.rint(x.sum(axis=-1, keepdims=True)) - floor.sum(axis=-1, keepdims=True)).astype(int)
    order = np.argsort(floor - x, axis=-1, kind="stable")       # biggest remainder first
    rank = np.empty_like(order)
    np.put_along_axis(rank, order, np.broadcast_to(np.arange(x.shape[-1]), x.shape), axis=-1)
    return floor + (rank < short)


def _check_shapes(rates: dict, shape: tuple[int, int]) -> None:
    """Every rate must be a scalar or broadcast to [patch, age]."""
    for name, v in rates.items():
        try:
            np.broadcast_to(np.asarray(v, dtype=float), shape)
        except ValueError:
            raise ValueError(f"rate {name!r} has shape {np.shape(v)}, which does not fit "
                             f"[patch, age] = {shape}") from None


def contact_modifier_from_config(cfg: ScenarioConfig) -> RateProvider | None:
    """The beta(t) multiplier described by cfg.mixing.contact_multiplier, or None."""
    from .data import contact_multiplier_series

    cm = cfg.mixing.contact_multiplier
    if cm is None:
        return None
    if cm.steps is not None:
        scale = 1.0 / cm.baseline if cm.baseline else 1.0
        steps = {k: (1.0 + v / 100.0 if cm.percent_change else v) * scale for k, v in cm.steps.items()}
        raw: RateProvider = Piecewise(steps)
    else:
        series = contact_multiplier_series(cm)
        if cm.csv is not None:
            raw = TimeSeries.from_dates(series.index.date, series.to_numpy(), cfg.sim.start)
        else:
            raw = TimeSeries(series)
    return raw if cm.elasticity == 1.0 else Elastic(raw, cm.elasticity)


class SEIREngine:
    def __init__(self, structure: ModelStructure, rates: RateSet, mixing: MixingOperator,
                 population: Population, start: date, substeps: int = 4,
                 stepper: Stepper | None = None):
        self.structure = structure
        self.rates = rates
        self.mixing = mixing
        self.population = population
        self.start = start
        self.substeps = substeps
        self.stepper = stepper or Deterministic()
        self.shape = population.N.shape
        self.beta0: float | None = None       # set by from_config
        self._by_source = structure.by_source()
        self._idx = {c: structure.index(c) for c in structure.compartments}
        self._infection = set(structure.infected_from)
        self._capped: set[str] = set()
        self._check_rates()

    # ---- construction -------------------------------------------------
    @staticmethod
    def beta_from_r0(r0: float, gamma: float, mixing: MixingOperator) -> float:
        """Transmission rate that gives R0 in a fully susceptible SEIR population."""
        return r0 * gamma / mixing.spectral_radius(mixing.N)

    @staticmethod
    def beta_for_r0(r0: float, structure: ModelStructure, rates: RateSet,
                    mixing: MixingOperator, t: float = 0.0) -> float:
        """Transmission rate that gives R0 in a fully susceptible population, for any structure.

        R0 = beta * rho(diag(N * D) @ M), where D is how many infectious days
        (weighted by relative infectiousness) one infection produces. For
        seir() and seir_h(), D = 1 / gamma and this is beta_from_r0.
        """
        r = rates.evaluate(t, {})
        _check_shapes(r, mixing.shape)
        r["foi"] = 0.0
        D = structure.infectious_days(r, mixing.shape)
        susc = structure.susceptibility(r, mixing.shape).get(structure.susceptible, 1.0)
        rho = mixing.spectral_radius(mixing.N * susc * D)
        if rho <= 0:
            raise ValueError("no transmission is possible: check contacts, coupling and infectious stages")
        return r0 / rho

    @classmethod
    def from_config(cls, cfg: ScenarioConfig, structure: ModelStructure | None = None,
                    contact_modifier: RateProvider | None = None,
                    feedback: Iterable[str] = (),
                    **rate_overrides: RateProvider) -> "SEIREngine":
        """Build an engine from a scenario.

        structure:        defaults to seir_h()
        contact_modifier: multiplies beta0; defaults to cfg.mixing.contact_multiplier
        feedback:         standard signal names to wire in, e.g. ("icu_mortality_multiplier",);
                          see rates.FEEDBACK. Off by default.
        rate_overrides:   any rate by name, e.g. p_death_icu=Product(...), waning=Constant(1/180)
        """
        pop = cfg.population
        structure = structure or seir_h()
        mixing = MixingOperator(pop.N, cfg.contact_matrix(), cfg.coupling_matrix())
        if contact_modifier is None:
            contact_modifier = contact_modifier_from_config(cfg)

        def rate_set(beta0: float) -> RateSet:
            rates = default_rates(cfg.disease, len(pop.ages), beta0, contact_modifier, ages=pop.ages)
            return rates.replace(**rate_overrides) if rate_overrides else rates

        beta0 = cls.beta_for_r0(cfg.disease.r0, structure, rate_set(1.0), mixing)
        rates = rate_set(beta0)
        feedback = tuple(feedback)
        if feedback:
            rates = with_feedback(rates, feedback)
        stepper = ChainBinomial(cfg.sim.seed) if cfg.sim.stochastic else Deterministic()
        engine = cls(structure, rates, mixing, pop, cfg.sim.start, cfg.sim.substeps, stepper)
        engine.beta0 = beta0
        return engine

    def _check_rates(self) -> None:
        """Fail at build time, not mid-run: a missing, mis-shaped, negative or too fast rate."""
        r = self.rates.evaluate(0.0, {})
        _check_shapes(r, self.shape)
        r["foi"] = np.zeros(self.shape)
        totals: dict[str, np.ndarray] = {}
        for t in self.structure.transitions:
            try:
                v = np.asarray(t.rate(r), dtype=float)
            except KeyError as e:
                name = e.args[0]
                raise KeyError(
                    f"transition {t.flow} ({t.src} -> {t.dst}) needs rate {name!r}, which the rate "
                    f"set does not have ({', '.join(self.rates.names)}). Pass it by name, e.g. "
                    f"SEIREngine.from_config(cfg, structure=..., {name}=Constant(...))") from None
            try:
                np.broadcast_to(v, self.shape)
            except ValueError:
                raise ValueError(f"rate for {t.flow} has shape {v.shape}, which does not fit "
                                 f"[patch, age] = {self.shape}") from None
            if (v < 0).any() or not np.isfinite(v).all():
                raise ValueError(f"rate for {t.flow} is negative or not finite at t = 0")
            totals[t.src] = totals.get(t.src, 0.0) + v
        for src, total in totals.items():
            fastest = float(np.max(total))
            if src not in self._infection and fastest / self.substeps > 1.0:
                raise ValueError(
                    f"people leave {src} at {fastest:.3g} per day, faster than a substep of "
                    f"1/{self.substeps} day can hold; set sim.substeps to at least {int(np.ceil(fastest))}")

    def initial_state(self, seeding: Seeding) -> np.ndarray:
        """People per [compartment, patch, age] on day 0.

        immune_share moves part of each patch from S to R. Seeds go to the
        structure's `exposed` compartment and its first infectious one, and
        seeding.initial puts people straight into any other compartment (a
        hospital census, say); counts are spread over ages by population
        unless given per age. Stochastic runs get whole numbers that keep
        every patch's seeded total.
        """
        pop, st = self.population, self.structure
        N = pop.N
        X = np.zeros((len(st.compartments),) + self.shape)
        age_share = N / N.sum(axis=1, keepdims=True)
        immune = self._immune_share(seeding)
        if immune.any():
            if "R" not in self._idx:
                raise ValueError("immune_share needs an R compartment in the structure")
            X[self._idx["R"]] = N * immune[:, None]
        roles = {"exposed": st.exposed, "infectious": next(iter(st.infectious))}
        for key, by_patch in seeding.counts(self.shape[1]).items():
            comp = roles.get(key, key)
            if key not in roles and (comp not in self._idx or comp == st.susceptible):
                raise ValueError(f"seeding.initial names {comp!r}; use one of "
                                 f"{[c for c in st.compartments if c != st.susceptible]}")
            for patch, count in by_patch.items():
                p = pop.patches.index(patch)
                X[self._idx[comp], p] += count if np.ndim(count) else count * age_share[p]
        s = self._idx[st.susceptible]
        if getattr(self.stepper, "integer", False):
            N = _round_rows(N)
            for i in range(len(st.compartments)):
                if i != s:
                    X[i] = _round_rows(X[i])
        X[s] = N - np.delete(X, s, axis=0).sum(axis=0)
        if (X[s] < -1e-9).any():
            raise ValueError("seeding and immunity exceed the population of some patch and age group")
        X[s] = np.maximum(X[s], 0.0)
        return X

    def _immune_share(self, seeding: Seeding) -> np.ndarray:
        share = seeding.immune_share
        patches = self.population.patches
        if isinstance(share, dict):
            unknown = set(share) - set(patches)
            if unknown:
                raise ValueError(f"immune_share names unknown patches: {sorted(unknown)}")
            return np.array([share.get(p, 0.0) for p in patches], dtype=float)
        return np.full(len(patches), float(share))

    # ---- stepping -----------------------------------------------------
    def _infectious_load(self, X: np.ndarray) -> np.ndarray:
        return sum(w * X[self._idx[c]] for c, w in self.structure.infectious.items())

    def step_day(self, X: np.ndarray, day: int, signals: Signals | None = None
                 ) -> tuple[np.ndarray, DayRecord]:
        signals = signals or {}
        X = X.copy()
        dt = 1.0 / self.substeps
        flows = {f: np.zeros(self.shape) for f in self.structure.flows}
        rate_sums: dict[str, "float | np.ndarray"] = {}

        for k in range(self.substeps):
            r = self.rates.evaluate(day + k * dt, signals)
            r["foi"] = r["beta"] * self.mixing.apply(self._infectious_load(X))
            for name, v in r.items():
                rate_sums[name] = rate_sums.get(name, 0.0) + v * dt

            # Compute every move from the same start-of-substep state, then apply.
            moves = []
            for src, transitions in self._by_source.items():
                rk = [t.rate(r) for t in transitions]
                if k == 0:
                    self._check_signs(transitions, rk, day)
                total = rk[0]
                for x in rk[1:]:
                    total = total + x
                if src in self._infection:
                    p_leave = -np.expm1(-np.multiply(total, dt))
                else:
                    p_leave = np.multiply(total, dt)
                    if np.max(p_leave) > 1.0:
                        self._warn_capped(src, day, float(np.max(total)))
                        p_leave = np.minimum(p_leave, 1.0)
                if len(rk) == 1:
                    probs = [p_leave]
                else:
                    scale = np.divide(p_leave, total, out=np.zeros(np.shape(total)), where=total > 0)
                    probs = [x * scale for x in rk]
                moves.append((src, transitions, self.stepper.move(X[self._idx[src]], probs)))
            for src, transitions, moved in moves:
                for t, m in zip(transitions, moved):
                    X[self._idx[src]] -= m
                    X[self._idx[t.dst]] += m
                    flows[t.flow] += m

        record = DayRecord(
            day=day,
            date=self.start + timedelta(days=day),
            compartments={c: X[i].copy() for c, i in self._idx.items()},
            flows=flows,
            rates=rate_sums,
            r_eff=self.r_eff(X, rate_sums),
        )
        return X, record

    def _warn_capped(self, src: str, day: int, fastest: float) -> None:
        if src not in self._capped:
            self._capped.add(src)
            warnings.warn(f"day {day}: people leave {src} at {fastest:.3g} per day, faster than a substep "
                          f"of 1/{self.substeps} day can hold; capped at one substep. Set sim.substeps to at "
                          f"least {int(np.ceil(fastest))}.", RuntimeWarning, stacklevel=3)

    @staticmethod
    def _check_signs(transitions, rk, day: int) -> None:
        for t, x in zip(transitions, rk):
            if np.min(x) < 0:
                raise ValueError(f"day {day}: rate for {t.flow} is negative; clip probabilities "
                                 f"that a multiplier can push above 1 (see rates.Clip)")

    def run(self, seeding: Seeding, days: int,
            signals_fn: Callable[[int, np.ndarray], Signals] | None = None) -> "SEIRResult":
        from .results import SEIRResult

        X = self.initial_state(seeding)
        X0 = X.copy()
        records = []
        for day in range(days):
            signals = signals_fn(day, X) if signals_fn else None
            X, rec = self.step_day(X, day, signals)
            records.append(rec)
        return SEIRResult.from_records(records, X0, self.structure, self.population)

    # ---- reproduction numbers and growth -------------------------------
    def _rates_at(self, t: float, signals: Signals | None) -> dict:
        r = self.rates.evaluate(t, signals or {})
        r["foi"] = 0.0
        return r

    def _effective_susceptibles(self, X: np.ndarray, rates) -> np.ndarray:
        susc = self.structure.susceptibility(rates, self.shape)
        return sum(np.asarray(s) * X[self._idx[c]] for c, s in susc.items())

    def r_eff(self, X: np.ndarray, rates) -> float:
        """Effective reproduction number for state X under `rates` (a rates dict).

        rho(diag(S_eff * beta * D) @ M): S_eff counts susceptibles weighted by
        how easily each compartment is infected (S = 1, vaccinated = 1 - VE),
        D is infectiousness-weighted infectious days per infection.
        """
        D = self.structure.infectious_days(rates, self.shape)
        beta = np.broadcast_to(np.asarray(rates["beta"], dtype=float), self.shape)
        return self.mixing.spectral_radius(self._effective_susceptibles(X, rates) * beta * D)

    def _fully_susceptible(self) -> np.ndarray:
        X = np.zeros((len(self.structure.compartments),) + self.shape)
        X[self._idx[self.structure.susceptible]] = self.population.N
        return X

    def r0(self, t: float = 0.0, signals: Signals | None = None) -> float:
        """Basic reproduction number at time t (a fully susceptible population)."""
        return self.r_eff(self._fully_susceptible(), self._rates_at(t, signals))

    def growth_rate(self, X: np.ndarray | None = None, t: float = 0.0,
                    signals: Signals | None = None) -> float:
        """Exponential growth rate r (per day) of new infections at state X.

        Solves rho(diag(S_eff * beta * D(r)) @ M) = 1, where D(r) discounts
        infectious days by exp(-r * age of infection) (the Euler-Lotka
        equation). For seir() this is (1 + r / sigma)(1 + r / gamma) = R.
        X defaults to a fully susceptible population.
        """
        X = self._fully_susceptible() if X is None else X
        rates = self._rates_at(t, signals)
        beta = np.broadcast_to(np.asarray(rates["beta"], dtype=float), self.shape)
        weight = self._effective_susceptibles(X, rates) * beta

        def f(r: float) -> float:
            D = self.structure.infectious_days(rates, self.shape, discount=r)
            return np.log(max(self.mixing.spectral_radius(weight * D), 1e-300))

        A, _, _ = self.structure._path_system(rates)
        low = -0.999 * float(np.min(np.real(np.linalg.eigvals(A))))
        if f(0.0) == np.log(1e-300):
            return low
        high = 0.1
        while f(high) > 0:
            high *= 2
            if high > 1e3:
                raise ValueError("growth rate is unbounded; check the rates")
        if f(low) < 0:
            return low
        return float(brentq(f, low, high, xtol=1e-12))

    def doubling_time(self, X: np.ndarray | None = None, t: float = 0.0,
                      signals: Signals | None = None) -> float:
        """Days for infections to double (negative: days to halve)."""
        r = self.growth_rate(X, t, signals)
        return float(np.log(2) / r) if r != 0 else float("inf")

    def generation_time(self, t: float = 0.0, signals: Signals | None = None) -> float:
        """Mean days from infection to infecting someone, averaged over the population."""
        g = self.structure.generation_time(self._rates_at(t, signals), self.shape)
        N = self.population.N
        return float((g * N).sum() / N.sum())

    def describe(self, t: float = 0.0, seeding: Seeding | None = None) -> dict:
        """Plain numbers about this engine, for a terminal, a log or a frontend.

        R0 and growth rates are for a fully susceptible population; with
        `seeding`, the *_start values are for the scenario's day-0 state
        (prior immunity included).
        """
        rates = self._rates_at(t, {})

        def scalar(name):
            v = np.asarray(rates[name], dtype=float)
            return float(v) if v.ndim == 0 else float((np.broadcast_to(v, self.shape) * self.population.N).sum()
                                                        / self.population.N.sum())

        r = self.growth_rate(t=t)
        out = {
            "compartments": list(self.structure.compartments),
            "flows": list(self.structure.flows),
            "infection_path": list(self.structure.infection_path),
            "patches": len(self.population.patches),
            "age_groups": len(self.population.ages),
            "population": float(self.population.N.sum()),
            "transmission_rate": scalar("beta"),
            "incubation_rate": scalar("sigma") if "sigma" in rates else None,
            "recovery_rate": scalar("gamma") if "gamma" in rates else None,
            "r0": self.r0(t),
            "generation_time_days": self.generation_time(t),
            "growth_rate_per_day": r,
            "doubling_time_days": float(np.log(2) / r) if r > 0 else None,
            "substeps": self.substeps,
            "stochastic": bool(getattr(self.stepper, "integer", False)),
            "rates": list(self.rates.names),
        }
        if seeding is not None:
            X0 = self.initial_state(seeding)
            r0 = self.growth_rate(X0, t)
            out.update(r_eff_start=self.r_eff(X0, rates), growth_rate_start=r0,
                       doubling_time_start=float(np.log(2) / r0) if r0 > 0 else None)
        return out


def simulate(cfg: ScenarioConfig, days: int | None = None, **engine_kwargs) -> "SEIRResult":
    """Build an engine from a scenario and run it: the one-call entry point."""
    engine = SEIREngine.from_config(cfg, **engine_kwargs)
    return engine.run(cfg.seeding, days or cfg.sim.days)
