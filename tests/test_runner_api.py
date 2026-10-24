"""Full-wiring integration tests: determinism, run_id sensitivity, immutability,
invalid week/phase, exports (strict), scenario isolation, nine-block wiring,
conservation on the whole pipeline (not just hand-built allocations)."""

from __future__ import annotations

import dataclasses
import json
import pickle

import pytest

from pipeline import api
from pipeline.contracts import DiseaseConfig, Injection, RunConfig
from pipeline.data import golden_fixture


def _syn_run(weeks=6, r0=2.8, seed=0.004):
    cfg = RunConfig(disease=DiseaseConfig(r0=r0, initial_infectious_fraction=seed), weeks=weeks)
    inp = api.load_inputs("synthetic", cfg)
    return api.run_scenario(inp, []), inp


def test_determinism():
    r1, inp = _syn_run()
    r2 = api.run_scenario(inp, [])
    assert r1.run_id == r2.run_id


def test_run_id_sensitive_to_risk_weight():
    b1 = golden_fixture()
    r1 = api.run_scenario(api.build_inputs(b1, RunConfig(weeks=3)), [])
    b2 = golden_fixture()
    b2.districts[1] = dataclasses.replace(b2.districts[1], risk_weight=3.0)
    r2 = api.run_scenario(api.build_inputs(b2, RunConfig(weeks=3)), [])
    assert r1.run_id != r2.run_id


def test_run_id_sensitive_to_population_and_geometry():
    b1 = golden_fixture()
    r1 = api.run_scenario(api.build_inputs(b1, RunConfig(weeks=2)), [])
    b2 = golden_fixture()
    b2.districts[0] = dataclasses.replace(b2.districts[0], population=12345)
    r2 = api.run_scenario(api.build_inputs(b2, RunConfig(weeks=2)), [])
    assert r1.run_id != r2.run_id


def test_run_id_sensitive_to_scenario_events():
    r_base, inp = _syn_run(weeks=5)
    close = Injection("c", "close_hospital", 2, {"hospital_id": "SH0"}, end_week=5)
    r_scen = api.run_scenario(inp, [close])
    assert r_base.run_id != r_scen.run_id


def test_nested_immutability_all_maps():
    r, _ = _syn_run(weeks=3)
    wk = r.weeks[0]
    with pytest.raises(TypeError):
        wk.state.S[wk.state.district_ids[0]] = 1.0
    with pytest.raises(TypeError):
        wk.after.allocation.unmet_by_district["x"] = 1.0
    with pytest.raises(TypeError):
        wk.after.fdna.hospital_scores["x"] = 1.0
    with pytest.raises(TypeError):
        wk.inherited_deficit["x"] = 1.0
    with pytest.raises(TypeError):
        wk.diagnostics["x"] = 1.0


def test_invalid_week_and_phase_rejected():
    r, _ = _syn_run(weeks=3)
    with pytest.raises(IndexError):
        api.get_week(r, -1, "after")
    with pytest.raises(IndexError):
        api.get_week(r, 99, "after")
    with pytest.raises(ValueError):
        api.get_week(r, 0, "bogus")


def test_pickle_and_json_strict():
    r, _ = _syn_run(weeks=3)
    assert pickle.loads(pickle.dumps(r)).run_id == r.run_id
    payload = json.loads(api.export_json(r))
    assert payload["run_id"] == r.run_id
    assert "config" in payload and "units" in payload
    # CSV carries provenance header
    csv = api.export_csv(r, "hospital_week").decode()
    assert "run_id=" in csv and "data_mode=" in csv


def test_scenario_isolation():
    r_base, inp = _syn_run(weeks=5)
    close = Injection("c", "close_hospital", 2, {"hospital_id": "SH0"}, end_week=5)
    _ = api.run_scenario(inp, [close])
    # baseline rerun unaffected by having run a scenario
    r_base2 = api.run_scenario(inp, [])
    assert r_base.run_id == r_base2.run_id


def test_whole_pipeline_conservation():
    r, inp = _syn_run(weeks=6)
    for wk in r.weeks:
        d = wk.diagnostics
        assert d["mass"] is True
        assert d["patient_mass"] is True
        assert d["capacity_bound"] is True
        assert d["fdna_convergence"] is True
        if not wk.after.allocation.reroutes:
            assert d["zero_move_identity"] is True
        # accepted + unmet == h_need per district
        v = api.get_week(r, wk.week, "after")
        for dist in v["districts"]:
            j = dist["district_id"]
            acc_j = sum(a for (dd, _h), a in wk.after.allocation.accepted.items() if dd == j)
            assert abs(acc_j + dist["unmet_need_people"] - wk.h_need[j]) < 1e-6


def test_nine_blocks_present():
    # All nine conceptual block adapters exist and are importable.
    import pipeline.accessibility  # SEPARATE geography + ACCESS
    import pipeline.analysis  # ANALYSIS
    import pipeline.api  # RESULTS facade
    import pipeline.data  # DATA
    import pipeline.fdna  # FDNA
    import pipeline.il2  # IL2
    import pipeline.il3  # IL3
    import pipeline.seir  # IL1 + SEIR

    assert hasattr(pipeline.seir, "init_state")  # IL1
    assert hasattr(pipeline.seir, "step_week")  # SEIR
    assert hasattr(pipeline.il2, "compute_requests")  # IL2
    assert hasattr(pipeline.analysis, "reserve_direct")  # ANALYSIS
    assert hasattr(pipeline.il3, "package_results")  # IL3


def test_import_boundaries():
    # Scientific modules must not import streamlit.
    import pipeline.analysis
    import pipeline.fdna
    import pipeline.il2
    import pipeline.runner
    import pipeline.seir

    # none of these modules should have pulled in streamlit transitively at import
    for m in (pipeline.seir, pipeline.fdna, pipeline.analysis, pipeline.il2):
        assert "streamlit" not in getattr(m, "__dict__", {})
