"""Scenario validation: presets, shapes, seeding, contact multipliers, copies and YAML."""
from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from cascade.epi import DISEASES, ScenarioConfig, SEIREngine
from cascade.epi.config import ContactMultiplier, DiseaseParams, Seeding
from conftest import SCENARIOS, make_config


# ---- disease --------------------------------------------------------------
def test_preset_fills_values_and_fields_override_it():
    d = DiseaseParams.model_validate({"preset": "covid_omicron", "r0": 2.0})
    assert d.r0 == 2.0
    assert d.latent_period == DISEASES["covid_omicron"]["latent_period"]
    assert d.name == "covid_omicron"
    assert d.sigma == pytest.approx(1 / d.latent_period) and d.gamma == pytest.approx(1 / d.infectious_period)


def test_unknown_preset_and_typos_fail_loudly():
    with pytest.raises(ValidationError, match="unknown disease preset"):
        DiseaseParams.model_validate({"preset": "covid_2030"})
    with pytest.raises(ValidationError, match="Extra inputs"):
        DiseaseParams.model_validate({"preset": "measles", "r_0": 12})


@pytest.mark.parametrize("bad", [{"p_hosp": 1.5}, {"p_icu": [0.1, -0.1, 0.2]}, {"r0": 0}, {"los_icu": -1}])
def test_disease_values_are_checked(bad):
    with pytest.raises(ValidationError):
        DiseaseParams.model_validate({"r0": 2, "latent_period": 3, "infectious_period": 5, **bad})


def test_per_age_values_by_label_become_lists_in_age_order():
    cfg = make_config(ages=("old", "young"), counts=[[10_000, 20_000]], p_hosp={"young": 0.01, "old": 0.2})
    assert cfg.disease.p_hosp == [0.2, 0.01]
    with pytest.raises(ValidationError, match="do not match"):
        make_config(ages=("old", "young"), counts=[[10_000, 20_000]], p_hosp={"kids": 0.01, "old": 0.2})
    with pytest.raises(ValidationError, match="2 age groups"):
        make_config(ages=("old", "young"), counts=[[10_000, 20_000]], p_hosp=[0.1, 0.2, 0.3])


def test_preset_by_age_needs_the_project_age_bands():
    with pytest.raises(ValidationError, match="labels"):
        ScenarioConfig.model_validate({
            "disease": {"preset": "covid_omicron"},
            "population": {"patches": ["A"], "ages": ["0-49", "50+"], "counts": [[1000, 1000]]},
            "seeding": {"exposed": {"A": 1}}, "sim": {"start": "2022-01-01", "days": 5}})


# ---- population and mixing --------------------------------------------------
@pytest.mark.parametrize("counts", [[[100, 100]], [[100], [0]], [[100], [-5]], [[float("nan")], [1]]])
def test_population_must_be_positive_and_shaped(counts):
    with pytest.raises(ValidationError):
        make_config(patches=("A", "B"), counts=counts)


def test_names_must_be_unique():
    with pytest.raises(ValidationError, match="unique"):
        make_config(patches=("A", "A"))


def test_mixing_shapes_and_coupling_rows(example):
    data = example.model_dump()
    data["mixing"]["patch_coupling"][0] = [0.5, 0.1, 0.1]
    with pytest.raises(ValidationError, match="sum to 1"):
        ScenarioConfig.model_validate(data)
    data = example.model_dump()
    data["mixing"]["age_contacts"] = [[1, 2], [3, 4]]
    with pytest.raises(ValidationError, match="age_contacts must be 3 x 3"):
        ScenarioConfig.model_validate(data)
    data = example.model_dump()
    data["mixing"]["age_contacts"] = [[0] * 3] * 3
    with pytest.raises(ValidationError, match="not all zero"):
        ScenarioConfig.model_validate(data)


def test_defaults_mean_one_place_and_even_contacts():
    cfg = make_config(patches=("A", "B"), ages=("x", "y"), counts=[[100, 200], [300, 400]], seeds={"A": 1})
    assert np.array_equal(cfg.coupling_matrix(), np.eye(2))
    assert np.allclose(cfg.contact_matrix(), 0.5)


# ---- seeding ------------------------------------------------------------------
def test_seeding_checks_patches_and_capacity():
    with pytest.raises(ValidationError, match="unknown patches"):
        make_config(seeds={"Nowhere": 5})
    with pytest.raises(ValidationError, match="exceeds its susceptible population"):
        make_config(seeds={"A": 200_000})
    cfg = make_config()
    with pytest.raises(ValidationError, match="exceeds"):
        cfg.updated({"seeding.immune_share": 0.9999, "seeding.exposed": {"A": 50}})
    with pytest.raises(ValidationError, match="between 0 and 1"):
        cfg.updated({"seeding.immune_share": 1.2})


