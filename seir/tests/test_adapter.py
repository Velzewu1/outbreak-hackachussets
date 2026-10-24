"""The FDNA plug: EpiSnapshot's contract, the shared loop and the one-day feedback lag."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from cascade.core import Simulation
from cascade.epi import EpiSnapshot, SEIREngine, SEIRModule, with_asymptomatic, seir_h, Constant

V1_FIELDS = ["day", "date", "patches", "population", "infectious", "prevalence", "new_hosp", "new_icu",
             "transmission_rate", "incubation_rate", "recovery_rate", "force_of_infection", "r_eff"]


def test_snapshot_fields_only_grow():
    fields = dataclasses.fields(EpiSnapshot)
    names = [f.name for f in fields]
    assert names[:len(V1_FIELDS)] == V1_FIELDS                 # never renamed, removed or reordered
    added = fields[len(V1_FIELDS):]
    assert added and all(f.default is None for f in added)      # added later, with defaults
    snap = EpiSnapshot(*[None] * len(V1_FIELDS))                # an old-style constructor still works
    assert snap.ward_census is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.day = 3


def test_module_writes_a_snapshot_per_day(example):
    module = SEIRModule.from_config(example)
    state = Simulation([module]).run(30)
    snap = state.epi
    assert snap.day == 29 and str(snap.date) == "2021-12-30"
    assert snap.patches == ("Dorchester", "Roxbury", "Back Bay")
    for name in ("population", "infectious", "prevalence", "new_hosp", "new_icu", "force_of_infection",
                 "susceptible", "exposed", "new_infections", "new_deaths", "ward_census", "icu_census"):
        assert getattr(snap, name).shape == (3,), name
    assert np.allclose(snap.prevalence, snap.infectious / snap.population)
    assert isinstance(snap.transmission_rate, float) and isinstance(snap.r_eff, float)
    res = module.result()
    last = res.ds.isel(time=-1).sum("age")
    assert np.allclose(snap.ward_census, last["H"]) and np.allclose(snap.new_hosp, last["new_hosp"])


def test_module_matches_a_plain_run(example):
    module = SEIRModule.from_config(example)
    Simulation([module]).run(40)
    direct = SEIREngine.from_config(example).run(example.seeding, 40)
    assert np.allclose(module.result().ds["I"], direct.ds["I"])


def test_feedback_written_today_is_read_tomorrow(example):
    engine = SEIREngine.from_config(example, feedback=("contact_multiplier",))

    class Lockdown:
        name = "policy"

        def step(self, state, t):
            if t == 10:
                state.signals.setdefault("seir", {})["contact_multiplier"] = 0.0
            return state

    module = SEIRModule(engine, example.seeding)
    Simulation([module, Lockdown()]).run(20)
    beta = module.result().ds["transmission_rate"].values
    assert beta[10] > 0 and beta[11] == 0.0                   # SEIR runs first, so the change lands next day
    assert float(module.result().ds["new_exposed"].isel(time=slice(11, None)).sum()) == 0.0


def test_per_patch_signals_reach_only_their_patch(example):
    engine = SEIREngine.from_config(example, feedback=("icu_mortality_multiplier",))
    X = engine.initial_state(example.seeding)
    for day in range(60):
        X, rec = engine.step_day(X, day)
    _, normal = engine.step_day(X, 60)
    _, strained = engine.step_day(X, 60, {"icu_mortality_multiplier": np.array([2.0, 1.0, 1.0])})
    deaths = strained.flows["new_deaths"].sum(axis=1) / normal.flows["new_deaths"].sum(axis=1)
    assert deaths == pytest.approx([2.0, 1.0, 1.0])


def test_snapshot_follows_the_structure(example):
    engine = SEIREngine.from_config(example, structure=with_asymptomatic(seir_h()), p_asym=Constant(0.4))
    module = SEIRModule(engine, example.seeding)
    state = Simulation([module]).run(25)
    last = module.result().ds.isel(time=-1).sum("age")
    assert np.allclose(state.epi.infectious, last["I"] + last["A"])     # A transmits, so it counts
    assert np.allclose(state.epi.new_infections, last["new_exposed"])
