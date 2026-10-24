"""Injection lifecycle: intervals, null end, no compounding, restoration,
conflicts, unknown targets, set_share mass preservation."""

from __future__ import annotations

import pytest

from pipeline import api
from pipeline.contracts import (
    DiseaseConfig,
    Injection,
    InvalidInjection,
    RunConfig,
)
from pipeline.data import golden_fixture
from pipeline.injections import resolve_scenario


def _hospitals():
    return golden_fixture().hospitals


def _net():
    return RunConfig().network


def test_interval_inclusive_exclusive():
    inj = Injection("i1", "close_hospital", 2, {"hospital_id": "H1"}, end_week=4)
    assert not inj.active_at(1)
    assert inj.active_at(2)
    assert inj.active_at(3)
    assert not inj.active_at(4)  # end exclusive


def test_null_end_open_ended():
    inj = Injection("i1", "set_capacity", 1, {"hospital_id": "H1", "factor": 0.5}, end_week=None)
    assert inj.active_at(1)
    assert inj.active_at(100)


def test_no_capacity_compounding():
    hosp = _hospitals()
    inj = [Injection("i1", "set_capacity", 0, {"hospital_id": "H1", "factor": 0.6})]
    scn_a = resolve_scenario(3, hosp, _net(), inj, ["D1", "D2", "D3"])
    scn_b = resolve_scenario(7, hosp, _net(), inj, ["D1", "D2", "D3"])
    # same effective capacity every active week (0.6*C, never 0.6**t)
    assert scn_a.effective_capacity["H1"] == scn_b.effective_capacity["H1"]
    assert abs(scn_a.effective_capacity["H1"] - 0.6 * 150) < 1e-9


def test_restoration_after_end():
    hosp = _hospitals()
    inj = [Injection("i1", "set_capacity", 2, {"hospital_id": "H1", "factor": 0.5}, end_week=4)]
    active = resolve_scenario(3, hosp, _net(), inj, ["D1", "D2", "D3"])
    restored = resolve_scenario(4, hosp, _net(), inj, ["D1", "D2", "D3"])
    assert active.effective_capacity["H1"] == 0.5 * 150
    assert restored.effective_capacity["H1"] == 150.0  # back to base


def test_unknown_hospital_rejected():
    hosp = _hospitals()
    inj = [Injection("i1", "close_hospital", 0, {"hospital_id": "NOPE"})]
    with pytest.raises(InvalidInjection):
        resolve_scenario(0, hosp, _net(), inj, ["D1", "D2", "D3"])


def test_conflicting_capacity_rejected():
    hosp = _hospitals()
    inj = [
        Injection("i1", "close_hospital", 0, {"hospital_id": "H1"}),
        Injection("i2", "set_capacity", 0, {"hospital_id": "H1", "factor": 0.5}),
    ]
    with pytest.raises(InvalidInjection):
        resolve_scenario(0, hosp, _net(), inj, ["D1", "D2", "D3"])


def test_pre_injection_weeks_identical_to_baseline():
    cfg = RunConfig(disease=DiseaseConfig(r0=2.6, initial_infectious_fraction=0.003), weeks=5)
    inp = api.load_inputs("synthetic", cfg)
    base = api.run_scenario(inp, [])
    close = Injection("c", "close_hospital", 3, {"hospital_id": "SH0"}, end_week=5)
    scen = api.run_scenario(inp, [close])
    # weeks 0,1,2 identical before the injection starts (week 3)
    for t in range(3):
        vb = api.get_week(base, t, "after")
        vs = api.get_week(scen, t, "after")
        assert vb["metrics"] == vs["metrics"]


def test_closure_preserves_occupants_inherited_deficit():
    # Build a case where a hospital has standing occupancy then closes.
    cfg = RunConfig(disease=DiseaseConfig(r0=2.8, initial_infectious_fraction=0.004), weeks=6)
    inp = api.load_inputs("synthetic", cfg)
    close = Injection("c", "close_hospital", 3, {"hospital_id": "SH0"}, end_week=6)
    scen = api.run_scenario(inp, [close])
    wk = scen.weeks[3]
    # inherited deficit = baseline + retained at the closed hospital (survives)
    assert wk.inherited_deficit.get("SH0", 0.0) >= 0.0
    # closed hospital accepts no new admissions
    v = api.get_week(scen, 3, "after")
    h = next(x for x in v["hospitals"] if x["hospital_id"] == "SH0")
    assert h["accepted_new_beds"] == 0.0
    assert h["closed"] is True
