from datetime import date
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

from cascade.core import SimState, Simulation
from cascade.epi import (ScenarioConfig, Seeding, SEIREngine, SEIRModule, Signal,
                         Transition, seir, seir_h)
from cascade.epi.calibrate import Param, calibrate
from cascade.epi.rates import Constant, Product

SCENARIO = Path(__file__).parent.parent / "scenarios" / "example_3patch.yaml"


def one_patch(r0=2.5, latent=3.0, infectious=5.0, n=1_000_000, days=200, **kw):
    return ScenarioConfig.model_validate({
        "disease": {"r0": r0, "latent_period": latent, "infectious_period": infectious, **kw},
        "population": {"patches": ["city"], "counts": [[n]]},
        "seeding": {"exposed": {"city": 10}},
        "sim": {"start": date(2021, 12, 1), "days": days, "substeps": 8},
    })


def test_population_is_conserved():
    cfg = ScenarioConfig.from_yaml(SCENARIO)
    res = SEIREngine.from_config(cfg).run(cfg.seeding, cfg.sim.days)
    total = res.compartments.to_array().sum(["variable", "patch", "age"])
    assert np.allclose(total, cfg.population.N.sum())


def test_matches_reference_ode():
    cfg = one_patch()
    res = SEIREngine.from_config(cfg, structure=seir()).run(cfg.seeding, cfg.sim.days)
    N, s, g = 1e6, cfg.disease.sigma, cfg.disease.gamma
    b = cfg.disease.r0 * g

    def f(t, y):
        S, E, I, R = y
        return [-b * S * I / N, b * S * I / N - s * E, s * E - g * I, g * I]

    ref = solve_ivp(f, (0, 200), [N - 10, 10, 0, 0], t_eval=np.arange(1, 201), rtol=1e-8)
    I_model = res.ds["I"].sum(["patch", "age"]).values
    assert abs(I_model.max() - ref.y[2].max()) / ref.y[2].max() < 0.02
    assert abs(I_model.argmax() - ref.y[2].argmax()) <= 1


def test_r_eff_starts_at_r0_and_rates_are_outputs():
    cfg = ScenarioConfig.from_yaml(SCENARIO)
    res = SEIREngine.from_config(cfg).run(cfg.seeding, 30)
    assert res.ds["r_eff"].values[0] == pytest.approx(cfg.disease.r0, rel=1e-3)
    assert res.ds["incubation_rate"].values[0] == pytest.approx(1 / 3)
    assert res.ds["recovery_rate"].values[0] == pytest.approx(1 / 5)
    assert "transmission_rate" in res.rates and "force_of_infection" in res.rates


def test_early_growth_matches_theory():
    cfg = one_patch(n=1e9, days=60)
    res = SEIREngine.from_config(cfg, structure=seir()).run(cfg.seeding, 60)
    inc = res.ds["new_exposed"].sum(["patch", "age"]).values
    r_model = np.polyfit(np.arange(30, 60), np.log(inc[30:60]), 1)[0]
    s, g, R0 = cfg.disease.sigma, cfg.disease.gamma, cfg.disease.r0
    r_theory = brentq(lambda r: (1 + r / s) * (1 + r / g) - R0, 1e-6, 2)
    assert r_model == pytest.approx(r_theory, rel=0.02)


def test_time_varying_transmission_from_mobility():
    cfg = one_patch(days=40)
    lockdown = lambda t, s: 1.0 if t < 20 else 0.4
    res = SEIREngine.from_config(cfg, structure=seir(), contact_modifier=lockdown).run(cfg.seeding, 40)
    beta = res.ds["transmission_rate"].values
    assert beta[25] == pytest.approx(0.4 * beta[5])


def test_stochastic_mean_tracks_deterministic():
    cfg = one_patch(n=200_000, days=120)
    det = SEIREngine.from_config(cfg, structure=seir()).run(cfg.seeding, 120)
    peaks = []
    for seed in range(20):
        c = cfg.model_copy(update={"sim": cfg.sim.model_copy(update={"stochastic": True, "seed": seed})})
        r = SEIREngine.from_config(c, structure=seir()).run(c.seeding, 120)
        assert (r.compartments.to_array() >= 0).all()
        peaks.append(r.ds["I"].sum(["patch", "age"]).max().item())
    det_peak = det.ds["I"].sum(["patch", "age"]).max().item()
    assert np.median(peaks) == pytest.approx(det_peak, rel=0.15)


def test_add_compartment_without_touching_engine():
    # Waning immunity: R -> S. One new transition, no engine change.
    structure = seir().extend(transitions=(Transition("R", "S", lambda r: r["waning"], "new_waned"),))
    cfg = one_patch(days=400)
    eng = SEIREngine.from_config(cfg, structure=structure, waning=Constant(1 / 90))
    res = eng.run(cfg.seeding, 400)
    assert res.ds["new_waned"].sum() > 0
    assert res.ds["I"].sum(["patch", "age"]).values[-1] > 1  # endemic, not burned out


def test_plugs_into_simulation_and_reads_fdna_feedback():
    cfg = ScenarioConfig.from_yaml(SCENARIO)
    # ICU deaths rise when FDNA reports ICU strain for a patch.
    p_death = Product(Constant(cfg.disease.p_death_icu),
                      Signal("icu_mortality_multiplier", default=1.0, per_patch=True))
    engine = SEIREngine.from_config(cfg, p_death_icu=p_death)

    class FakeFDNA:
        name = "fdna"

        def step(self, state, t):
            strained = state.epi.new_icu > 2
            state.signals.setdefault("seir", {})["icu_mortality_multiplier"] = np.where(strained, 1.5, 1.0)
            state.history.append(state.epi)
            return state

    state = Simulation([SEIRModule(engine, cfg.seeding), FakeFDNA()]).run(90)
    snap = state.history[-1]
    assert snap.new_hosp.shape == (3,) and snap.prevalence.shape == (3,)
    assert isinstance(snap.recovery_rate, float)
    assert any((s.new_icu > 2).any() for s in state.history)


def test_calibration_recovers_known_parameters():
    base = ScenarioConfig.from_yaml(SCENARIO)

    def simulate(p):
        d = base.disease.model_copy(update={"r0": p["r0"]})
        cfg = base.model_copy(update={"disease": d})
        hosp_scale = Constant(p["hosp_scale"] * np.asarray(base.disease.p_hosp))
        return SEIREngine.from_config(cfg, p_hosp=hosp_scale).run(cfg.seeding, 90)

    def weekly(res):
        return res.ds["new_hosp"].sum(["patch", "age"]).values[:84].reshape(12, 7).sum(1)

    truth = weekly(simulate({"r0": 2.2, "hosp_scale": 1.3}))
    fit = calibrate(simulate, weekly, truth,
                    {"r0": Param(3.0, 1.2, 5.0), "hosp_scale": Param(1.0, 0.3, 3.0)})
    assert fit.params["r0"] == pytest.approx(2.2, rel=0.02)
    assert fit.params["hosp_scale"] == pytest.approx(1.3, rel=0.05)
