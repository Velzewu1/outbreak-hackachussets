"""SEIRResult: labelled output, the series and weeks a frontend needs, summaries and files."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from cascade.epi import SEIREngine, simulate, with_vaccination, seir_h, Constant


@pytest.fixture(scope="module")
def res():
    from cascade.epi import ScenarioConfig
    from conftest import SCENARIOS

    cfg = ScenarioConfig.from_yaml(SCENARIOS / "example_3patch.yaml")
    return simulate(cfg)


def test_every_variable_says_what_it_is(res):
    kinds = {v: res.ds[v].attrs["kind"] for v in res.ds.data_vars}
    assert set(res.compartments.data_vars) == {"S", "E", "I", "R", "H", "C", "D"}
    assert {"new_exposed", "new_hosp", "new_icu", "new_deaths"} <= set(res.flows.data_vars)
    assert {"transmission_rate", "incubation_rate", "recovery_rate", "force_of_infection", "r_eff"} <= set(res.rates.data_vars)
    assert set(kinds.values()) == {"compartment", "flow", "rate"}
    assert res.ds["incubation_rate"].attrs["units"] == "per day" and res.ds["p_hosp"].attrs["units"] == "share"
    assert res.ds["transmission_rate"].dims == ("time",)                    # same everywhere: per day
    assert res.ds["p_hosp"].dims == ("time", "patch", "age")                # varies by age: per cell
    assert res.ds.sizes == {"time": 120, "patch": 3, "age": 3}


def test_named_rates_are_the_model_inputs(res):
    assert np.allclose(res.ds["incubation_rate"], 1 / 3) and np.allclose(res.ds["recovery_rate"], 1 / 5)
    foi = res.ds["force_of_infection"]
    assert (foi >= 0).all() and float(foi.max()) > 0


def test_observed_rates_estimate_the_inputs(res):
    avg = res.observed_rates("average")
    early = slice(5, 40)                                       # enough people in each stage
    assert np.allclose(avg["new_infectious"][early], 1 / 3, rtol=0.03)
    assert np.allclose((avg["new_recovered"] + avg["new_hosp"])[early], 1 / 5, rtol=0.03)
    one = res.observed_rate("E", "new_infectious", method="average")
    assert one.dims == ("time", "patch", "age")
    with pytest.raises(ValueError):
        res.observed_rate("E", "new_infectious", method="median")


def test_series_and_derived_counts(res):
    assert np.allclose(res.series("inpatients"), (res.ds["H"] + res.ds["C"]).sum(["patch", "age"]))
    assert np.allclose(res.series("icu"), res.ds["C"].sum(["patch", "age"]))
    assert np.allclose(res.series("infections"), res.series("new_exposed"))
    assert np.allclose(res.series("infectious"), res.series("I"))
    roxbury = res.series("new_hosp", patches=["Roxbury"])
    assert np.allclose(roxbury, res.ds["new_hosp"].sel(patch="Roxbury").sum("age"))
    with pytest.raises(KeyError, match="rates live in ds"):
        res.series("transmission_rate")
    with pytest.raises(KeyError):
        res.series("nothing")


def test_weeks_are_complete_mmwr_weeks(res):
    w = res.weekly("new_hosp")
    assert (w.index.day_of_week == 5).all()                     # labelled by the Saturday that ends the week
    first = w.index[0]
    daily = res.series("new_hosp")
    assert w.iloc[0] == pytest.approx(daily[first - pd.Timedelta(days=6):first].sum())
    assert w.index[0] - pd.Timedelta(days=6) >= daily.index[0]
    assert w.index[-1] <= daily.index[-1]
    census = res.weekly("inpatients")
    assert census.iloc[0] == pytest.approx(res.series("inpatients")[first - pd.Timedelta(days=6):first].mean())
    assert len(res.weekly("new_hosp", complete=False)) >= len(w)


def test_summary_is_plain_json(res):
    s = res.summary()
    json.dumps(s)
    assert s["days"] == 120 and s["start"] == "2021-12-01"
    assert s["attack_rate"] == pytest.approx(s["infections"] / s["population"])
    assert s["admissions"] == pytest.approx(float(res.ds["new_hosp"].sum()))
    assert s["peak_inpatients"] == pytest.approx(res.series("inpatients").max())
    assert s["r_eff_start"] > 1 > s["r_eff_end"]


def test_infections_count_every_route_into_exposed(example):
    cfg = example
    st = with_vaccination(seir_h())
    res = SEIREngine.from_config(cfg, structure=st, vax_rate=Constant(0.01),
                                 vax_efficacy=Constant(0.5)).run(cfg.seeding, 60)
    total = res.ds["new_exposed"] + res.ds["breakthrough_infections"]
    assert float(res.ds["breakthrough_infections"].sum()) > 0
    assert np.allclose(res.infections(), total)


def test_frame_has_one_row_per_day_and_patch(res):
    df = res.to_frame()
    assert len(df) == 120 * 3 and list(df.columns[:2]) == ["time", "patch"]
    assert {"S", "new_hosp", "transmission_rate", "p_hosp", "r_eff"} <= set(df.columns)
    dorchester = df[df["patch"] == "Dorchester"].set_index("time")
    w = res.population.sel(patch="Dorchester")
    expected = (res.ds["p_hosp"].sel(patch="Dorchester") * w).sum("age") / w.sum()
    assert np.allclose(dorchester["p_hosp"], expected)              # population-weighted over ages
    assert "population" not in df.columns
    assert "transmission_rate" not in res.to_frame(include_rates=False).columns


def test_saving_to_csv_and_netcdf(res, tmp_path):
    res.save(tmp_path / "run.csv")
    back = pd.read_csv(tmp_path / "run.csv")
    assert len(back) == 360 and "new_hosp" in back.columns
    res.save(tmp_path / "run.nc")
    with xr.open_dataset(tmp_path / "run.nc") as ds:
        assert np.allclose(ds["I"], res.ds["I"]) and ds["I"].attrs["kind"] == "compartment"


def test_results_need_at_least_one_day(example):
    from cascade.epi.results import SEIRResult

    with pytest.raises(ValueError, match="at least one day"):
        SEIRResult.from_records([], None, seir_h(), example.population)
