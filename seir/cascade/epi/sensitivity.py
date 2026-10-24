"""One-at-a-time sensitivity: move each input by +-25% and see what an output does.

The writeup asks for this on every assumed weight. For the SEIR layer the
inputs are scenario values given as dotted paths ("disease.r0",
"disease.los_icu", "mixing.contact_multiplier.elasticity"), and the output
is any number computed from a run (by default a key of SEIRResult.summary()).
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from .config import ScenarioConfig
from .results import SEIRResult

Metric = str | Callable[[SEIRResult], float]


def _get(cfg: ScenarioConfig, path: str):
    node = cfg.model_dump()
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f"{path}: {key!r} is not in the scenario")
        node = node[key]
    return node


def _metric_value(res: SEIRResult, metric: Metric) -> float:
    if callable(metric):
        return float(metric(res))
    summary = res.summary()
    if metric not in summary:
        raise KeyError(f"unknown metric {metric!r}; summary() has {sorted(summary)}")
    return float(summary[metric])


def _run(job) -> float:
    cfg, days, metric, engine_kwargs = job
    from .engine import SEIREngine

    return _metric_value(SEIREngine.from_config(cfg, **engine_kwargs).run(cfg.seeding, days), metric)


def one_at_a_time(cfg: ScenarioConfig, paths: Sequence[str], metric: Metric = "peak_inpatients",
                  rel: float = 0.25, days: int | None = None, workers: int = 1,
                  **engine_kwargs) -> pd.DataFrame:
    """Each input at (1 - rel) and (1 + rel) times its value, others held at base.

    Returns one row per input, sorted by swing (|high - low| of the metric),
    with the elasticity (relative change in metric per relative change in
    input). Values that are lists (per-age shares) are scaled as a whole.
    Shares are capped at 1 and integers stay integers.
    """
    if not 0 < rel < 1:
        raise ValueError("rel must be between 0 and 1")
    days = days or cfg.sim.days
    jobs, rows = [(cfg, days, metric, engine_kwargs)], []
    for path in paths:
        base = _get(cfg, path)
        for f in (1 - rel, 1 + rel):
            value = (np.asarray(base, dtype=float) * f)
            if path.split(".")[-1] in ("p_hosp", "p_icu", "p_death_icu"):
                value = np.minimum(value, 1.0)
            value = value.tolist() if np.ndim(value) else (int(round(value)) if isinstance(base, int) else float(value))
            jobs.append((cfg.updated({path: value}), days, metric, engine_kwargs))
        rows.append((path, base))
    if workers > 1 and not callable(metric):
        with ProcessPoolExecutor(workers) as ex:
            values = list(ex.map(_run, jobs))
    else:
        values = [_run(j) for j in jobs]
    base_metric = values[0]
    out = []
    for i, (path, base) in enumerate(rows):
        low, high = values[1 + 2 * i], values[2 + 2 * i]
        out.append({
            "parameter": path,
            "base_value": base,
            "metric_low": low,
            "metric_base": base_metric,
            "metric_high": high,
            "swing": abs(high - low),
            "elasticity": (high - low) / (2 * rel * base_metric) if base_metric else np.nan,
        })
    return pd.DataFrame(out).sort_values("swing", ascending=False, ignore_index=True)
