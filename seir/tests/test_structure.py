"""Model structures as data: validation, the infection path and its closed forms."""
from __future__ import annotations

import numpy as np
import pytest

from cascade.epi import (ModelStructure, Transition, seir, seir_h, with_asymptomatic, with_vaccination,
                         with_waning)

RATES = {"beta": 0.3, "sigma": 1 / 3, "gamma": 1 / 5, "p_hosp": 0.1, "p_icu": 0.2, "p_death_icu": 0.3,
         "ward_exit": 1 / 5, "icu_exit": 1 / 9, "foi": 0.0}


def T(src, dst, flow, rate=0.1):
    return Transition(src, dst, lambda r: rate, flow)


@pytest.mark.parametrize("comps, trans, message", [
    (("S", "E", "I", "S"), (), "unique"),
    (("S", "E", "I"), (T("S", "X", "f"),), "unknown compartment"),
    (("S", "E", "I"), (T("E", "E", "f"),), "to itself"),
    (("S", "E", "I"), (T("S", "E", "f"), T("E", "I", "f")), "flow names must be unique"),
    (("S", "E", "I"), (T("S", "E", "I"), T("E", "I", "g")), "clash"),
    (("S", "E", "I"), (T("S", "E", "f"),), "no infectious compartment"),
])
def test_bad_structures_are_rejected(comps, trans, message):
    with pytest.raises(ValueError, match=message):
        ModelStructure(compartments=comps, transitions=trans)


def test_unknown_role_compartment():
    with pytest.raises(ValueError, match="is not a compartment"):
        ModelStructure(compartments=("S", "E", "I"), transitions=(T("S", "E", "f"), T("E", "I", "g")),
                       infectious={"Z": 1.0})


def test_infection_paths():
    assert seir().infection_path == ("E", "I")
    assert seir_h().infection_path == ("E", "I")              # hospital patients do not transmit
    assert with_asymptomatic(seir_h()).infection_path == ("E", "I", "A")
    assert with_waning(seir()).infection_path == ("E", "I")   # never back through S
    assert with_vaccination(seir_h()).infection_path == ("E", "I")


def test_flows_and_extend():
    st = seir_h()
    assert st.flows == ("new_exposed", "new_infectious", "new_recovered", "new_hosp", "new_icu",
                        "ward_discharges", "new_deaths", "icu_discharges")
    assert [t.flow for t in st.by_source()["I"]] == ["new_recovered", "new_hosp"]
    waned = with_waning(st)
    assert waned.compartments == st.compartments and "new_waned" in waned.flows
    assert st.flows == waned.flows[:-1]                       # the original is unchanged


def test_infectious_days_is_one_over_gamma_for_seir():
    shape = (2, 3)
    D = seir_h().infectious_days(RATES, shape)
    assert D.shape == shape and np.allclose(D, 5.0)


def test_infectious_days_with_an_asymptomatic_stage():
    st = with_asymptomatic(seir(), relative_infectiousness=0.5)
    D = st.infectious_days({**RATES, "p_asym": 0.4}, (1, 1))
    assert D.item() == pytest.approx(0.6 * 5 + 0.4 * 0.5 * 5)


def test_discounted_infectious_days_match_the_laplace_transform():
    r = 0.1
    D = seir().infectious_days(RATES, (1, 1), discount=r).item()
    s, g = RATES["sigma"], RATES["gamma"]
    # Time-weighted infectiousness e^{-r a}: (s / (s + r)) * (1 / (g + r)).
    assert D == pytest.approx(s / (s + r) / (g + r))


def test_generation_time_is_latent_plus_infectious():
    assert seir_h().generation_time(RATES, (1, 1)).item() == pytest.approx(3 + 5)


def test_per_age_rates_give_per_cell_values():
    rates = {**RATES, "gamma": np.array([1 / 4, 1 / 5, 1 / 8])}
    D = seir_h().infectious_days(rates, (2, 3))
    assert np.allclose(D, [[4, 5, 8], [4, 5, 8]])


def test_susceptibility_reads_vaccine_efficacy():
    st = with_vaccination(seir_h())
    s = st.susceptibility({**RATES, "vax_rate": 0.01, "vax_efficacy": 0.7}, (1, 2))
    assert np.allclose(s["S"], 1.0) and np.allclose(s["V"], 0.3)
