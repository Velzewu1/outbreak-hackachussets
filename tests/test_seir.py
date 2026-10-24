"""SEIR need-state model tests: mass conservation, nonnegativity, seed-0,
convergence, risk-weight affects need not the shared curve, week continuity."""

from __future__ import annotations

from pipeline.contracts import DiseaseConfig, District
from pipeline.seir import carry_state, init_state, step_week

DISTRICTS = [
    District("D1", 10000, 1.0, None, 42.33, -71.08),
    District("D2", 20000, 1.5, None, 42.34, -71.10),
    District("D3", 15000, 0.8, None, 42.30, -71.06),
]
RW = {d.district_id: d.risk_weight for d in DISTRICTS}


def test_initial_mass_conservation():
    s = init_state(DISTRICTS, DiseaseConfig())
    for j in s.district_ids:
        assert abs(s.S[j] + s.E[j] + s.I[j] + s.R[j] - s.N[j]) < 1e-9
    assert s.week == 0


def test_step_week_conserves_mass_and_nonneg():
    cfg = DiseaseConfig(r0=2.5)
    s = init_state(DISTRICTS, cfg)
    out = step_week(s, cfg, RW)
    e = out.state_end
    for j in e.district_ids:
        total = e.S[j] + e.E[j] + e.I[j] + e.R[j]
        assert abs(total - e.N[j]) < 1e-6 * e.N[j]
        for comp in (e.S[j], e.E[j], e.I[j], e.R[j]):
            assert comp >= -1e-9
    # boundary index incremented; interval index is input week
    assert out.week == 0
    assert e.week == 1


def test_seed_zero_no_need():
    cfg = DiseaseConfig(initial_infectious_fraction=0.0)
    s = init_state(DISTRICTS, cfg)
    out = step_week(s, cfg, RW)
    for j in out.h_need:
        assert out.h_need[j] == 0.0
        assert out.i_exit[j] == 0.0
        assert out.new_infections[j] == 0.0


def test_week_continuity():
    cfg = DiseaseConfig(r0=2.5)
    s0 = init_state(DISTRICTS, cfg)
    o0 = step_week(s0, cfg, RW)
    s1 = carry_state(o0.state_end)
    # carry preserves the boundary index (does not double-increment)
    assert s1.week == 1
    o1 = step_week(s1, cfg, RW)
    assert o1.week == 1
    assert o1.state_end.week == 2
    # week 1 starts from week-0 end, not a fresh seed
    assert abs(s1.I["D1"] - o0.state_end.I["D1"]) < 1e-12


def test_risk_weight_scales_need_not_curve():
    cfg = DiseaseConfig(r0=2.5)
    s = init_state(DISTRICTS, cfg)
    out = step_week(s, cfg, RW)
    # Normalized S/E/I/R fractions equal across districts (shared curve)
    frac = {j: out.state_end.I[j] / out.state_end.N[j] for j in out.state_end.district_ids}
    vals = list(frac.values())
    assert max(vals) - min(vals) < 1e-9
    # but per-capita need scales with risk_weight: D2 (rw 1.5) > D1 (rw 1.0) per capita
    need_pc = {j: out.h_need[j] / out.state_end.N[j] for j in out.h_need}
    assert need_pc["D2"] > need_pc["D1"] > need_pc["D3"]


def test_determinism():
    cfg = DiseaseConfig(r0=2.7)
    s = init_state(DISTRICTS, cfg)
    a = step_week(s, cfg, RW)
    b = step_week(init_state(DISTRICTS, cfg), cfg, RW)
    for j in a.h_need:
        assert abs(a.h_need[j] - b.h_need[j]) < 1e-12
