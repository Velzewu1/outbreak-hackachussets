"""Reproducible fixed-seed benchmark: end-to-end wall time and peak memory for
golden-small, medium (~100 districts / 15 hospitals / 52 weeks) and large
(~1000 districts / 40 hospitals / 52 weeks), with repeats. Verifies conservation
and determinism during the benchmark. Writes artifacts/benchmark.json.

Measured numbers only; nothing invented. Run:
  .venv/bin/python scripts/benchmark.py
"""

from __future__ import annotations

import json
import pathlib
import platform
import statistics
import time
import tracemalloc

from pipeline import api
from pipeline.data import synthetic_spatial


def _bundle(n_d, n_h, seed=7):
    return synthetic_spatial(n_districts=n_d, n_hospitals=n_h, seed=seed)


def _rss_mb():
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return None


def _run_once(mode_bundle, weeks):
    cfg = api.RunConfig(
        disease=api.DiseaseConfig(r0=2.6, initial_infectious_fraction=0.003),
        weeks=weeks,
    )
    inp = api.build_inputs(mode_bundle, cfg)
    rss_before = _rss_mb()
    tracemalloc.start()
    t0 = time.perf_counter()
    run = api.run_scenario(inp, [])
    dt = time.perf_counter() - t0
    _cur, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = _rss_mb()
    # verify conservation + determinism by SERIALIZED output bytes (not only run_id)
    ok = all(
        w.diagnostics["mass"]
        and w.diagnostics["patient_mass"]
        and w.diagnostics["capacity_bound"]
        and w.diagnostics["fdna_convergence"]
        for w in run.weeks
    )
    run2 = api.run_scenario(inp, [])
    bytes1 = api.export_json(run)
    bytes2 = api.export_json(run2)
    deterministic = (run.run_id == run2.run_id) and (bytes1 == bytes2)
    rss_delta = (
        (rss_after - rss_before) if (rss_before is not None and rss_after is not None) else None
    )
    return dt, traced_peak / 1e6, rss_delta, ok, deterministic, run.run_id


def bench_case(name, n_d, n_h, weeks, repeats):
    times = []
    traced_peaks = []
    rss_deltas = []
    ok_all = True
    det_all = True
    rid = None
    for _ in range(repeats):
        b = _bundle(n_d, n_h)
        dt, traced_peak_mb, rss_delta, ok, det, rid = _run_once(b, weeks)
        times.append(dt)
        traced_peaks.append(traced_peak_mb)
        if rss_delta is not None:
            rss_deltas.append(rss_delta)
        ok_all = ok_all and ok
        det_all = det_all and det
    return {
        "name": name,
        "districts": n_d,
        "hospitals": n_h,
        "weeks": weeks,
        "repeats": repeats,
        "wall_seconds_mean": statistics.mean(times),
        "wall_seconds_min": min(times),
        "wall_seconds_max": max(times),
        "python_traced_peak_mb_mean": statistics.mean(traced_peaks),
        "process_rss_delta_mb_mean": (statistics.mean(rss_deltas) if rss_deltas else None),
        "memory_note": "python_traced_peak = tracemalloc (Python allocations only); "
        "process_rss_delta = psutil RSS change (whole process)",
        "conservation_ok": ok_all,
        "deterministic_bytes": det_all,
        "run_id_sample": rid,
    }


def main():
    cases = [
        ("golden_small", 3, 3, 8, 5),
        ("medium", 100, 15, 52, 3),
        ("large", 1000, 40, 52, 2),
    ]
    results = [bench_case(*c) for c in cases]
    env = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
    }
    out = {"environment": env, "cases": results, "note": "measured; not invented"}
    pathlib.Path("artifacts").mkdir(exist_ok=True)
    json.dump(out, open("artifacts/benchmark.json", "w"), indent=2)
    for r in results:
        rss = r["process_rss_delta_mb_mean"]
        rss_s = f"{rss:.1f}" if rss is not None else "n/a"
        print(
            f"{r['name']:13} d={r['districts']:4} h={r['hospitals']:2} "
            f"w={r['weeks']:2} x{r['repeats']}: "
            f"{r['wall_seconds_mean']:.3f}s mean, traced-peak "
            f"{r['python_traced_peak_mb_mean']:.1f}MB, RSS+{rss_s}MB, "
            f"conserve={r['conservation_ok']} det-bytes={r['deterministic_bytes']}"
        )
    print("saved artifacts/benchmark.json")


if __name__ == "__main__":
    main()
