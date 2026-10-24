"""The engine against theory: final size, R0 and R_eff, growth, conservation, stochastic runs."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

from cascade.epi import Constant, ScenarioConfig, SEIREngine, seir, seir_h, simulate
from cascade.epi.engine import ChainBinomial, _round_rows, contact_modifier_from_config
from conftest import DATA, make_config

AGES = ("0-17", "18-64", "65+")
C3 = [[9.00, 8.09, 0.96], [2.50, 10.47, 1.18], [1.11, 4.40, 1.80]]


def three_ages(r0=2.0, days=200, **kw):
    cfg = make_config(patches=("A", "B"), ages=AGES, r0=r0, days=days,
                      counts=[[20_000, 60_000, 15_000], [10_000, 40_000, 20_000]], **kw)
    return cfg.updated({"mixing.age_contacts": C3,
                        "mixing.patch_coupling": [[0.9, 0.1], [0.2, 0.8]]})


def ode_reference(eng, X0, days):
    """The structure's own ODE, solved tightly: what the engine approximates."""
    shape, flows = X0.shape, eng.structure.flows

    def rhs(t, y):
        X = y[:X0.size].reshape(shape)
        r = eng.rates.evaluate(t, {})
        r["foi"] = r["beta"] * eng.mixing.apply(eng._infectious_load(X))
        dX, dF = np.zeros(shape), np.zeros((len(flows),) + eng.shape)
        for tr in eng.structure.transitions:
            f = np.broadcast_to(np.asarray(tr.rate(r), dtype=float), eng.shape) * X[eng._idx[tr.src]]
            dX[eng._idx[tr.src]] -= f
            dX[eng._idx[tr.dst]] += f
            dF[flows.index(tr.flow)] += f
        return np.concatenate([dX.ravel(), dF.ravel()])

    y0 = np.concatenate([X0.ravel(), np.zeros(len(flows) * X0[0].size)])
    sol = solve_ivp(rhs, (0, days), y0, t_eval=np.arange(days + 1), rtol=1e-10, atol=1e-8, method="DOP853")
    X = sol.y[:X0.size].T.reshape((-1,) + shape)[1:]
    F = np.diff(sol.y[X0.size:].T.reshape((-1, len(flows)) + eng.shape), axis=0)
    return X, {f: F[:, i] for i, f in enumerate(flows)}


@pytest.mark.parametrize("substeps", [1, 4])
def test_final_size_matches_the_closed_form_at_any_step(substeps):
    cfg = make_config(r0=1.8, days=400).updated({"sim.substeps": substeps})
    res = SEIREngine.from_config(cfg, structure=seir()).run(cfg.seeding, 400)
    z = float(res.ds["new_exposed"].sum()) / 100_000
    z_theory = brentq(lambda z: 1 - z - np.exp(-1.8 * z), 1e-6, 1)
    assert z == pytest.approx(z_theory, rel=1e-3)


def test_hospital_model_tracks_its_ode():
    cfg = three_ages(r0=2.5, days=200)
    eng = SEIREngine.from_config(cfg)
    res = eng.run(cfg.seeding, 200)
    X, F = ode_reference(eng, eng.initial_state(cfg.seeding), 200)
    for flow in ("new_exposed", "new_hosp", "new_icu", "new_deaths"):    # totals: exact at any step
        assert float(res.ds[flow].sum()) == pytest.approx(F[flow].sum(), rel=1e-4)
    census = res.series("inpatients").values
    ode_census = (X[:, eng._idx["H"]] + X[:, eng._idx["C"]]).sum(axis=(1, 2))
    assert census.max() == pytest.approx(ode_census.max(), rel=0.01)
    assert abs(int(census.argmax()) - int(ode_census.argmax())) <= 1
    assert np.abs(census - ode_census).sum() / ode_census.sum() < 0.06   # a lag of under a day


def test_r0_is_honoured_with_ages_and_patches():
    cfg = three_ages(r0=2.3)
    eng = SEIREngine.from_config(cfg)
    assert eng.r0() == pytest.approx(2.3, rel=1e-9)
    res = eng.run(cfg.seeding, 1)
    assert res.ds["r_eff"].values[0] == pytest.approx(2.3, rel=1e-3)


def test_r_eff_starts_at_r0_times_the_susceptible_share():
    cfg = three_ages(r0=2.3).updated({"seeding.immune_share": 0.4})
    eng = SEIREngine.from_config(cfg)
    assert eng.describe(seeding=cfg.seeding)["r_eff_start"] == pytest.approx(2.3 * 0.6, rel=1e-3)


