"""The shipped scenarios load, run, and reproduce the documented Massachusetts results."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cascade.epi import ScenarioConfig, data, simulate
from cascade.epi.calibrate import aligned
from cascade.epi.validation import validate_series
from conftest import DATA, SCENARIOS


@pytest.fixture(scope="module")
def admissions():
    return data.weekly(data.hhs_state_admissions(DATA / "hhs_ma_daily_admissions.csv"))


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_scenario_loads_and_runs(path):
    cfg = ScenarioConfig.from_yaml(path)
    res = simulate(cfg, days=14)
    assert res.ds.sizes["time"] == 14 and np.isfinite(res.ds["I"]).all()


def scored(cfg, observed):
    res = simulate(cfg, days=int((observed.index[-1] - pd.Timestamp(cfg.sim.start)).days) + 1)
    model = pd.Series(aligned(res.series("new_hosp"), observed.index, 7), index=observed.index)
    return res, validate_series(model, observed)


def test_omicron_scenario_passes_the_bars_without_refitting(admissions):
    cfg = ScenarioConfig.from_yaml(SCENARIOS / "omicron_2021.yaml")
    res, report = scored(cfg, admissions["2021-12-25":"2022-03-05"])
    assert report.passed
    values = {c.name: c.value for c in report.checks}
    assert values["weeks within +-40%"] == 1.0 and values["peak week offset"] == 0
    assert values["peak height error"] == pytest.approx(-0.16, abs=0.02)
    summary = res.summary()
    assert summary["r_eff_start"] == pytest.approx(1.50, abs=0.02)
    assert summary["attack_rate"] == pytest.approx(0.42, abs=0.02)


def test_mobility_scenario_passes_in_sample(admissions):
    cfg = ScenarioConfig.from_yaml(SCENARIOS / "omicron_2021_mobility.yaml")
    _, report = scored(cfg, admissions["2021-12-25":"2022-03-05"])
    assert report.passed


def test_winter_census_out_of_sample(admissions):
    cfg = ScenarioConfig.from_yaml(SCENARIOS / "winter_2020.yaml")
    res, report = scored(cfg, admissions["2020-10-03":"2021-03-06"])
    assert report.passed                                             # admissions: what was fitted
    census = data.ctp_state(DATA / "ctp_ma_hospital_census.csv").resample("W-SAT").mean()
    census = census.loc["2020-10-03":"2021-03-06"]

    def check(name, column):
        model = pd.Series(aligned(res.series(name), census.index, 7, how="mean"), index=census.index)
        return {c.name: c.value for c in validate_series(model, census[column]).checks}

    icu = check("icu", "inIcuCurrently")
    assert icu["weeks within +-40%"] > 0.9 and icu["peak week offset"] == 0
    assert abs(icu["peak height error"]) < 0.05
    ward = check("inpatients", "hospitalizedCurrently")                # documented: peak 26% low
    assert ward["weeks within +-40%"] > 0.8 and ward["peak week offset"] == 0
    assert ward["peak height error"] == pytest.approx(-0.26, abs=0.02)


def test_novel_flu_is_a_pathogen_swap():
    cfg = ScenarioConfig.from_yaml(SCENARIOS / "novel_flu.yaml")
    assert cfg.disease.name == "influenza_pandemic_2009" and cfg.disease.r0 == 1.8
    s = simulate(cfg).summary()
    assert 0.5 < s["attack_rate"] < 0.8 and s["peak_inpatients"] > 0
