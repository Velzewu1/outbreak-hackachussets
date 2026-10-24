"""Facility-level historical backtest against HHS Suffolk COVID-occupied beds.

The integrated engine allocates admissions and retains cohorts PER HOSPITAL, so
facility-level COVID-occupied beds are direct model outputs. We evaluate at the
CCN level using the audited crosswalk (BIDMC_E + BIDMC_W -> 220086; the other
model hospitals map 1:1 to a CCN).

Calendar & split (fixed BEFORE masking): the FULL 35-week HHS calendar
(2020-10-04 .. 2021-05-30, uniform 7-day spacing) with the first 23 weeks as
train and the final 12 as holdout. Masking is applied PER (CCN, week): a record
is usable only if unsuppressed, finite, and coverage is sufficient. The SEIR
calendar is never compressed.

Scoring: one-week-ahead on the holdout. Model and persistence are scored on
IDENTICAL valid (CCN, week) keys. Persistence requires the EXACT 7-day predecessor
to also be valid. Every exclusion is recorded. Metric: MAE in beds.

Observation operator (weekly-batch approximation, DECLARED): within a modeled
weekly interval the committed epidemic cohorts are constant, so the model's
weekly-mean COVID-occupied beds equals its committed epidemic occupancy for that
week under this batch approximation. We compare that to the HHS
``inpatient_beds_used_covid_7_day_avg`` (a weekly mean). This is an explicit
approximation; if it cannot be defended for a given run the status is
``incomplete`` (never ``verified`` merely because lengths match).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

HOLDOUT_WEEKS = 12
# Require full weekly-mean support (all 7 reporting days). Records with coverage
# < 7 (or missing coverage) are masked, in addition to suppressed/missing values.
MIN_COVERAGE = 7

# model hospital_id -> CCN (BIDMC campuses aggregate to 220086)
MODEL_TO_CCN = {
    "MGH": "220071",
    "BWH": "220110",
    "BIDMC_W": "220086",
    "BIDMC_E": "220086",
    "BMC_MENINO": "220031",
    "BMC_BRIGHTON": "220036",
    "TUFTS": "220116",
    "FAULKNER": "220119",
    "NEBAPTIST": "220088",
}
INCLUDED_CCNS = sorted(set(MODEL_TO_CCN.values()))


def _d(s: str) -> date:
    y, m, dd = (int(x) for x in s.split("-"))
    return date(y, m, dd)


@dataclass
class BacktestResult:
    status: str
    notes: list = field(default_factory=list)
    calendar_weeks: int = 0
    train_weeks: int = 0
    holdout_weeks: int = 0
    matched_facilities: int = 0
    forecast_pairs: int = 0  # facility-week holdout pairs scored
    fitted_r0: float | None = None
    fitted_p_h: float | None = None
    model_mae_beds: float | None = None
    persistence_mae_beds: float | None = None
    regional_model_mae_beds: float | None = None
    regional_persistence_mae_beds: float | None = None
    per_facility: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    rollout_strategy: str = (
        "fixed-origin multi-week rollout: one simulation from week 0 with "
        "train-only fitted parameters; holdout weeks are read from that single "
        "trajectory (NOT rolling one-step data assimilation)"
    )
    observation_operator: str = (
        "weekly-batch: constant committed epidemic cohorts within a week => "
        "model weekly mean == committed epidemic occupancy (declared approximation)"
    )
    target_variable: str = "inpatient_beds_used_covid_7_day_avg (weekly mean, per facility CCN)"
    source_url: str = "https://healthdata.gov/resource/anag-cw7u.json"
    period: tuple = ("2020-10-04", "2021-05-30")


def _observed_by_ccn_week(observed: dict):
    """Return {(ccn, week): covid_mean or None} with suppression/coverage masking,
    plus the sorted full calendar and recorded exclusions."""
    rows = observed.get("rows", [])
    cal = sorted({r["week"] for r in rows})
    valid: dict[tuple, float] = {}
    exclusions = []
    for r in rows:
        if r["ccn"] not in INCLUDED_CCNS:
            continue
        key = (r["ccn"], r["week"])
        cov = r.get("coverage")
        if r["suppressed"] or r["covid_mean"] is None:
            exclusions.append(f"{key}: suppressed/missing")
            continue
        if cov is not None and cov < MIN_COVERAGE:
            exclusions.append(f"{key}: coverage {cov} < {MIN_COVERAGE}")
            continue
        valid[key] = float(r["covid_mean"])
    return valid, cal, exclusions


def run_backtest(observed: dict, model_facility_covid: dict | None) -> BacktestResult:
    """model_facility_covid: {(ccn, week): model_covid_beds} for ALL calendar weeks
    and all included CCNs. If None -> status incomplete (persistence only)."""
    notes: list[str] = []
    if observed.get("status") != "available":
        return BacktestResult("unavailable", ["HHS observed data not available"])

    valid, cal, exclusions = _observed_by_ccn_week(observed)
    notes.extend(exclusions[:50])
    if len(cal) < HOLDOUT_WEEKS + 3:
        return BacktestResult(
            "unavailable",
            notes + [f"only {len(cal)} calendar weeks"],
            calendar_weeks=len(cal),
        )

    # Split BEFORE masking, on the full calendar.
    train_cal = cal[: len(cal) - HOLDOUT_WEEKS]
    holdout_cal = cal[len(cal) - HOLDOUT_WEEKS :]

    # Build holdout one-week-ahead pairs with EXACT 7-day predecessor, per CCN.
    week_index = {w: i for i, w in enumerate(cal)}
    pairs = []  # (ccn, prev_week, week)
    for ccn in INCLUDED_CCNS:
        for w in holdout_cal:
            i = week_index[w]
            if i == 0:
                continue
            prev = cal[i - 1]
            if (_d(w) - _d(prev)).days != 7:
                notes.append(f"{(ccn, w)}: no 7-day predecessor; excluded")
                continue
            if (ccn, w) in valid and (ccn, prev) in valid:
                pairs.append((ccn, prev, w))
            else:
                notes.append(f"{(ccn, w)}: obs or predecessor masked; excluded")

    if not pairs:
        return BacktestResult(
            "unavailable",
            notes + ["no valid holdout facility-week pairs"],
            calendar_weeks=len(cal),
            train_weeks=len(train_cal),
            holdout_weeks=len(holdout_cal),
        )

    # Persistence on identical keys.
    persist_err = [abs(valid[(c, w)] - valid[(c, p)]) for (c, p, w) in pairs]
    persistence_mae = float(np.mean(persist_err))

    model_mae = None
    status = "incomplete"
    per_fac: dict = {}
    scored_rows: list = []
    if model_facility_covid is not None:
        # require model coverage for every scored key
        missing = [(c, w) for (c, _p, w) in pairs if (c, w) not in model_facility_covid]
        if missing:
            notes.append(f"model missing {len(missing)} scored keys; status incomplete")
        else:
            model_err = [abs(model_facility_covid[(c, w)] - valid[(c, w)]) for (c, _p, w) in pairs]
            model_mae = float(np.mean(model_err))
            status = "verified"
            for c, p, w in pairs:
                scored_rows.append(
                    {
                        "ccn": c,
                        "origin": p,
                        "target": w,
                        "model": model_facility_covid[(c, w)],
                        "observed": valid[(c, w)],
                        "persistence": valid[(c, p)],
                    }
                )
            # per-facility breakdown
            for ccn in INCLUDED_CCNS:
                ks = [(c, p, w) for (c, p, w) in pairs if c == ccn]
                if not ks:
                    continue
                me = np.mean(
                    [abs(model_facility_covid[(c, w)] - valid[(c, w)]) for (c, _p, w) in ks]
                )
                pe = np.mean([abs(valid[(c, w)] - valid[(c, p)]) for (c, p, w) in ks])
                per_fac[ccn] = {
                    "n": len(ks),
                    "model_mae": float(me),
                    "persistence_mae": float(pe),
                }

    # Secondary regional aggregate (sum over facilities) on weeks where ALL
    # included CCNs are valid in both w and predecessor.
    reg_model_mae = reg_persist_mae = None
    if model_facility_covid is not None and status == "verified":
        reg_pairs = []
        for w in holdout_cal:
            i = week_index[w]
            if i == 0:
                continue
            prev = cal[i - 1]
            if (_d(w) - _d(prev)).days != 7:
                continue
            if all((c, w) in valid and (c, prev) in valid for c in INCLUDED_CCNS):
                reg_pairs.append((prev, w))
        if reg_pairs:
            rm, rp = [], []
            for prev, w in reg_pairs:
                obs_w = sum(valid[(c, w)] for c in INCLUDED_CCNS)
                obs_p = sum(valid[(c, prev)] for c in INCLUDED_CCNS)
                mod_w = sum(model_facility_covid[(c, w)] for c in INCLUDED_CCNS)
                rm.append(abs(mod_w - obs_w))
                rp.append(abs(obs_p - obs_w))
            reg_model_mae = float(np.mean(rm))
            reg_persist_mae = float(np.mean(rp))

    return BacktestResult(
        status=status,
        notes=notes,
        calendar_weeks=len(cal),
        train_weeks=len(train_cal),
        holdout_weeks=len(holdout_cal),
        matched_facilities=len(INCLUDED_CCNS),
        forecast_pairs=len(pairs),
        model_mae_beds=model_mae,
        persistence_mae_beds=persistence_mae,
        regional_model_mae_beds=reg_model_mae,
        regional_persistence_mae_beds=reg_persist_mae,
        per_facility=per_fac,
        rows=scored_rows,
    )
