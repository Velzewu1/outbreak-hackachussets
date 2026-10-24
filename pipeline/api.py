"""Public API facade — the ONLY module the Streamlit app imports from the engine.

Exposes dataset discovery, input building, scenario runs, comparison, per-week
flat views, and exports. No model math lives here; it delegates to the runner.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

from .accessibility import build_accessibility
from .config import run_config_from_dict
from .contracts import (  # re-exported public config/injection types
    DataValidationError as _DVE,
)
from .contracts import (
    DiseaseConfig,
    Injection,
    InvalidInjection,
    NetworkConfig,
    RunConfig,
)
from .data import DataBundle, golden_fixture, synthetic_spatial
from .runner import ValidatedInputs, simulate_run
from .types import RunResult, WeekResult

__all__ = [
    "DiseaseConfig",
    "Injection",
    "InvalidInjection",
    "NetworkConfig",
    "RunConfig",
    "available_datasets",
    "build_inputs",
    "compare_scenarios",
    "export_csv",
    "export_json",
    "get_week",
    "list_hospitals",
    "list_weeks",
    "load_inputs",
    "make_injection",
    "run_config_from_dict",
    "run_scenario",
]


def make_injection(injection_id, kind, start_week, payload, end_week=None, note=""):
    """Public constructor so the app never imports pipeline.contracts directly."""
    return Injection(injection_id, kind, start_week, dict(payload), end_week, note).validate()


def list_hospitals(inputs: ValidatedInputs) -> list[dict]:
    return [
        {
            "hospital_id": h.hospital_id,
            "name": h.name,
            "lat": h.lat,
            "lon": h.lon,
            "staffed_beds": h.staffed_beds,
            "icu_beds": h.icu_beds,
        }
        for h in inputs.hospitals
    ]


def list_weeks(run: RunResult) -> list[int]:
    return [w.week for w in run.weeks]


def district_geojson(inputs: ValidatedInputs) -> dict:
    """GeoJSON FeatureCollection of modeled district polygons/centroids for the
    map. Geometry is real when present (real mode) else a small square proxy
    (synthetic). Centroids always present."""
    feats = []
    for d in inputs.districts:
        geom = d.geometry
        if geom is None:
            # synthetic square proxy centered on the centroid (clearly synthetic)
            e = 0.004
            geom = {
                "type": "Polygon",
                "coordinates": [
                    [
                        [d.centroid_lon - e, d.centroid_lat - e],
                        [d.centroid_lon + e, d.centroid_lat - e],
                        [d.centroid_lon + e, d.centroid_lat + e],
                        [d.centroid_lon - e, d.centroid_lat + e],
                        [d.centroid_lon - e, d.centroid_lat - e],
                    ]
                ],
            }
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "district_id": d.district_id,
                    "population": d.population,
                    "risk_weight": d.risk_weight,
                    "ej_flag": d.ej_flag,
                    "centroid_lat": d.centroid_lat,
                    "centroid_lon": d.centroid_lon,
                },
                "geometry": geom,
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def data_manifest(run: RunResult) -> dict:
    return dict(run.data_manifest)


# --------------------------------------------------------------------------- #
# Historical evaluation (exposed through the API; app never reads artifacts)
# --------------------------------------------------------------------------- #

_EVAL_ARTIFACT = "artifacts/evaluation.json"


def evaluation_report() -> dict:
    """Return the precomputed historical evaluation (fixed-origin + rolling-origin
    facility-level backtests vs persistence). Reads the offline artifact produced
    by scripts/run_backtest.py. If absent, returns a status=unavailable payload.
    The app calls THIS, never the artifact file directly."""
    import json as _json
    import os as _os

    if not _os.path.exists(_EVAL_ARTIFACT):
        return {
            "status": "unavailable",
            "reason": "evaluation artifact not computed; run scripts/run_backtest.py",
        }
    with open(_EVAL_ARTIFACT) as f:
        return _json.load(f)


def compute_evaluation() -> dict:
    """Compute both evaluation strategies and return a combined report. Heavy
    (runs the engine many times); intended for scripts/run_backtest.py, not the UI."""
    import sys as _sys

    from validation import rolling
    from validation.backtest import (
        HOLDOUT_WEEKS,
        _observed_by_ccn_week,
        run_backtest,
    )
    from validation.fit import facility_series, fit_r0

    from .data_real import _load_hhs_observed, real_available

    if not real_available():
        return {"status": "unavailable", "reason": "real data not present"}
    obs = _load_hhs_observed()
    valid, cal, excl = _observed_by_ccn_week(obs)
    train_weeks = cal[: len(cal) - HOLDOUT_WEEKS]

    fit = fit_r0(valid, cal, train_weeks, seed_frac=0.0015, p_h=0.03)
    mf = facility_series(fit["fitted_r0"], fit["p_h_fixed"], cal, fit["seed_frac"])
    fixed = run_backtest(obs, mf)

    roll = rolling.run_rolling(obs, _sys.modules[__name__])

    return {
        "status": "verified" if fixed.status == "verified" else fixed.status,
        "source_url": fixed.source_url,
        "period": list(fixed.period),
        "calendar_weeks": fixed.calendar_weeks,
        "train_weeks": fixed.train_weeks,
        "holdout_weeks": fixed.holdout_weeks,
        "matched_facilities": fixed.matched_facilities,
        "min_coverage_days": 7,
        "excluded_records": len(excl),
        "fixed_origin": {
            "strategy": fixed.rollout_strategy,
            "observation_operator": fixed.observation_operator,
            "forecast_pairs": fixed.forecast_pairs,
            "model_mae_beds": fixed.model_mae_beds,
            "persistence_mae_beds": fixed.persistence_mae_beds,
            "regional_model_mae_beds": fixed.regional_model_mae_beds,
            "regional_persistence_mae_beds": fixed.regional_persistence_mae_beds,
            "per_facility": fixed.per_facility,
            "rows": fixed.rows,
            "fit": fit,
        },
        "rolling_origin": {
            "strategy": roll.strategy,
            "status": roll.status,
            "forecast_pairs": roll.forecast_pairs,
            "model_mae_beds": roll.model_mae_beds,
            "persistence_mae_beds": roll.persistence_mae_beds,
            "leakage_free": roll.leakage_free,
            "origins": roll.origins,
            "rows": roll.rows,
        },
        "honest_note": "Both strategies' model MAE exceed the persistence baseline; "
        "reported as measured. No tuning to the holdout.",
    }


# --------------------------------------------------------------------------- #
# Dataset discovery + input building
# --------------------------------------------------------------------------- #


@dataclass
class DatasetSummary:
    name: str
    data_mode: str
    n_districts: int
    n_hospitals: int
    has_observed: bool


def available_datasets() -> list[DatasetSummary]:
    out = [
        DatasetSummary("golden", "synthetic_demo", 3, 3, False),
        DatasetSummary("synthetic", "synthetic_demo", 24, 6, False),
    ]
    # Real dataset availability is probed lazily by load_inputs("real").
    try:
        from .data_real import real_available

        if real_available():
            out.append(DatasetSummary("real", "mixed_assumptions", 0, 0, True))
    except Exception:
        pass
    return out


def build_inputs(
    bundle: DataBundle,
    config: RunConfig | None = None,
) -> ValidatedInputs:
    cfg = (config or RunConfig()).validate()
    # Validate every entity BEFORE accessibility so a manually built ValidatedInputs
    # (or malformed bundle) raises an actionable DataValidationError, not a deep
    # math error. Duplicate-ID checks also run here (and again at the run boundary).
    for d in bundle.districts:
        d.validate()
    for h in bundle.hospitals:
        h.validate()
    d_ids = [d.district_id for d in bundle.districts]
    if len(set(d_ids)) != len(d_ids):
        raise _DVE("duplicate district_id in inputs")
    h_ids = [h.hospital_id for h in bundle.hospitals]
    if len(set(h_ids)) != len(h_ids):
        raise _DVE("duplicate hospital_id in inputs")
    acc = build_accessibility(
        bundle.districts,
        bundle.hospitals,
        cfg.network,
        nearest_fallback=cfg.nearest_outside_radius_fallback,
    )
    manifest = dict(bundle.manifest)
    if acc.fallback_districts:
        manifest["nearest_fallback_districts"] = list(acc.fallback_districts)
        manifest["nearest_fallback_note"] = (
            "These populated tracts have no hospital within radius_km; each is "
            "assigned its single NEAREST hospital (disclosed), reflecting that "
            "their nearest care is beyond the normal catchment radius. Not silently "
            "dropped and not fabricated."
        )
    return ValidatedInputs(
        config=cfg,
        districts=bundle.districts,
        hospitals=bundle.hospitals,
        accessibility=acc,
        observed=None,
        manifest=manifest,
        data_mode=bundle.data_mode,
        seeded_cohorts=bundle.seeded_cohorts,
    )


def load_inputs(mode: str = "golden", config: RunConfig | None = None) -> ValidatedInputs:
    if mode == "golden":
        return build_inputs(golden_fixture(), config)
    if mode == "synthetic":
        return build_inputs(synthetic_spatial(), config)
    if mode == "real":
        from .data_real import load_real_bundle

        cfg = (config or RunConfig()).validate()
        # baseline_fraction sourced from RunConfig (no hidden default in loader).
        bundle, observed = load_real_bundle(baseline_fraction=cfg.baseline_fraction)
        # 229 of 230 positive-pop tracts are within 10 km of an included hospital;
        # one NE-Suffolk peninsula tract (25025170502, pop 3407, nearest 11.39 km)
        # requires the explicit nearest-outside-radius fallback policy. We HONOR the
        # caller's configured policy: if it is off, build_accessibility raises a
        # graceful, actionable error naming the uncovered tract (no silent drop, no
        # forced override).
        vi = build_inputs(bundle, cfg)
        vi.observed = observed
        return vi
    raise ValueError(f"unknown dataset mode {mode!r}")


# --------------------------------------------------------------------------- #
# Running scenarios
# --------------------------------------------------------------------------- #


def run_scenario(inputs: ValidatedInputs, injections: list | None = None) -> RunResult:
    return simulate_run(inputs.config, inputs, list(injections or []))


def compare_scenarios(inputs: ValidatedInputs, injections: list) -> dict:
    base = run_scenario(inputs, [])
    scen = run_scenario(inputs, injections)
    weeks = []
    for b, s in zip(base.weeks, scen.weeks, strict=True):
        weeks.append(
            {
                "week": b.week,
                "baseline": get_week(base, b.week, "after"),
                "scenario": get_week(scen, s.week, "after"),
            }
        )
    return {
        "baseline_run_id": base.run_id,
        "scenario_run_id": scen.run_id,
        "weeks": weeks,
    }


# --------------------------------------------------------------------------- #
# Flat per-week views for the UI
# --------------------------------------------------------------------------- #


def get_week(run: RunResult, week_index: int, phase: str = "after") -> dict:
    if phase not in ("before", "after"):
        raise ValueError(f"phase must be 'before' or 'after', got {phase!r}")
    if not isinstance(week_index, int) or isinstance(week_index, bool):
        raise ValueError(f"week_index must be an int, got {week_index!r}")
    if not (0 <= week_index < len(run.weeks)):
        raise IndexError(f"week_index {week_index} out of range [0, {len(run.weeks) - 1}]")
    wr: WeekResult = run.weeks[week_index]
    snap = wr.after if phase == "after" else wr.before
    loads = snap.hospital_loads
    fdna = snap.fdna
    alloc = snap.allocation

    hospitals = []
    for h in sorted(loads):
        lo = loads[h]
        hospitals.append(
            {
                "hospital_id": h,
                "baseline_beds": lo.baseline,
                "retained_beds": lo.retained,
                "request_people": lo.request_i,
                "requested_load": lo.requested_load,
                "effective_capacity_beds": lo.effective_capacity,
                "committed_beds": alloc.projected_occupancy.get(h, 0.0),
                "accepted_new_beds": alloc.accepted_i(h),
                "inherited_deficit_beds": wr.inherited_deficit.get(h, 0.0),
                "own_score": lo.own_score,
                "fdna_final_score": fdna.hospital_scores[h],
                "excess": lo.excess,
                "closed": lo.closed,
            }
        )

    districts = []
    for j in sorted(fdna.district_scores):
        districts.append(
            {
                "district_id": j,
                "access_score": float(fdna.district_scores[j]),
                "new_admission_need_people": float(wr.h_need.get(j, 0.0)),
                "unmet_need_people": float(alloc.unmet_by_district.get(j, 0.0)),
            }
        )

    overloaded = sum(
        1 for h in loads if loads[h].requested_load > loads[h].effective_capacity + 1e-9
    )
    below = sum(
        1 for j in fdna.district_scores if fdna.district_scores[j] < run.config.score_threshold
    )

    return {
        "run_id": run.run_id,
        "data_mode": run.data_mode,
        "week_index": week_index,
        "week_label": f"Week {week_index + 1}",
        "phase": phase,
        "metrics": {
            "overloaded_hospitals": int(overloaded),
            "unmet_need_people": float(sum(alloc.unmet_by_district.values())),
            "rerouted_people": float(alloc.reroute_volume),
            "inherited_deficit_beds": float(sum(wr.inherited_deficit.values())),
            "districts_below_threshold": int(below),
        },
        "hospitals": hospitals,
        "districts": districts,
        "reroutes": [
            {
                "week": r.week,
                "district": r.district,
                "source_hospital": r.source_hospital,
                "destination": r.destination,
                "amount": r.amount,
            }
            for r in alloc.reroutes
        ],
        "active_injections": [
            {
                "id": i.injection_id,
                "kind": i.kind,
                "payload": i.payload,
                "start_week": i.start_week,
                "end_week": i.end_week,
                "note": i.note,
            }
            for i in wr.active_injections
        ],
        "diagnostics": wr.diagnostics,
    }


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #


def _config_payload(cfg: RunConfig) -> dict:
    from dataclasses import asdict

    return asdict(cfg)


def export_json(run: RunResult) -> bytes:
    cfg = run.config
    payload = {
        "run_id": run.run_id,
        "data_mode": run.data_mode,
        "units": {
            "beds": "people == occupied beds",
            "need_and_unmet": "people/week (NOT beds)",
            "scores": "0-100 operability",
        },
        "config": _config_payload(cfg),
        "provenance": run.provenance,  # initial SEIR, seeded cohorts, component hashes
        "active_injections_by_week": [
            [
                {
                    "id": i.injection_id,
                    "kind": i.kind,
                    "payload": i.payload,
                    "start_week": i.start_week,
                    "end_week": i.end_week,
                    "note": i.note,
                }
                for i in w.active_injections
            ]
            for w in run.weeks
        ],
        "weeks": [get_week(run, w.week, "after") for w in run.weeks],
        "weeks_before": [get_week(run, w.week, "before") for w in run.weeks],
        "manifest": run.data_manifest,
        "validation": (run.validation.__dict__ if run.validation else None),
        "warnings": list(run.warnings),
    }
    # Strict numeric encoding: reject NaN/Infinity rather than concealing them.
    return json.dumps(payload, indent=2, allow_nan=False, default=_json_default).encode("utf-8")


def _json_default(o):
    # Only allow known safe conversions; everything else is a hard error.
    import numpy as np

    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(f"non-serializable object in export: {type(o)}")


def export_csv(run: RunResult, table: str = "hospital_week") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    # Provenance header comments so every CSV is self-labeling.
    src = run.data_manifest.get("source", "unknown")
    w.writerow(
        [
            f"# run_id={run.run_id}",
            f"data_mode={run.data_mode}",
            f"source={src}",
            "beds=people; need/unmet=people/week; scores=0-100",
        ]
    )
    if run.data_mode != "historical_data":
        w.writerow([f"# {run.data_mode.upper()} - not observed Boston occupancy"])
    if table == "hospital_week":
        w.writerow(
            [
                "run_id",
                "week",
                "phase",
                "hospital_id",
                "requested_load",
                "effective_capacity",
                "committed_beds",
                "own_score",
                "fdna_final_score",
                "inherited_deficit_beds",
            ]
        )
        for wr in run.weeks:
            for phase in ("before", "after"):
                v = get_week(run, wr.week, phase)
                for h in v["hospitals"]:
                    w.writerow(
                        [
                            run.run_id,
                            wr.week,
                            phase,
                            h["hospital_id"],
                            h["requested_load"],
                            h["effective_capacity_beds"],
                            h["committed_beds"],
                            h["own_score"],
                            h["fdna_final_score"],
                            h["inherited_deficit_beds"],
                        ]
                    )
    elif table == "district_week":
        w.writerow(
            [
                "run_id",
                "week",
                "phase",
                "district_id",
                "access_score",
                "new_admission_need_people",
                "unmet_need_people",
            ]
        )
        for wr in run.weeks:
            for phase in ("before", "after"):
                v = get_week(run, wr.week, phase)
                for d in v["districts"]:
                    w.writerow(
                        [
                            run.run_id,
                            wr.week,
                            phase,
                            d["district_id"],
                            d["access_score"],
                            d["new_admission_need_people"],
                            d["unmet_need_people"],
                        ]
                    )
    elif table == "reroute_week":
        w.writerow(["run_id", "week", "district", "source_hospital", "destination", "amount"])
        for wr in run.weeks:
            v = get_week(run, wr.week, "after")
            for r in v["reroutes"]:
                w.writerow(
                    [
                        run.run_id,
                        r["week"],
                        r["district"],
                        r["source_hospital"],
                        r["destination"],
                        r["amount"],
                    ]
                )
    else:
        raise ValueError(f"unknown table {table!r}")
    return buf.getvalue().encode("utf-8")
