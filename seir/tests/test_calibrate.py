"""Fitting: the general least-squares wrapper, dated alignment and fit_scenario."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cascade.epi import SEIREngine
from cascade.epi.calibrate import Param, aligned, calibrate, fit_scenario, fitted_series, infer_window


def test_param_checks_its_bounds():
    with pytest.raises(ValueError, match="outside"):
        Param(5.0, 1.0, 4.0)
    with pytest.raises(ValueError, match="positive lower bound"):
        Param(1.0, 0.0, 4.0, log=True)


def test_window_inference():
    weekly = pd.date_range("2022-01-01", periods=5, freq="7D")
    daily = pd.date_range("2022-01-01", periods=5, freq="D")
    assert infer_window(weekly) == 7 and infer_window(daily) == 1
    assert infer_window(weekly[:1]) == 1
    assert infer_window(pd.DatetimeIndex(["2022-01-01", "2022-01-04", "2022-01-07"])) == 1


def test_aligned_sums_or_averages_the_window():
    daily = pd.Series(np.arange(1.0, 15.0), index=pd.date_range("2022-01-01", periods=14))
    ends = pd.DatetimeIndex(["2022-01-07", "2022-01-14"])
    assert np.allclose(aligned(daily, ends, 7), [28.0, 77.0])
    assert np.allclose(aligned(daily, ends, 7, how="mean"), [4.0, 11.0])
    starts = pd.DatetimeIndex(["2022-01-01", "2022-01-08", "2022-01-09"])
    out = aligned(daily, starts, 7, label="start")
    assert np.allclose(out[:2], [28.0, 77.0]) and np.isnan(out[2])           # runs past the end
    assert np.isnan(aligned(daily, pd.DatetimeIndex(["2022-01-03"]), 7)[0])  # starts before the run
    with pytest.raises(ValueError):
        aligned(daily, ends, 7, label="middle")
    with pytest.raises(ValueError):
        aligned(daily, ends, 7, how="median")


@pytest.fixture(scope="module")
def truth(request):
    """Weekly admissions from the example scenario with known values."""
    from cascade.epi import ScenarioConfig
    from conftest import SCENARIOS

    cfg = ScenarioConfig.from_yaml(SCENARIOS / "example_3patch.yaml")
    true = cfg.updated({"disease.r0": 2.2, "seeding.exposed.Dorchester": 40})
    res = SEIREngine.from_config(true).run(true.seeding, 120)
    return cfg, res.weekly("new_hosp")


def test_fit_scenario_recovers_known_values(truth):
    cfg, observed = truth
    fit = fit_scenario(cfg, observed, {"disease.r0": Param(3.0, 1.2, 5.0),
                                       "seeding.exposed.Dorchester": Param(10, 1, 1000, log=True)})
    assert fit.success
    assert fit.params["disease.r0"] == pytest.approx(2.2, rel=1e-3)
    assert fit.params["seeding.exposed.Dorchester"] == pytest.approx(40, rel=1e-2)
    assert fit.config.disease.r0 == pytest.approx(fit.params["disease.r0"])
    assert fit.extra["window"] == 7 and fit.extra["how"] == "sum"
    frame = fitted_series(fit)
    assert list(frame.columns) == ["observed", "model"] and np.allclose(frame["model"], frame["observed"], rtol=1e-3)


def test_missing_weeks_are_left_out(truth):
    cfg, observed = truth
    gappy = observed.copy()
    gappy.iloc[[2, 5]] = np.nan
    fit = fit_scenario(cfg, gappy, {"disease.r0": Param(3.0, 1.2, 5.0)})
    assert fit.params["disease.r0"] == pytest.approx(2.2, rel=0.02)    # the seed is off by design here
    with pytest.raises(ValueError, match="no finite"):
        fit_scenario(cfg, gappy * np.nan, {"disease.r0": Param(3.0, 1.2, 5.0)})


def test_census_targets_are_averaged(truth):
    cfg, _ = truth
    res = SEIREngine.from_config(cfg).run(cfg.seeding, 120)
    census = res.weekly("inpatients")
    fit = fit_scenario(cfg, census, {"disease.r0": Param(2.5, 1.2, 5.0)}, variable="inpatients")
    assert fit.extra["how"] == "mean"
    assert fit.params["disease.r0"] == pytest.approx(cfg.disease.r0, rel=1e-3)


def test_fit_scenario_refuses_data_before_the_start(truth):
    cfg, observed = truth
    early = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(["2021-01-02", "2021-01-09"]))
    with pytest.raises(ValueError, match="before sim.start"):
        fit_scenario(cfg, early, {"disease.r0": Param(2.5, 1.2, 5.0)})


def test_calibrate_checks_its_inputs(truth):
    cfg, observed = truth

    def simulate(p):
        return SEIREngine.from_config(cfg.updated({"disease.r0": p["r0"]})).run(cfg.seeding, 30)

    with pytest.raises(ValueError, match="loss"):
        calibrate(simulate, lambda r: np.zeros(3), np.ones(3), {"r0": Param(2.5, 1.2, 5)}, loss="huber")
    with pytest.raises(ValueError, match="shape"):
        calibrate(simulate, lambda r: np.zeros(2), np.ones(3), {"r0": Param(2.5, 1.2, 5)})
