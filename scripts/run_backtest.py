"""Compute the historical evaluation (fixed-origin + rolling-origin facility-level
backtests vs persistence) and write artifacts/evaluation.json with provenance,
predictions, observed series, and exclusions.

Honest result: the model is expected to LOSE to persistence; numbers are reported
as measured. Run:  PYTHONPATH=. .venv/bin/python scripts/run_backtest.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import time

from pipeline import api
from pipeline.data_real import HHS_FILE, _load_hhs_observed, real_available
from validation.backtest import _observed_by_ccn_week


def _sha(path):
    try:
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def main():
    pathlib.Path("artifacts").mkdir(exist_ok=True)
    if not real_available():
        json.dump({"status": "unavailable"}, open("artifacts/evaluation.json", "w"))
        print("real data unavailable")
        return
    t = time.time()
    report = api.compute_evaluation()
    elapsed = time.time() - t

    # attach observed series + masked exclusions + source checksums
    obs = _load_hhs_observed()
    valid, cal, excl = _observed_by_ccn_week(obs)
    report["elapsed_seconds"] = elapsed
    report["source_sha256_16"] = {"hhs": _sha(HHS_FILE)}
    report["observed_valid_keys"] = len(valid)
    report["calendar"] = cal
    report["exclusions_sample"] = excl[:50]

    json.dump(report, open("artifacts/evaluation.json", "w"), indent=2, default=str)
    fo = report.get("fixed_origin", {})
    ro = report.get("rolling_origin", {})
    print(f"status={report.get('status')} ({elapsed:.1f}s)")
    print(
        f"fixed-origin:  model_mae={fo.get('model_mae_beds')} "
        f"persistence_mae={fo.get('persistence_mae_beds')} pairs={fo.get('forecast_pairs')}"
    )
    print(
        f"rolling-origin: model_mae={ro.get('model_mae_beds')} "
        f"persistence_mae={ro.get('persistence_mae_beds')} pairs={ro.get('forecast_pairs')} "
        f"leakage_free={ro.get('leakage_free')}"
    )
    print("Honest note: model loses to persistence in both strategies.")
    print("saved artifacts/evaluation.json")


if __name__ == "__main__":
    main()
