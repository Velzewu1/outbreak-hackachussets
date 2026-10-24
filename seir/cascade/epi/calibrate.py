"""Fit scenario parameters to observed series (e.g. HHS weekly admissions).

Two levels:

  calibrate()     the general one: you supply simulate(params) -> SEIRResult
                  and target(result) -> array, as in the SEIR guide
  fit_scenario()  the convenient one: parameters are dotted paths into a
                  ScenarioConfig ("disease.r0", "seeding.exposed.Boston"),
                  and observed data is a dated pandas Series
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .config import ScenarioConfig
from .results import SEIRResult
from .structure import seir_h


@dataclass
class Param:
    initial: float
    low: float
    high: float
    log: bool = False      # search on a log scale, for values spanning orders of magnitude (seeds)

    def __post_init__(self):
        if not self.low <= self.initial <= self.high:
            raise ValueError(f"initial {self.initial} is outside [{self.low}, {self.high}]")
        if self.log and self.low <= 0:
            raise ValueError("a log-scale parameter needs a positive lower bound")


@dataclass
class FitResult:
    params: dict[str, float]
    result: SEIRResult
    cost: float
    success: bool
    nfev: int = 0
    message: str = ""
    model: np.ndarray | None = None        # fitted target, same length as observed
    observed: np.ndarray | None = None
    config: ScenarioConfig | None = None   # fit_scenario only: the scenario with fitted values
    extra: dict = field(default_factory=dict)


def calibrate(simulate: Callable[[dict[str, float]], SEIRResult],
              target: Callable[[SEIRResult], np.ndarray],
              observed: np.ndarray,
              params: dict[str, Param],
              loss: str = "log1p",
              weights: np.ndarray | None = None,
              **least_squares_kwargs) -> FitResult:
    """Least squares on log1p counts (by default), so small and large weeks both matter.

    simulate: builds and runs a scenario from a dict of parameter values.
    target:   pulls the series to compare from a result (same length as observed).
    observed: NaN entries (missing weeks) are left out of the fit.
    loss:     "log1p" (default) or "linear".
    """
    names = list(params)
    observed = np.asarray(observed, dtype=float)
    keep = np.isfinite(observed)
    if not keep.any():
        raise ValueError("observed has no finite values")
    w = np.ones_like(observed) if weights is None else np.asarray(weights, dtype=float)
    if loss == "log1p":
        transform = np.log1p
    elif loss == "linear":
        transform = np.asarray
    else:
        raise ValueError("loss must be 'log1p' or 'linear'")
    to_x = [np.log if params[n].log else (lambda v: v) for n in names]
    from_x = [np.exp if params[n].log else (lambda v: v) for n in names]

    def values(x) -> dict[str, float]:
        return {n: float(f(v)) for n, f, v in zip(names, from_x, x)}

    def residuals(x):
        model = np.asarray(target(simulate(values(x))), dtype=float)
        if model.shape != observed.shape:
            raise ValueError(f"target returned shape {model.shape}, observed is {observed.shape}")
        return ((transform(np.maximum(model, 0.0)) - transform(observed)) * w)[keep]

    least_squares_kwargs.setdefault("x_scale", "jac")
    fit = least_squares(
        residuals,
        x0=[f(params[n].initial) for n, f in zip(names, to_x)],
        bounds=([f(params[n].low) for n, f in zip(names, to_x)],
                [f(params[n].high) for n, f in zip(names, to_x)]),
        **least_squares_kwargs,
    )
    best = values(fit.x)
    result = simulate(best)
    return FitResult(best, result, float(fit.cost), bool(fit.success), int(fit.nfev),
                     str(fit.message), np.asarray(target(result), dtype=float), observed)


# ---- fitting a scenario to a dated series --------------------------------------
def infer_window(index: pd.DatetimeIndex) -> int:
    """Days covered by each observation: 7 for weekly data, 1 for daily."""
    if len(index) < 2:
        return 1
    step = pd.Series(index).diff().dropna().dt.days.median()
    return int(step) if step in (1, 7) else 1


def aligned(daily: pd.Series, dates: pd.DatetimeIndex, window: int = 1, label: str = "end",
            how: str = "sum") -> np.ndarray:
    """Model values matching each observation: the `window` days ending (or starting) on each date.

    NaN where the window is not fully inside the simulated period.
    """
    if label not in ("start", "end"):
        raise ValueError("label must be 'start' or 'end'")
    if how not in ("sum", "mean"):
        raise ValueError("how must be 'sum' or 'mean'")
    days = pd.DatetimeIndex(daily.index).normalize()
    csum = np.concatenate([[0.0], np.cumsum(daily.to_numpy(dtype=float))])
    first = days[0]
    out = np.full(len(dates), np.nan)
    for i, d in enumerate(pd.DatetimeIndex(dates).normalize()):
        start = d - pd.Timedelta(days=window - 1) if label == "end" else d
        a = (start - first).days
        b = a + window
        if a >= 0 and b <= len(days):
            total = csum[b] - csum[a]
            out[i] = total if how == "sum" else total / window
    return out


def fit_scenario(cfg: ScenarioConfig, observed: pd.Series, params: Mapping[str, Param],
                 variable: str = "new_hosp", window: int | None = None, label: str = "end",
                 how: str | None = None, days: int | None = None, loss: str = "log1p",
                 patches=None, engine_kwargs: Mapping | None = None,
                 **least_squares_kwargs) -> FitResult:
    """Fit config values to a dated series, e.g. HHS weekly admissions.

    params:   {"disease.r0": Param(2.5, 1.2, 5.0), "seeding.exposed.Boston": Param(100, 1, 1e4, log=True)}
    observed: values indexed by date; each date labels `window` days ending
              (label="end") or starting (label="start") on it. window is
              inferred (7 for weekly data) when not given.
    variable: a count from SEIRResult.series: "new_hosp", "inpatients", "icu",
              "new_deaths", "infections", ... Flows are summed over the
              window, counts averaged (override with `how`).
    days:     how long to simulate; by default up to the last observation.
    patches:  only these patches count towards the target (default: all).
    """
    from .engine import SEIREngine

    observed = observed.astype(float)
    dates = pd.DatetimeIndex(observed.index)
    window = window or infer_window(dates)
    engine_kwargs = dict(engine_kwargs or {})
    stocks = set((engine_kwargs.get("structure") or seir_h()).compartments) | {"inpatients", "icu", "infectious"}
    how = how or ("mean" if variable in stocks else "sum")
    start = pd.Timestamp(cfg.sim.start)
    last = dates.max() + (pd.Timedelta(days=window - 1) if label == "start" else pd.Timedelta(0))
    days = days or int((last - start).days) + 1
    if days <= 0:
        raise ValueError("every observation is before sim.start")

    def configure(values: dict[str, float]) -> ScenarioConfig:
        return cfg.updated(values) if values else cfg

    def simulate(values: dict[str, float]) -> SEIRResult:
        c = configure(values)
        return SEIREngine.from_config(c, **engine_kwargs).run(c.seeding, days)

    def target(res: SEIRResult) -> np.ndarray:
        daily = res.series(variable, patches=patches)
        return aligned(daily, dates, window, label, how)

    probe = aligned(pd.Series(np.zeros(days), index=pd.date_range(start, periods=days)),
                    dates, window, label, how)
    inside = np.isfinite(probe)
    if not inside.any():
        raise ValueError("no observation window lies inside the simulated period")
    obs = np.where(inside, observed.to_numpy(), np.nan)
    fit = calibrate(simulate, target, obs, dict(params), loss=loss, **least_squares_kwargs)
    fit.config = configure(fit.params)
    fit.extra.update(variable=variable, window=window, label=label, how=how, days=days,
                     dates=dates)
    return fit


def fitted_series(fit: FitResult) -> pd.DataFrame:
    """Observed and fitted values side by side, indexed by the observation dates."""
    return pd.DataFrame({"observed": fit.observed, "model": fit.model},
                        index=pd.DatetimeIndex(fit.extra.get("dates", range(len(fit.observed)))))
