"""Rolling-origin leakage tests exercising PRODUCTION code (validation.rolling).

Two levels:
1. Unit: production ``select_r0`` / ``train_window_mae`` are invariant to
   perturbing observations AFTER the origin week.
2. Integration: production ``run_rolling`` with a tiny fake public-API module
   (fixed model series per R0) — perturbing a future observation does not change
   a given origin's recorded R0/forecast.
"""

from __future__ import annotations

import copy
import types

import numpy as np

from validation import rolling
from validation.backtest import INCLUDED_CCNS


def _toy_series(cal, rng):
    return {w: {c: float(rng.uniform(5, 50)) for c in INCLUDED_CCNS} for w in cal}


def test_select_r0_invariant_to_future_perturbation():
    cal = [f"2020-{m:02d}-01" for m in range(1, 13)]
    rng = np.random.default_rng(0)
    grid = [1.6, 2.1, 2.6, 3.1]
    series_by_r0 = {r0: _toy_series(cal, np.random.default_rng(int(r0 * 10))) for r0 in grid}
    valid = {(c, w): float(rng.uniform(5, 50)) for c in INCLUDED_CCNS for w in cal}
    o = 6
    before = rolling.select_r0(grid, series_by_r0, cal, valid, o)
    mae_before = rolling.train_window_mae(series_by_r0[before], cal, valid, o)

    valid2 = copy.deepcopy(valid)
    for c in INCLUDED_CCNS:
        valid2[(c, cal[9])] += 1000.0  # perturb FUTURE week (index 9 > origin 6)
    after = rolling.select_r0(grid, series_by_r0, cal, valid2, o)
    mae_after = rolling.train_window_mae(series_by_r0[after], cal, valid2, o)

    assert before == after
    assert abs(mae_before - mae_after) < 1e-12


def _fake_api(series_by_r0, cal):
    """Minimal stand-in for pipeline.api used by run_rolling."""
    import dataclasses

    @dataclasses.dataclass
    class _Disease:
        r0: float
        p_h: float
        initial_infectious_fraction: float

    @dataclasses.dataclass
    class _Cfg:
        disease: _Disease
        weeks: int
        nearest_outside_radius_fallback: bool

    mod = types.SimpleNamespace()
    mod.RunConfig = lambda disease, weeks, nearest_outside_radius_fallback: _Cfg(
        disease, weeks, nearest_outside_radius_fallback
    )
    mod.DiseaseConfig = lambda r0, p_h, initial_infectious_fraction: _Disease(
        r0, p_h, initial_infectious_fraction
    )
    mod.load_inputs = lambda mode, cfg: ("inp", cfg)
    mod.run_scenario = lambda inp, injs: inp[1]  # carries cfg

    def get_week(run_cfg, week_index, phase):
        r0 = run_cfg.disease.r0
        # snap to nearest grid r0 present in series_by_r0
        key = min(series_by_r0, key=lambda g: abs(g - r0))
        wk = cal[week_index]
        return {
            "hospitals": [
                {
                    "hospital_id": _ccn_to_model(c),
                    "committed_beds": series_by_r0[key][wk][c],
                    "baseline_beds": 0.0,
                }
                for c in INCLUDED_CCNS
            ]
        }

    mod.get_week = get_week
    return mod


def _ccn_to_model(ccn):
    # map a CCN back to one model id (inverse of MODEL_TO_CCN; any one works since
    # BIDMC campuses both map to 220086 — pick a representative)
    for mid, c in rolling.MODEL_TO_CCN.items():
        if c == ccn:
            return mid
    return ccn


def test_run_rolling_integration_leakage_free(monkeypatch):
    # 20-week calendar so holdout (12) + origins exist
    cal = [f"2021-{(1 + i // 4):02d}-{(1 + 7 * (i % 4)):02d}" for i in range(20)]
    # ensure uniform 7-day spacing by building real dates
    from datetime import date, timedelta

    start = date(2020, 10, 4)
    cal = [(start + timedelta(days=7 * i)).isoformat() for i in range(20)]
    grid = rolling.R0_GRID
    series_by_r0 = {r0: _toy_series(cal, np.random.default_rng(int(r0 * 100))) for r0 in grid}
    valid = {
        (c, w): float(np.random.default_rng(1).uniform(5, 50)) for c in INCLUDED_CCNS for w in cal
    }
    observed = {
        "status": "available",
        "rows": [
            {
                "ccn": c,
                "week": w,
                "covid_mean": valid[(c, w)],
                "used_mean": 100.0,
                "coverage": 7,
                "suppressed": False,
            }
            for c in INCLUDED_CCNS
            for w in cal
        ],
    }

    fake = _fake_api(series_by_r0, cal)
    # precompute the same series the code will build (one sim per R0) via fake api
    res1 = rolling.run_rolling(observed, fake)
    assert res1.status == "verified"
    assert res1.leakage_free is True
    assert res1.forecast_pairs > 0
    # recorded origins carry fit_window_end < target and an R0
    for o in res1.origins:
        assert o["origin"] < o["target"]
        assert o["fitted_r0"] in grid

    # perturb a FUTURE observation relative to the FIRST origin, rerun, and confirm
    # the first origin's recorded R0 is unchanged.
    first = res1.origins[0]
    first_origin_idx = cal.index(first["origin"])
    future_idx = min(len(cal) - 1, first_origin_idx + 3)
    observed2 = copy.deepcopy(observed)
    for row in observed2["rows"]:
        if row["week"] == cal[future_idx]:
            row["covid_mean"] += 1000.0
    res2 = rolling.run_rolling(observed2, fake)
    first2 = next(o for o in res2.origins if o["origin"] == first["origin"])
    assert first2["fitted_r0"] == first["fitted_r0"]