def test_beta_formulas_agree_for_seir():
    cfg = make_config(r0=2.5)
    eng = SEIREngine.from_config(cfg, structure=seir())
    assert eng.beta0 == pytest.approx(SEIREngine.beta_from_r0(2.5, cfg.disease.gamma, eng.mixing))


def test_growth_rate_solves_euler_lotka():
    eng = SEIREngine.from_config(make_config(r0=2.5))
    r = eng.growth_rate()
    assert (1 + r * 3) * (1 + r * 5) == pytest.approx(2.5, rel=1e-9)
    assert eng.doubling_time() == pytest.approx(np.log(2) / r)
    assert eng.generation_time() == pytest.approx(8.0)
    below = SEIREngine.from_config(make_config(r0=0.8))
    assert below.growth_rate() < 0


def test_growth_rate_with_ages_matches_simulation():
    cfg = three_ages(r0=1.6, days=90).updated({"population.counts": [[2e7, 6e7, 1.5e7], [1e7, 4e7, 2e7]],
                                               "sim.substeps": 8})
    eng = SEIREngine.from_config(cfg)
    res = eng.run(cfg.seeding, 90)
    inc = res.series("infections").values
    simulated = np.polyfit(np.arange(60, 90), np.log(inc[60:90]), 1)[0]
    assert simulated == pytest.approx(eng.growth_rate(), rel=0.02)


def test_people_and_infections_are_conserved():
    cfg = three_ages(r0=2.0, days=150)
    res = SEIREngine.from_config(cfg).run(cfg.seeding, 150)
    total = res.compartments.to_array().sum(["variable", "age"])
    assert np.allclose(total, cfg.population.N.sum(axis=1))
    S_end = res.ds["S"].isel(time=-1)
    assert np.allclose(res.ds["new_exposed"].sum("time"), res.initial["S"] - S_end)


def test_hospital_flows_add_up():
    cfg = three_ages(r0=2.0, days=300)
    res = SEIREngine.from_config(cfg).run(cfg.seeding, 300)
    ward_exits = res.ds["new_icu"].sum() + res.ds["ward_discharges"].sum()
    assert float(res.ds["new_icu"].sum() / ward_exits) == pytest.approx(0.2, rel=0.01)
    assert float(res.ds["D"].isel(time=-1).sum()) == pytest.approx(float(res.ds["new_deaths"].sum()))
    assert np.allclose(res.series("inpatients"), res.ds["H"].sum(["patch", "age"]) + res.ds["C"].sum(["patch", "age"]))


def test_substeps_converge():
    cfg = three_ages(r0=2.5, days=120)
    peaks = [SEIREngine.from_config(cfg.updated({"sim.substeps": n})).run(cfg.seeding, 120)
             .series("inpatients").max() for n in (4, 32)]
    assert peaks[0] == pytest.approx(peaks[1], rel=0.01)


def test_isolated_patches_stay_clean_and_coupled_ones_do_not():
    base = make_config(patches=("A", "B"), r0=2.5, days=120)
    iso = SEIREngine.from_config(base).run(base.seeding, 120)
    assert float(iso.ds["new_exposed"].sel(patch="B").sum()) == 0.0
    linked = base.updated({"mixing.patch_coupling": [[0.95, 0.05], [0.05, 0.95]]})
    res = SEIREngine.from_config(linked).run(linked.seeding, 120)
    assert float(res.ds["new_exposed"].sel(patch="B").sum()) > 1000


def test_stochastic_runs_keep_whole_people():
    cfg = three_ages(r0=2.0, days=80).updated({"sim.stochastic": True, "sim.seed": 3,
                                               "seeding.initial": {"H": {"A": 7.3}}})
    eng = SEIREngine.from_config(cfg)
    assert isinstance(eng.stepper, ChainBinomial)
    res = eng.run(cfg.seeding, 80)
    values = res.compartments.to_array().values
    assert np.allclose(values, np.round(values)) and (values >= 0).all()
    assert np.allclose(res.compartments.to_array().sum(["variable", "age"]), cfg.population.N.sum(axis=1))
    again = SEIREngine.from_config(cfg).run(cfg.seeding, 80)
    assert np.array_equal(res.ds["I"].values, again.ds["I"].values)        # same seed, same run


def test_round_rows_keeps_totals():
    x = np.array([[0.4, 0.4, 0.2], [1.5, 2.5, 3.0]])
    out = _round_rows(x)
    assert np.allclose(out.sum(axis=1), [1, 7]) and np.allclose(out, np.round(out))


