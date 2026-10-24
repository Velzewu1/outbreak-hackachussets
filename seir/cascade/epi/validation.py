"""Scoring a model against what happened, with the pass bars from the project writeup.

  Metric                     Pass bar
  Weekly COVID inpatients    within +-40% of observed for at least 60% of weeks
  Peak timing and height     peak week within +-1 week; height within +-25%
  Which hospitals strained   Spearman rho >= 0.6; top 3 overlap by at least 2

The first two apply to any weekly series (inpatients, admissions); the third
compares per-hospital peaks once allocation exists, and works on any two
equally indexed vectors. backtest() is the "fit the first half, predict the
second half" check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .calibrate import Param, aligned, fit_scenario, infer_window
from .config import ScenarioConfig


@dataclass(frozen=True)
class Check:
    name: str
    value: float
    bar: str
    passed: bool


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)
    title: str = ""

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([vars(c) for c in self.checks])

    def to_dict(self) -> dict:
        return {"title": self.title, "passed": self.passed,
                "checks": [{**vars(c), "value": float(c.value)} for c in self.checks]}

    def __str__(self) -> str:
        width = max([len(c.name) for c in self.checks] + [10])
        lines = [self.title] if self.title else []
        for c in self.checks:
            mark = "PASS" if c.passed else "FAIL"
            lines.append(f"  {mark}  {c.name:<{width}}  {c.value:>8.3g}   ({c.bar})")
        lines.append(f"  {'PASS' if self.passed else 'FAIL'}  overall")
        return "\n".join(lines)


def _paired(model: pd.Series, observed: pd.Series) -> tuple[pd.Series, pd.Series]:
    both = pd.concat({"m": model.astype(float), "o": observed.astype(float)}, axis=1).dropna()
    if both.empty:
        raise ValueError("model and observed share no dates with values")
    return both["m"], both["o"]


def share_within(model: pd.Series, observed: pd.Series, tol: float = 0.40) -> float:
    """Share of dates where the model is within +-tol of the observed value (observed > 0)."""
    m, o = _paired(model, observed)
    ok = o > 0
    if not ok.any():
        raise ValueError("observed has no positive values")
    return float((np.abs(m[ok] - o[ok]) <= tol * o[ok]).mean())


def peak_offset(model: pd.Series, observed: pd.Series) -> int:
    """Model peak position minus observed peak position, in steps (weeks for weekly data)."""
    m, o = _paired(model, observed)
    idx = list(m.index)
    return idx.index(m.idxmax()) - idx.index(o.idxmax())


def peak_height_error(model: pd.Series, observed: pd.Series) -> float:
    """(model peak - observed peak) / observed peak."""
    m, o = _paired(model, observed)
    return float((m.max() - o.max()) / o.max())


def score(model: pd.Series, observed: pd.Series, tol: float = 0.40) -> dict:
    """Error metrics for comparing models (e.g. against an SEIR-only baseline)."""
    m, o = _paired(model, observed)
    err = m - o
    return {
        "n": int(len(o)),
        "mae": float(np.abs(err).mean()),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "bias": float(err.mean()),
        "mape": float((np.abs(err[o > 0]) / o[o > 0]).mean()),
        "log_rmse": float(np.sqrt(((np.log1p(m.clip(lower=0)) - np.log1p(o)) ** 2).mean())),
        "share_within": share_within(m, o, tol),
        "peak_offset": peak_offset(m, o),
        "peak_height_error": peak_height_error(m, o),
    }


def validate_series(model: pd.Series, observed: pd.Series, tol: float = 0.40,
                    min_share: float = 0.60, peak_steps: int = 1, peak_tol: float = 0.25,
                    title: str = "") -> ValidationReport:
    """The writeup's inpatient bars, for any two series on the same (weekly) dates."""
    within = share_within(model, observed, tol)
    offset = peak_offset(model, observed)
    height = peak_height_error(model, observed)
    return ValidationReport([
        Check(f"weeks within +-{tol:.0%}", within, f">= {min_share:.0%} of weeks", within >= min_share),
        Check("peak week offset", offset, f"within +-{peak_steps}", abs(offset) <= peak_steps),
        Check("peak height error", height, f"within +-{peak_tol:.0%}", abs(height) <= peak_tol),
    ], title)


def validate_ranking(model: Mapping[str, float] | pd.Series, observed: Mapping[str, float] | pd.Series,
                     min_rho: float = 0.6, k: int = 3, min_overlap: int = 2,
                     title: str = "") -> ValidationReport:
    """The writeup's strain-ranking bars: Spearman rho and top-k overlap (e.g. hospitals by peak occupancy)."""
    m, o = _paired(pd.Series(model), pd.Series(observed))
    rho = float(spearmanr(m, o).statistic)
    overlap = len(set(m.nlargest(k).index) & set(o.nlargest(k).index))
    return ValidationReport([
        Check("Spearman rho", rho, f">= {min_rho}", rho >= min_rho),
        Check(f"top-{k} overlap", overlap, f">= {min_overlap}", overlap >= min_overlap),
    ], title)


@dataclass
class Backtest:
    fit: object                      # FitResult from the first part
    train: pd.DataFrame              # observed and model on the fitted dates
    test: pd.DataFrame               # observed and model after the split
    metrics: dict                    # score() on the test part
    report: ValidationReport         # validate_series() on the test part


def backtest(cfg: ScenarioConfig, observed: pd.Series, params: Mapping[str, Param],
             split, variable: str = "new_hosp", **fit_kwargs) -> Backtest:
    """Fit on observations up to `split`, predict the rest, and score the prediction.

    This is the honest test for a decision-support tool: the model never sees
    the weeks it is judged on.
    """
    observed = observed.astype(float)
    split = pd.Timestamp(split)
    train_obs = observed[observed.index <= split]
    test_obs = observed[observed.index > split]
    if train_obs.dropna().empty or test_obs.dropna().empty:
        raise ValueError("split must leave observations on both sides")
    window = fit_kwargs.pop("window", None)
    label = fit_kwargs.get("label", "end")
    window = window or infer_window(pd.DatetimeIndex(observed.index))
    last = observed.index.max() + (pd.Timedelta(days=window - 1) if label == "start" else pd.Timedelta(0))
    days = int((last - pd.Timestamp(cfg.sim.start)).days) + 1
    fit = fit_scenario(cfg, train_obs, params, variable=variable, window=window, days=days, **fit_kwargs)
    how = fit.extra["how"]
    daily = fit.result.series(variable, patches=fit_kwargs.get("patches"))

    def frame(obs: pd.Series) -> pd.DataFrame:
        return pd.DataFrame({"observed": obs,
                             "model": aligned(daily, pd.DatetimeIndex(obs.index), window, label, how)},
                            index=obs.index)

    train, test = frame(train_obs), frame(test_obs)
    return Backtest(fit, train, test, score(test["model"], test["observed"]),
                    validate_series(test["model"], test["observed"], title="held-out weeks"))
