"""Fit physical disease parameters on TRAIN weeks only and produce per-facility
model COVID-occupied-bed series for the backtest.

The model's COVID-occupied beds at a hospital for a week = committed epidemic
occupancy = committed - baseline (served epidemic cohorts, capacity-bounded by
construction). Campuses are aggregated to CCN via the backtest crosswalk.

Fitting: minimise TRAIN-only occupied-bed MAE (summed over included CCNs, over
train weeks) over R0 in a bounded range, using the SAME public simulation API and
observation operator used for scoring. p_H is kept FIXED at its config value
(not defensibly identifiable from this target alone) unless explicitly enabled.
No post-hoc scaling of the capacity-constrained output.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar

from pipeline import api
from pipeline.contracts import DiseaseConfig, RunConfig

from .backtest import INCLUDED_CCNS, MODEL_TO_CCN


def _model_facility_covid(
    r0: float, p_h: float, weeks: int, seed_frac: float, calendar: list[str]
) -> dict:
    """Run the engine over `weeks` intervals; return {(ccn, week): covid_beds}
    aligned to `calendar` (first len(calendar) weeks)."""
    cfg = RunConfig(
        disease=DiseaseConfig(r0=r0, p_h=p_h, initial_infectious_fraction=seed_frac),
        weeks=weeks,
        # Real Suffolk needs the documented nearest-outside-radius fallback for the
        # one NE peninsula tract; load_inputs(real) honors the configured policy.
        nearest_outside_radius_fallback=True,
    )
    inp = api.load_inputs("real", cfg)
    run = api.run_scenario(inp, [])
    out: dict[tuple, float] = {}
    for wk in run.weeks:
        if wk.week >= len(calendar):
            break
        week_label = calendar[wk.week]
        v = api.get_week(run, wk.week, "after")
        ccn_tot: dict[str, float] = {c: 0.0 for c in INCLUDED_CCNS}
        for h in v["hospitals"]:
            ccn = MODEL_TO_CCN.get(h["hospital_id"])
            if ccn is None:
                continue
            covid = max(0.0, h["committed_beds"] - h["baseline_beds"])
            ccn_tot[ccn] += covid
        for c, val in ccn_tot.items():
            out[(c, week_label)] = val
    return out


def _train_mae(model_fac: dict, valid: dict, train_weeks: list[str]) -> float:
    errs = []
    for c in INCLUDED_CCNS:
        for w in train_weeks:
            if (c, w) in valid and (c, w) in model_fac:
                errs.append(abs(model_fac[(c, w)] - valid[(c, w)]))
    return float(np.mean(errs)) if errs else float("inf")


def fit_r0(
    valid: dict,
    calendar: list[str],
    train_weeks: list[str],
    seed_frac: float = 0.0015,
    p_h: float = 0.03,
) -> dict:
    """Fit R0 by minimising TRAIN-only occupied-bed MAE. p_H fixed."""
    n = len(calendar)

    def loss(r0):
        mf = _model_facility_covid(r0, p_h, n, seed_frac, calendar)
        return _train_mae(mf, valid, train_weeks)

    res = minimize_scalar(loss, bounds=(1.3, 3.5), method="bounded", options={"xatol": 0.05})
    return {
        "fitted_r0": float(res.x),
        "train_mae_beds": float(res.fun),
        "seed_frac": seed_frac,
        "p_h_fixed": p_h,
    }


def facility_series(r0: float, p_h: float, calendar: list[str], seed_frac: float) -> dict:
    return _model_facility_covid(r0, p_h, len(calendar), seed_frac, calendar)
