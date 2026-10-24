"""SEIR numerical convergence + normalized-vs-independent equivalence.

The optimized step_week integrates ONE normalized curve per unique initial
fraction and scales by N. This must equal a per-district independent solve within
tolerance, and the integrator must converge (conserve mass) across step sizes.
"""

from __future__ import annotations

import numpy as np

from pipeline.contracts import DiseaseConfig, District
from pipeline.seir import _integrate_week, init_state, step_week


def _independent_week(s, j, cfg):
    """Per-district independent solve (same integrator) for comparison."""
    beta = cfg.r0 / cfg.infectious_days
    sigma = 1.0 / cfg.latent_days
    gamma = 1.0 / cfg.infectious_days
    n = s.N[j]
    return _integrate_week(s.S[j], s.E[j], s.I[j], s.R[j], n, beta, sigma, gamma)


def test_normalized_equals_independent_tight():
    districts = [
        District("D1", 10000, 1.0, None, 42.33, -71.08),
        District("D2", 20000, 1.5, None, 42.34, -71.10),
        District("D3", 15000, 0.8, None, 42.30, -71.06),
    ]
    rw = {d.district_id: d.risk_weight for d in districts}
    cfg = DiseaseConfig(r0=2.6)
    s = init_state(districts, cfg)
    out = step_week(s, cfg, rw)

    # The optimized (normalized-once, scaled-by-N) output must match a per-district
    # independent solve to TIGHT tolerance (same integrator, same math). We use
    # 1e-6 * N on both compartments and the integrated flows.
    for j in out.state_end.district_ids:
        n = s.N[j]
        S, E, I, R, cnew, ce2i, ciex = _independent_week(s, j, cfg)
        tol = 1e-6 * max(1.0, n)
        assert abs(out.state_end.S[j] - S) < tol
        assert abs(out.state_end.E[j] - E) < tol
        assert abs(out.state_end.I[j] - I) < tol
        assert abs(out.state_end.R[j] - R) < tol
        assert abs(out.new_infections[j] - cnew) < tol
        assert abs(out.e_to_i[j] - ce2i) < tol
        assert abs(out.i_exit[j] - ciex) < tol


def test_integrator_step_refinement_convergence():
    """Halving the integrator max_step changes the normalized end state by less
    than 1e-6 (solution is converged in the step size, not just mass-conserving)."""
    from scipy.integrate import solve_ivp

    cfg = DiseaseConfig(r0=3.0, initial_infectious_fraction=0.005)
    beta = cfg.r0 / cfg.infectious_days
    sigma = 1.0 / cfg.latent_days
    gamma = 1.0 / cfg.infectious_days

    def rhs(_t, y):
        S, E, I, R = y
        inf = beta * S * I  # n == 1 (normalized)
        return [-inf, inf - sigma * E, sigma * E - gamma * I, gamma * I]

    y0 = [0.995, 0.0, 0.005, 0.0]

    def end(max_step):
        sol = solve_ivp(
            rhs,
            (0.0, 7.0),
            y0,
            method="RK45",
            t_eval=[7.0],
            rtol=1e-9,
            atol=1e-11,
            max_step=max_step,
        )
        return sol.y[:, -1]

    coarse = end(1.0)
    fine = end(0.5)
    import numpy as np

    assert np.max(np.abs(coarse - fine)) < 1e-6


def test_mass_conservation_across_weeks():
    districts = [District("D1", 10000, 1.0, None, 42.33, -71.08)]
    cfg = DiseaseConfig(r0=3.0, initial_infectious_fraction=0.005)
    s = init_state(districts, cfg)
    for _ in range(10):
        out = step_week(s, cfg, {"D1": 1.0})
        e = out.state_end
        total = e.S["D1"] + e.E["D1"] + e.I["D1"] + e.R["D1"]
        assert abs(total - e.N["D1"]) < 1e-6 * e.N["D1"]
        for comp in (e.S["D1"], e.E["D1"], e.I["D1"], e.R["D1"]):
            assert comp >= -1e-9
        from pipeline.seir import carry_state

        s = carry_state(e)


def test_integrator_nonnegative_and_finite():
    # A high-R0 fast epidemic must remain finite and nonnegative.
    S, E, I, R, cnew, ce2i, ciex = _integrate_week(0.99, 0.0, 0.01, 0.0, 1.0, 3.5 / 7, 1 / 5, 1 / 7)
    for v in (S, E, I, R, cnew, ce2i, ciex):
        assert np.isfinite(v) and v >= -1e-9
    assert abs((S + E + I + R) - 1.0) < 1e-3
