"""Rate providers: small objects that say what a rate is at time t.

Every rate the engine uses (transmission, incubation, recovery, hospital
shares, lengths of stay) comes from a provider called as provider(t, signals),
so any of them can be made time-varying or driven by another module without
touching the engine. t is in days since the scenario start; signals are the
values other modules wrote for the SEIR module (state.signals["seir"]).
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Iterable, Mapping, Protocol, Sequence

import numpy as np

# External inputs for the current day, written by other modules (e.g. FDNA).
Signals = Mapping[str, "float | np.ndarray"]
Value = "float | np.ndarray"


class RateProvider(Protocol):
    def __call__(self, t: float, signals: Signals) -> Value: ...


class Constant:
    def __init__(self, value):
        self.value = np.asarray(value, dtype=float) if np.ndim(value) else float(value)

    def __call__(self, t, signals):
        return self.value


class TimeSeries:
    """Daily values (e.g. MBTA ridership / baseline), linearly interpolated, flat outside their range."""

    def __init__(self, values, start_day: float = 0.0):
        self.values = np.asarray(values, dtype=float)
        if self.values.ndim != 1 or self.values.size == 0:
            raise ValueError("TimeSeries needs a non-empty 1-D sequence of values")
        self.days = start_day + np.arange(len(self.values))

    @classmethod
    def from_dates(cls, dates: Sequence[date], values, start: date) -> "TimeSeries":
        """Values on consecutive calendar days, aligned to the scenario start date."""
        return cls(values, start_day=float((dates[0] - start).days))

    def __call__(self, t, signals):
        return float(np.interp(t, self.days, self.values))


class Piecewise:
    """Step function: {day: value}, each value held until the next step; `before` until the first."""

    def __init__(self, steps: Mapping[float, float], before: float = 1.0):
        if not steps:
            raise ValueError("Piecewise needs at least one step")
        items = sorted((float(k), float(v)) for k, v in steps.items())
        self.days = np.array([k for k, _ in items])
        self.values = np.array([v for _, v in items])
        self.before = float(before)

    def __call__(self, t, signals):
        i = np.searchsorted(self.days, t, side="right") - 1
        return self.before if i < 0 else float(self.values[i])


class Seasonal:
    """1 + amplitude * cos(2 pi (t - peak_day) / period): winter forcing for flu-like pathogens."""

    def __init__(self, amplitude: float, peak_day: float, period: float = 365.25):
        if not 0 <= amplitude < 1:
            raise ValueError("amplitude must be in [0, 1)")
        self.amplitude, self.peak_day, self.period = amplitude, peak_day, period

    def __call__(self, t, signals):
        return 1.0 + self.amplitude * float(np.cos(2 * np.pi * (t - self.peak_day) / self.period))


class Elastic:
    """1 + elasticity * (provider - 1): contacts respond less (or more) than mobility does."""

    def __init__(self, provider: RateProvider, elasticity: float):
        self.provider, self.elasticity = provider, elasticity

    def __call__(self, t, signals):
        return 1.0 + self.elasticity * (self.provider(t, signals) - 1.0)


class Signal:
    """Reads a value another module published, e.g. FDNA's ICU strain per patch.

    per_patch=True reshapes a [patch] vector to [patch, 1] so it broadcasts over ages.
    """

    def __init__(self, name: str, default: float = 1.0, per_patch: bool = False,
                 transform: Callable[[np.ndarray], np.ndarray] | None = None):
        self.name, self.default, self.per_patch, self.transform = name, default, per_patch, transform

    def __call__(self, t, signals):
        if self.name not in signals:
            return self.default
        v = np.asarray(signals[self.name], dtype=float)
        if self.transform is not None:
            v = self.transform(v)
        if v.ndim == 0:
            return float(v)
        return v[:, None] if self.per_patch and v.ndim == 1 else v


class Product:
    def __init__(self, *providers: RateProvider):
        self.providers = providers

    def __call__(self, t, signals):
        out = 1.0
        for p in self.providers:
            out = out * p(t, signals)
        return out


class Clip:
    """Keeps a provider inside [low, high], e.g. a probability pushed above 1 by a multiplier."""

    def __init__(self, provider: RateProvider, low: float = 0.0, high: float = 1.0):
        self.provider, self.low, self.high = provider, low, high

    def __call__(self, t, signals):
        v = self.provider(t, signals)
        return float(np.clip(v, self.low, self.high)) if np.ndim(v) == 0 else np.clip(v, self.low, self.high)


class RateSet:
    """Named providers evaluated together at each substep."""

    def __init__(self, **providers: RateProvider):
        self.providers = dict(providers)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.providers)

    def evaluate(self, t: float, signals: Signals) -> dict[str, Value]:
        return {name: p(t, signals) for name, p in self.providers.items()}

    def replace(self, **overrides: RateProvider) -> "RateSet":
        return RateSet(**{**self.providers, **overrides})


def default_rates(disease, n_age: int, beta0: float,
                  contact_modifier: RateProvider | None = None,
                  ages: Sequence[str] | None = None) -> RateSet:
    """The standard rate set for seir() and seir_h() structures.

    beta = beta0 * contact_modifier(t); sigma and gamma come from the latent
    and infectious periods; p_hosp is scaled by disease.hosp_scale (capped at
    1); ward_exit and icu_exit are 1 / length of stay. Nothing here reads a
    feedback signal: wire those in with with_feedback() or a rate override.
    """
    def by_age(name):
        return disease.by_age(name, n_age, list(ages) if ages is not None else None)

    beta = Constant(beta0) if contact_modifier is None else Product(Constant(beta0), contact_modifier)
    return RateSet(
        beta=beta,
        sigma=Constant(disease.sigma),
        gamma=Constant(disease.gamma),
        p_hosp=Constant(np.minimum(by_age("p_hosp") * disease.hosp_scale, 1.0)),
        p_icu=Constant(by_age("p_icu")),
        p_death_icu=Constant(by_age("p_death_icu")),
        ward_exit=Constant(1.0 / disease.los_ward),
        icu_exit=Constant(1.0 / disease.los_icu),
    )


# ---- standard feedback channels ------------------------------------------
# signal name (in state.signals["seir"]) -> the rate it multiplies. Each signal
# is a multiplier, scalar or [patch], and leaves the rate unchanged when absent.
FEEDBACK: dict[str, str] = {
    "icu_mortality_multiplier": "p_death_icu",   # FDNA: ICU strain raises ICU deaths
    "hosp_multiplier": "p_hosp",                 # e.g. admission thresholds rise under strain
    "contact_multiplier": "beta",                # e.g. a policy or behaviour module
}
_PROBABILITIES = {"p_hosp", "p_icu", "p_death_icu"}


def with_feedback(rates: RateSet, signals: Iterable[str]) -> RateSet:
    """Wrap rates so the named feedback signals scale them (see FEEDBACK)."""
    overrides = {}
    for name in signals:
        if name not in FEEDBACK:
            raise ValueError(f"unknown feedback signal {name!r}; choose from {sorted(FEEDBACK)}")
        target = FEEDBACK[name]
        base = overrides.get(target, rates.providers[target])
        scaled = Product(base, Signal(name, default=1.0, per_patch=True))
        high = 1.0 if target in _PROBABILITIES else np.inf
        overrides[target] = Clip(scaled, 0.0, high)
    return rates.replace(**overrides)