def test_immune_share_per_patch():
    cfg = make_config(patches=("A", "B")).updated({"seeding.immune_share": {"B": 0.3}})
    assert np.allclose(cfg.immune_share(), [0.0, 0.3])
    X = SEIREngine.from_config(cfg).initial_state(cfg.seeding)
    eng = SEIREngine.from_config(cfg)
    assert X[eng.structure.index("R")].sum(axis=1) == pytest.approx([0.0, 30_000])


def test_initial_counts_go_to_named_compartments():
    cfg = make_config(ages=("young", "old"), counts=[[60_000, 40_000]])
    cfg = cfg.updated({"seeding.initial": {"H": {"A": 100}, "C": {"A": [0, 7]}}})
    eng = SEIREngine.from_config(cfg)
    X = eng.initial_state(cfg.seeding)
    assert X[eng.structure.index("H")][0] == pytest.approx([60, 40])     # spread by population
    assert X[eng.structure.index("C")][0] == pytest.approx([0, 7])       # given per age
    assert X.sum() == pytest.approx(100_000)


@pytest.mark.parametrize("initial, message", [
    ({"H": {"A": [1, 2, 3]}}, "one count per age group"),
    ({"H": {"A": -1}}, "non-negative"),
    ({"H": {"Z": 1}}, "unknown patches"),
    ({"exposed": {"A": 1}}, "use seeding.exposed"),
])
def test_initial_counts_are_validated(initial, message):
    cfg = make_config(ages=("young", "old"), counts=[[60_000, 40_000]])
    with pytest.raises(ValidationError, match=message):
        cfg.updated({"seeding.initial": initial})


def test_initial_counts_must_name_a_compartment_of_the_structure():
    cfg = make_config().updated({"seeding.initial": {"Q": {"A": 1}}})
    eng = SEIREngine.from_config(cfg)
    with pytest.raises(ValueError, match="'Q'"):
        eng.initial_state(cfg.seeding)


def test_seeding_counts_merges_every_source():
    s = Seeding(exposed={"A": 1}, infectious={"A": 2}, initial={"H": {"A": [1, 2]}})
    counts = s.counts(2)
    assert counts["exposed"] == {"A": 1} and counts["infectious"] == {"A": 2}
    assert np.array_equal(counts["H"]["A"], [1, 2])


# ---- contact multiplier ----------------------------------------------------------
@pytest.mark.parametrize("spec, message", [
    ({}, "exactly one"),
    ({"values": [1, 1], "steps": {0: 1}}, "exactly one"),
    ({"csv": "x.csv", "baseline": 2, "baseline_dates": ["2021-01-01", "2021-01-07"]}, "at most one"),
    ({"values": [1], "baseline_dates": ["2021-01-01", "2021-01-07"]}, "dated csv"),
    ({"csv": "x.csv", "baseline_dates": ["2021-01-07", "2021-01-01"]}, r"\[start, end\]"),
    ({"steps": {0: 1}, "smooth_days": 7}, "smooth_days"),
    ({"values": [1], "elasticity": -1}, "greater than or equal"),
])
def test_contact_multiplier_validation(spec, message):
    with pytest.raises(ValidationError, match=message):
        ContactMultiplier.model_validate(spec)


# ---- copies and files ------------------------------------------------------------------
def test_updated_changes_dotted_paths_and_validates(example):
    c = example.updated({"disease.r0": 1.5, "sim.days": 10, "seeding.exposed.Roxbury": 5})
    assert c.disease.r0 == 1.5 and c.sim.days == 10 and c.seeding.exposed["Roxbury"] == 5
    assert example.disease.r0 == 2.8                       # the original is untouched
    with pytest.raises(KeyError, match="not a section"):
        example.updated({"disease.r0.x": 1})
    with pytest.raises(ValidationError):
        example.updated({"disease.r0": -1})


def test_updated_with_a_preset_swaps_the_whole_disease(example):
    c = example.updated({"disease.r0": 1.9, "disease.preset": "influenza_pandemic_2009"})
    assert c.disease.name == "influenza_pandemic_2009"
    assert c.disease.r0 == 1.9                                       # applied on top of the preset
    assert c.disease.los_icu == DISEASES["influenza_pandemic_2009"]["los_icu"]


def test_yaml_round_trip(tmp_path, example):
    path = tmp_path / "copy.yaml"
    example.to_yaml(path)
    again = ScenarioConfig.from_yaml(path)
    assert again == example


def test_csv_paths_resolve_relative_to_the_yaml_file():
    cfg = ScenarioConfig.from_yaml(SCENARIOS / "omicron_2021_mobility.yaml")
    assert cfg.mixing.contact_multiplier.csv.endswith("data/google_mobility_massachusetts.csv")
    assert (SCENARIOS.parent / "data" / "google_mobility_massachusetts.csv").exists()
