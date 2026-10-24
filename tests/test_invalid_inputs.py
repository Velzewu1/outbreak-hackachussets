"""Focused invalid-input rejection tests for the backend contract boundary."""

from __future__ import annotations

import dataclasses

import pytest

from pipeline import api
from pipeline.contracts import DataValidationError, InvalidInjection, RunConfig
from pipeline.data import golden_fixture


def _run(bundle, injections=()):
    return api.run_scenario(api.build_inputs(bundle, RunConfig(weeks=2)), list(injections))


def test_malformed_entity_values_rejected():
    import math

    b = golden_fixture()
    b.districts[0] = dataclasses.replace(b.districts[0], risk_weight=-1.0)
    with pytest.raises(DataValidationError):
        _run(b)

    b = golden_fixture()
    b.districts[0] = dataclasses.replace(b.districts[0], population=0)
    with pytest.raises(DataValidationError):
        _run(b)

    b = golden_fixture()
    b.hospitals[0] = dataclasses.replace(b.hospitals[0], staffed_beds=0)
    with pytest.raises(DataValidationError):
        _run(b)

    b = golden_fixture()
    b.hospitals[0] = dataclasses.replace(b.hospitals[0], lat=math.inf)
    with pytest.raises(DataValidationError):
        _run(b)

    b = golden_fixture()
    b.hospitals[0] = dataclasses.replace(b.hospitals[0], lat=200.0)  # out of range
    with pytest.raises(DataValidationError):
        _run(b)


def test_injection_nonempty_id_and_integer_weeks():
    with pytest.raises(InvalidInjection):
        api.make_injection("", "close_hospital", 0, {"hospital_id": "H1"})
    with pytest.raises(InvalidInjection):
        api.make_injection("i", "close_hospital", 1.5, {"hospital_id": "H1"})
    with pytest.raises(InvalidInjection):
        api.make_injection("i", "close_hospital", True, {"hospital_id": "H1"})
    with pytest.raises(InvalidInjection):
        api.make_injection("i", "close_hospital", 0, {"hospital_id": "H1"}, end_week=1.5)


def test_unknown_event_target_rejected_even_future():
    b = golden_fixture()
    # future-dated event (weeks beyond horizon) with an unknown hospital must fail
    inj = api.make_injection("x", "close_hospital", 50, {"hospital_id": "NOPE"}, end_week=52)
    with pytest.raises(InvalidInjection):
        _run(b, [inj])


def test_set_share_ineligible_hospital_rejected():
    # golden D1 is eligible to H1,H2,H3 (all within radius). Target a hospital that
    # exists but is not in D1's eligible catchment by first removing it from range:
    # simplest deterministic check -> set_share to a hospital id that is not eligible.
    b = golden_fixture()
    # make H3 ineligible for D1 by moving D1 far from H3? Instead target unknown-in-
    # catchment via a tiny radius config so only H1 is eligible, then share->H2.
    cfg = RunConfig(
        weeks=2, network=dataclasses.replace(RunConfig().network, radius_km=2.0, k_nearest=1)
    )
    inp = api.build_inputs(b, cfg)
    inj = api.make_injection(
        "s", "set_share", 0, {"district_id": "D1", "hospital_id": "H2", "share": 0.5}
    )
    with pytest.raises(DataValidationError):
        api.run_scenario(inp, [inj])


def test_runconfig_fallback_must_be_bool():
    with pytest.raises(DataValidationError):
        RunConfig(nearest_outside_radius_fallback="yes").validate()


def test_seeded_cohort_nonfinite_and_bad_los_rejected():
    import math

    from pipeline.types import Cohort

    b = golden_fixture()
    b.seeded_cohorts["H1"] = [Cohort("D1", -1, 1, math.nan)]
    with pytest.raises(DataValidationError):
        _run(b)

    b = golden_fixture()
    b.seeded_cohorts["H1"] = [Cohort("D1", -1, 0, 5.0)]  # LOS < 1
    with pytest.raises(DataValidationError):
        _run(b)

    b = golden_fixture()
    b.seeded_cohorts["H1"] = [Cohort("D1", 0, 1, 5.0)]  # admit_week >= 0 not allowed
    with pytest.raises(DataValidationError):
        _run(b)