def test_missing_and_bad_rates_fail_at_build_time():
    cfg = make_config()
    waning = seir_h().extend(transitions=(seir_h().transitions[0].__class__("R", "S", lambda r: r["waning"],
                                                                             "new_waned"),))
    with pytest.raises(KeyError, match="needs rate 'waning'"):
        SEIREngine.from_config(cfg, structure=waning)
    with pytest.raises(ValueError, match="negative"):
        SEIREngine.from_config(cfg, structure=waning, waning=Constant(-0.1))
    with pytest.raises(ValueError, match="does not fit"):
        SEIREngine.from_config(cfg, p_hosp=Constant([0.1, 0.2, 0.3]))


def test_stays_shorter_than_a_substep_are_refused_or_capped():
    cfg = make_config(latent=0.2)                                   # sigma = 5 per day
    with pytest.raises(ValueError, match="sim.substeps to at least 5"):
        SEIREngine.from_config(cfg)
    SEIREngine.from_config(cfg.updated({"sim.substeps": 5}))
    from cascade.epi import Product, Signal
    eng = SEIREngine.from_config(make_config(), ward_exit=Product(Constant(0.2), Signal("speed")))
    X = eng.initial_state(make_config().seeding)
    X[eng._idx["E"]] = X[eng._idx["I"]] = 0.0                     # no new admissions today
    X[eng._idx["H"]] = 100.0
    with pytest.warns(RuntimeWarning, match="capped"):
        X1, rec = eng.step_day(X, 0, {"speed": 50.0})             # 10 per day against substeps of 1/4
    assert (X1 >= 0).all() and X1[eng._idx["H"]].sum() == 0.0   # everyone left in the first substep
    assert rec.flows["new_icu"].sum() + rec.flows["ward_discharges"].sum() == pytest.approx(100)


def test_a_rate_pushed_negative_mid_run_says_how_to_fix_it():
    cfg = make_config()
    from cascade.epi import Product, Signal
    eng = SEIREngine.from_config(cfg, p_hosp=Product(Constant(0.5), Signal("m")))
    X = eng.initial_state(cfg.seeding)
    with pytest.raises(ValueError, match="rates.Clip"):
        eng.step_day(X, 0, {"m": 3.0})                       # p_hosp 1.5 -> 1 - p_hosp < 0


def test_signals_reach_the_rates():
    cfg = make_config(days=10)
    eng = SEIREngine.from_config(cfg, feedback=("contact_multiplier",))
    res = eng.run(cfg.seeding, 10, signals_fn=lambda day, X: {"contact_multiplier": 0.5 if day >= 5 else 1.0})
    beta = res.ds["transmission_rate"].values
    assert beta[6] == pytest.approx(0.5 * beta[2])


@pytest.mark.parametrize("spec, day, expected", [
    ({"steps": {0: 1.0, 10: 0.5}}, 12, 0.5),
    ({"steps": {0: 0, 10: -50}, "percent_change": True}, 12, 0.5),
    ({"steps": {10: 60}, "baseline": 120}, 12, 0.5),
    ({"values": [1.0, 1.0, 0.2]}, 2, 0.2),
    ({"steps": {10: 0.5}, "elasticity": 0.5}, 12, 0.75),
])
def test_contact_multiplier_from_config(spec, day, expected):
    cfg = make_config().updated({"mixing.contact_multiplier": spec})
    assert contact_modifier_from_config(cfg)(day, {}) == pytest.approx(expected)


def test_contact_multiplier_from_a_dated_csv_lines_up_with_the_start():
    cfg = ScenarioConfig.model_validate({
        **make_config().model_dump(),
        "mixing": {"contact_multiplier": {"csv": str(DATA / "google_mobility_massachusetts.csv"),
                                          "column": "transit_stations", "percent_change": True}}})
    cfg = cfg.updated({"sim.start": date(2020, 4, 15)})
    m = contact_modifier_from_config(cfg)
    assert m(0, {}) < 0.5                  # transit far below normal in April 2020


def test_simulate_is_build_and_run(example):
    a = simulate(example, days=20)
    b = SEIREngine.from_config(example).run(example.seeding, 20)
    assert np.allclose(a.ds["I"], b.ds["I"])


def test_describe_is_plain_numbers(example):
    import json
    d = SEIREngine.from_config(example).describe(seeding=example.seeding)
    json.dumps(d)
    assert d["r0"] == pytest.approx(2.8) and d["r_eff_start"] == pytest.approx(2.8, rel=1e-3)
    assert d["infection_path"] == ["E", "I"] and d["population"] == 198_000
