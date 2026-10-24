"""Stochastic ensembles and one-at-a-time sensitivity."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cascade.epi import simulate
from cascade.epi.ensemble import bands, run_ensemble, takeoff_share
from cascade.epi.sensitivity import one_at_a_time


@pytest.fixture(scope="module")
def ens(example_module):
    return run_ensemble(example_module, runs=8, seed=1, days=60)


@pytest.fixture(scope="module")
def example_module():
    from cascade.epi import ScenarioConfig
    from conftest import SCENARIOS

    return ScenarioConfig.from_yaml(SCENARIOS / "example_3patch.yaml")


def test_ensemble_shapes_and_seeds(ens):
    assert ens["new_hosp"].dims == ("run", "time", "patch")
    assert ens.sizes == {"run": 8, "time": 60, "patch": 3}
    assert ens["r_eff"].dims == ("run", "time")
    assert len(set(ens.attrs["seeds"])) == 8
    v = ens["inpatients"].values
    assert np.allclose(v, np.round(v)) and (v >= 0).all()           # whole people
    assert not np.array_equal(ens["infections"][0], ens["infections"][1])


def test_ensembles_are_reproducible_and_parallel_safe(example_module, ens):
    again = run_ensemble(example_module, runs=8, seed=1, days=60, workers=2)
    assert again.identical(ens)
    other = run_ensemble(example_module, runs=8, seed=2, days=60)
    assert not other["infections"].equals(ens["infections"])


def test_bands_and_takeoff(ens):
    b = bands(ens)
    assert b["inpatients"].dims == ("quantile", "time")
    lo, mid, hi = (b["inpatients"].sel(quantile=q) for q in (0.05, 0.5, 0.95))
    assert (lo <= mid).all() and (mid <= hi).all()
    assert bands(ens, citywide=False)["inpatients"].dims == ("quantile", "time", "patch")
    assert takeoff_share(ens) == 1.0                                 # 70 seeds always take off
    assert takeoff_share(ens, threshold=np.inf) == 0.0


def test_ensemble_median_tracks_the_deterministic_run(example_module, ens):
    det = simulate(example_module, days=60).series("infections").sum()
    total = ens["infections"].sum(["time", "patch"])
    assert float(total.median()) == pytest.approx(det, rel=0.1)


def test_ensemble_input_checks(example_module):
    with pytest.raises(ValueError, match="at least 1"):
        run_ensemble(example_module, runs=0)
    with pytest.raises(ValueError, match="unknown structure"):
        run_ensemble(example_module, runs=1, days=5, structure="sir")
    ens = run_ensemble(example_module, runs=2, days=5, structure="seir", variables=("infections",))
    assert set(ens.data_vars) == {"infections", "r_eff"}


# ---- sensitivity --------------------------------------------------------------------
def test_one_at_a_time_ranks_inputs(example_module):
    df = one_at_a_time(example_module, ["disease.r0", "disease.los_icu", "disease.p_hosp"], days=120)
    assert list(df.columns) == ["parameter", "base_value", "metric_low", "metric_base", "metric_high",
                                "swing", "elasticity"]
    assert df["swing"].is_monotonic_decreasing
    row = df.set_index("parameter")
    assert row.loc["disease.p_hosp", "elasticity"] == pytest.approx(1.0, rel=0.02)   # census scales with p_hosp
    assert row.loc["disease.los_icu", "metric_high"] > row.loc["disease.los_icu", "metric_low"]
    assert row.loc["disease.p_hosp", "base_value"] == [0.002, 0.01, 0.06]


def test_one_at_a_time_caps_shares_and_keeps_integers(example_module):
    cfg = example_module.updated({"disease.p_icu": 0.9, "sim.days": 30})
    df = one_at_a_time(cfg, ["disease.p_icu", "sim.substeps"], metric="admissions")
    assert set(df["parameter"]) == {"disease.p_icu", "sim.substeps"}
    custom = one_at_a_time(cfg, ["disease.r0"], metric=lambda r: float(r.ds["new_hosp"].sum()))
    assert custom.loc[0, "metric_high"] > custom.loc[0, "metric_low"]


def test_one_at_a_time_input_checks(example_module):
    with pytest.raises(ValueError, match="between 0 and 1"):
        one_at_a_time(example_module, ["disease.r0"], rel=1.5)
    with pytest.raises(KeyError, match="not in the scenario"):
        one_at_a_time(example_module, ["disease.r_zero"])
    with pytest.raises(KeyError, match="unknown metric"):
        one_at_a_time(example_module, ["disease.r0"], metric="happiness", days=10)
