"""Many stochastic runs of one scenario, for uncertainty bands.

Each run is a chain-binomial simulation with its own seed. Runs are
independent, so workers > 1 spreads them over processes. Everything sent to
a worker must pickle: the scenario (pydantic models do), a structure given by
name ("seir", "seir_h") or as a top-level function, and rate providers built
from the classes in rates.py (lambdas do not pickle).
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Sequence

import numpy as np
import pandas as pd
import xarray as xr

from .config import ScenarioConfig
from .structure import STRUCTURES, ModelStructure

StructureSpec = str | Callable[[], ModelStructure] | None
DEFAULT_VARIABLES = ("infections", "new_hosp", "inpatients", "icu", "new_deaths")


def _structure(spec: StructureSpec) -> ModelStructure | None:
    if spec is None:
        return None
    if isinstance(spec, str):
        if spec not in STRUCTURES:
            raise ValueError(f"unknown structure {spec!r}; choose from {sorted(STRUCTURES)}")
        return STRUCTURES[spec]()
    return spec()


def _one_run(job) -> dict[str, np.ndarray]:
    cfg, days, structure, variables, engine_kwargs = job
    from .engine import SEIREngine

    engine = SEIREngine.from_config(cfg, structure=_structure(structure), **engine_kwargs)
    res = engine.run(cfg.seeding, days)
    out = {}
    for v in variables:
        da = res.inpatients() if v == "inpatients" else (
            res.ds["C"].sum("age") if v == "icu" else (
                res.infections().sum("age") if v == "infections" else res.ds[v].sum("age")))
        out[v] = da.values                                   # [time, patch]
    out["r_eff"] = res.ds["r_eff"].values
    return out


def run_ensemble(cfg: ScenarioConfig, runs: int = 50, seed: int = 0, workers: int = 1,
                 days: int | None = None, structure: StructureSpec = None,
                 variables: Sequence[str] = DEFAULT_VARIABLES, **engine_kwargs) -> xr.Dataset:
    """Stochastic runs stacked along a "run" dimension: dims (run, time, patch), r_eff (run, time).

    Seeds come from numpy's SeedSequence(seed), so the whole ensemble is
    reproducible and runs do not share random streams.
    """
    if runs < 1:
        raise ValueError("runs must be at least 1")
    days = days or cfg.sim.days
    seeds = np.random.SeedSequence(seed).generate_state(runs)
    jobs = [(cfg.updated({"sim.stochastic": True, "sim.seed": int(s)}), days, structure,
             tuple(variables), engine_kwargs) for s in seeds]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            outs = list(ex.map(_one_run, jobs))
    else:
        outs = [_one_run(j) for j in jobs]
    time = pd.date_range(cfg.sim.start, periods=days, freq="D", name="time")
    data = {v: (("run", "time", "patch"), np.stack([o[v] for o in outs])) for v in variables}
    data["r_eff"] = (("run", "time"), np.stack([o["r_eff"] for o in outs]))
    return xr.Dataset(data, coords={"run": np.arange(runs), "time": time,
                                    "patch": cfg.population.patches},
                      attrs={"seed": seed, "seeds": [int(s) for s in seeds]})


def bands(ens: xr.Dataset, q: Sequence[float] = (0.05, 0.5, 0.95), citywide: bool = True) -> xr.Dataset:
    """Quantiles over runs (summed over patches first when citywide)."""
    data = ens.sum("patch") if citywide else ens
    data = data.assign(r_eff=ens["r_eff"])
    return data.quantile(list(q), dim="run")


def takeoff_share(ens: xr.Dataset, threshold: float | None = None) -> float:
    """Share of runs whose epidemic took off: total infections above `threshold`.

    Stochastic runs started from a few cases can die out by chance; report
    this share next to any band. By default the threshold is 1% of the
    median run's total infections.
    """
    total = ens["infections"].sum(["time", "patch"])
    threshold = 0.01 * float(total.median()) if threshold is None else threshold
    return float((total > threshold).mean())
