"""Deep immutability of result history + commit_week phase guard + input
validation. Covers attribute assignment AND nested mutation for every result
container, event payload, manifest/provenance, pickle roundtrip, and that
mutating a returned copy does not affect later weeks or a baseline rerun."""

from __future__ import annotations

import dataclasses
import pickle

import pytest

from pipeline import api
from pipeline import hospital_state as hs
from pipeline.contracts import DataValidationError
from pipeline.data import golden_fixture


def _run(weeks=4):
    cfg = api.RunConfig(
        disease=api.DiseaseConfig(r0=2.7, initial_infectious_fraction=0.004), weeks=weeks
    )
    return api.run_scenario(
        api.load_inputs("synthetic", cfg),
        [api.make_injection("c", "close_hospital", 1, {"hospital_id": "SH0"}, end_week=weeks)],
    )


def _blocked(fn):
    try:
        fn()
        return False
    except (TypeError, dataclasses.FrozenInstanceError):
        return True


def test_attribute_assignment_blocked():
    run = _run()
    wk = run.weeks[0]
    assert _blocked(lambda: setattr(wk, "week", 9))
    assert _blocked(lambda: setattr(wk.after, "phase", "x"))
    assert _blocked(lambda: setattr(wk.after.allocation, "reroute_volume", 9))
    assert _blocked(lambda: setattr(wk.after.fdna, "iterations", 9))
    st0 = next(iter(wk.end_hospital_state.values()))
    assert _blocked(lambda: setattr(st0, "baseline", 0))
    if st0.cohorts:
        assert _blocked(lambda: setattr(st0.cohorts[0], "count", 0))


def test_nested_dict_mutation_blocked():
    run = _run()
    wk = run.weeks[0]
    assert _blocked(lambda: wk.state.S.__setitem__(wk.state.district_ids[0], 1))
    assert _blocked(lambda: wk.after.allocation.unmet_by_district.__setitem__("x", 1))
    assert _blocked(lambda: wk.after.allocation.accepted.__setitem__(("a", "b"), 1))
    assert _blocked(lambda: wk.after.fdna.hospital_scores.__setitem__("x", 1))
    assert _blocked(lambda: wk.inherited_deficit.__setitem__("x", 1))
    assert _blocked(lambda: wk.diagnostics.__setitem__("x", 1))
    assert _blocked(lambda: wk.end_hospital_state.__setitem__("x", 1))
    # FrozenDict |= blocked
    assert _blocked(lambda: wk.after.allocation.unmet_by_district.__ior__({"x": 1}))


def test_injection_payload_immutable_in_history():
    run = _run()
    wk = run.weeks[1]  # injection active here
    assert wk.active_injections, "expected an active injection in week 1"
    inj = wk.active_injections[0]
    assert _blocked(lambda: inj.payload.__setitem__("x", 1))
    assert _blocked(lambda: setattr(inj, "kind", "x"))
    assert _blocked(lambda: setattr(inj, "payload", {}))


def test_mutating_a_week_copy_does_not_affect_later_weeks_or_baseline():
    cfg = api.RunConfig(
        disease=api.DiseaseConfig(r0=2.7, initial_infectious_fraction=0.004), weeks=4
    )
    inp = api.load_inputs("synthetic", cfg)
    run = api.run_scenario(inp, [])
    # grab a mutable copy of week 0 state and mutate it
    w0_state = dict(run.weeks[0].state.S)  # a plain dict copy
    did = run.weeks[0].state.district_ids[0]
    w0_state[did] = w0_state[did] + 10_000.0  # mutate the COPY
    # later weeks and a baseline rerun are unaffected
    assert run.weeks[1].state.S[did] != w0_state[did]
    run2 = api.run_scenario(inp, [])
    assert run2.run_id == run.run_id
    assert run2.weeks[0].state.S[did] == run.weeks[0].state.S[did]


def test_commit_week_rejects_before_phase():
    run = _run()
    wk = run.weeks[0]
    sm = wk.end_hospital_state
    with pytest.raises(DataValidationError):
        hs.commit_week(dict(sm), wk.before.allocation, 0, 2)


def test_pickle_roundtrip_preserves_run_id():
    run = _run()
    assert pickle.loads(pickle.dumps(run)).run_id == run.run_id


def test_duplicate_injection_ids_rejected():
    inp = api.build_inputs(golden_fixture(), api.RunConfig(weeks=2))
    with pytest.raises(DataValidationError):
        api.run_scenario(
            inp,
            [
                api.make_injection("x", "close_hospital", 0, {"hospital_id": "H1"}),
                api.make_injection("x", "close_hospital", 1, {"hospital_id": "H2"}),
            ],
        )


def test_duplicate_district_rejected():
    b = golden_fixture()
    b.districts.append(b.districts[0])  # duplicate district_id -> must reject at build/run
    with pytest.raises(DataValidationError):
        # build may dedupe via sorted IDs; the run boundary explicitly checks dupes
        api.run_scenario(api.build_inputs(b, api.RunConfig(weeks=2)), [])


def test_duplicate_hospital_rejected():
    import dataclasses

    b = golden_fixture()
    b.hospitals.append(dataclasses.replace(b.hospitals[0]))  # duplicate hospital_id
    with pytest.raises(DataValidationError):
        api.run_scenario(api.build_inputs(b, api.RunConfig(weeks=2)), [])


def test_seeded_cohort_validation():
    from pipeline.types import Cohort

    b = golden_fixture()
    b.seeded_cohorts["H1"] = [Cohort("NOPE", -1, 1, 5.0)]  # unknown origin district
    with pytest.raises(DataValidationError):
        api.run_scenario(api.build_inputs(b, api.RunConfig(weeks=2)), [])
