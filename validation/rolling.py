"""Rolling-origin one-week-ahead evaluation with expanding-window TRAIN fitting.

Genuine next-week hospital forecast per the primary plan. For each origin week
``o`` in the holdout, R0 is fitted using observations ONLY through week ``o``
(expanding window); the model is rolled to produce the week ``o+1`` facility
COVID-occupied prediction. The target week is NEVER in the fit (leakage-free).
p_H and the seed fraction are fixed (not identifiable here). Scored on the SAME
(CCN, week) keys as persistence, with exact 7-day predecessor.

This is heavier than the fixed-origin rollout (one fit per origin), so it runs a
bounded coarse R0 search per origin. Both strategies are reported separately;
neither is tuned to the holdout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .backtest import INCLUDED_CCNS, MODEL_TO_CCN, _d, _observed_by_ccn_week

R0_GRID = [1.6, 1.9, 2.1, 2.3, 2.5, 2.8, 3.1]  # bounded, coarse; same for every origin


@dataclass
class RollingResult:
    status: str
    notes: list = field(default_factory=list)
    origins: list = field(default_factory=list)  # [{origin, target, fitted_r0}]
    forecast_pairs: int = 0
    model_mae_beds: float | None = None
    persistence_mae_beds: float | None = None
    leakage_free: bool = True
    rows: list = field(default_factory=list)
    strategy: str = (
        "rolling-origin 1-week-ahead; expanding-window train fit per origin using "
        "observations only through the origin week; target week never in fit"
    )


def train_window_mae(series_by_week, calendar, valid, upto_idx):
    """Mean absolute error of one R0's model series vs observed over weeks
    0..upto_idx (inclusive). This is the ONLY fit objective used by the rolling
    evaluation; tests exercise it directly to prove leakage-freedom."""
    import numpy as _np

    errs = []
    for c in INCLUDED_CCNS:
        for i in range(0, upto_idx + 1):
            w = calendar[i]
            if (c, w) in valid:
                errs.append(abs(series_by_week[w][c] - valid[(c, w)]))
    return float(_np.mean(errs)) if errs else float("inf")


def select_r0(r0_grid, series_by_r0, calendar, valid, origin_idx):
    """Pick R0 minimizing train-window MAE through the origin week ONLY (no
    observations after the origin are read)."""
    return min(
        r0_grid, key=lambda r0: train_window_mae(series_by_r0[r0], calendar, valid, origin_idx)
    )


def _facility_covid(run_get_week, run, calendar, week_index):
    """Map one week's model output to {ccn: covid_beds}."""
    v = run_get_week(run, week_index, "after")
    out = {c: 0.0 for c in INCLUDED_CCNS}
    for h in v["hospitals"]:
        ccn = MODEL_TO_CCN.get(h["hospital_id"])
        if ccn is None:
            continue
        out[ccn] += max(0.0, h["committed_beds"] - h["baseline_beds"])
    return out


def run_rolling(
    observed: dict, api_module, seed_frac: float = 0.0015, p_h: float = 0.03
) -> RollingResult:
    valid, cal, _excl = _observed_by_ccn_week(observed)
    if len(cal) < 15:
        return RollingResult("unavailable", ["too few calendar weeks"])
    holdout_start = len(cal) - 12

    # precompute model facility series for each candidate R0 over the full calendar
    # (one simulation per R0; reused across origins). seed/p_h fixed.
    series_by_r0: dict[float, dict] = {}
    for r0 in R0_GRID:
        cfg = api_module.RunConfig(
            disease=api_module.DiseaseConfig(r0=r0, p_h=p_h, initial_infectious_fraction=seed_frac),
            weeks=len(cal),
            nearest_outside_radius_fallback=True,
        )
        run = api_module.run_scenario(api_module.load_inputs("real", cfg), [])
        series_by_r0[r0] = {
            cal[i]: _facility_covid(api_module.get_week, run, cal, i) for i in range(len(cal))
        }

    def train_mae(r0, upto_idx):
        return train_window_mae(series_by_r0[r0], cal, valid, upto_idx)

    origins = []
    model_err = []
    persist_err = []
    rows = []  # scored prediction/observed/persistence rows for charts + recompute
    for o in range(holdout_start - 1, len(cal) - 1):
        origin_w = cal[o]
        target_w = cal[o + 1]
        if (_d(target_w) - _d(origin_w)).days != 7:
            continue
        # expanding-window fit using observations ONLY through origin week o.
        fit_window = cal[: o + 1]  # inclusive of origin; target_w (o+1) excluded
        best_r0 = select_r0(R0_GRID, series_by_r0, cal, valid, o)
        s = series_by_r0[best_r0]
        for c in INCLUDED_CCNS:
            if (c, target_w) in valid and (c, origin_w) in valid:
                pred = s[target_w][c]
                obs_t = valid[(c, target_w)]
                obs_o = valid[(c, origin_w)]
                model_err.append(abs(pred - obs_t))
                persist_err.append(abs(obs_t - obs_o))
                rows.append(
                    {
                        "ccn": c,
                        "origin": origin_w,
                        "target": target_w,
                        "model": pred,
                        "observed": obs_t,
                        "persistence": obs_o,
                        "fitted_r0": best_r0,
                    }
                )
        origins.append(
            {
                "origin": origin_w,
                "target": target_w,
                "fit_window_end": fit_window[-1],
                "fit_window_len": len(fit_window),
                "fitted_r0": best_r0,
            }
        )

    if not model_err:
        return RollingResult("unavailable", ["no valid rolling pairs"])
    return RollingResult(
        status="verified",
        origins=origins,
        forecast_pairs=len(model_err),
        model_mae_beds=float(np.mean(model_err)),
        persistence_mae_beds=float(np.mean(persist_err)),
        leakage_free=True,  # by construction: fit window ends at origin < target
        rows=rows,
    )
