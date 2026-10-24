"""IL1 + SEIR need-state model (Option A, APPROVED defaults).

Mass balance S+E+I+R=N (H is NOT a compartment). ``h_need`` is an auxiliary
new-admission need signal = p_H_j * (people leaving I over the week). One shared
normalized epidemic curve; per-district counts = fraction * N_j; risk_weight
scales p_H (hospitalization), not transmission.

Integrated over 7 daily substeps with scipy.integrate.solve_ivp. Weekly outputs
(i_exit, e_to_i, new_infections) are integrated PEOPLE, not rates.
"""

from __future__ import annotations

from scipy.integrate import solve_ivp

from .contracts import DiseaseConfig
from .types import SEIRState, SEIRWeekOutput

DAYS_PER_WEEK = 7


def init_state(districts, disease: DiseaseConfig) -> SEIRState:
    """Week-0 boundary state. I = seed*N, S = N-I, E=R=0."""
    disease.validate()
    ids = tuple(sorted(d.district_id for d in districts))
    S, E, I, R, N = {}, {}, {}, {}, {}
    seed = disease.initial_infectious_fraction
    for d in districts:
        n = float(d.population)
        i0 = seed * n
        N[d.district_id] = n
        I[d.district_id] = i0
        S[d.district_id] = n - i0
        E[d.district_id] = 0.0
        R[d.district_id] = 0.0
    return SEIRState(week=0, district_ids=ids, S=S, E=E, I=I, R=R, N=N).validate()


def carry_state(prev: SEIRState) -> SEIRState:
    """Carry a boundary state forward unchanged (deep, immutable copy).

    ``prev`` is already the END boundary of an interval (week index set by
    ``step_week`` to interval+1). This preserves that boundary index; it does not
    increment again.
    """
    return SEIRState(
        week=prev.week,
        district_ids=prev.district_ids,
        S=dict(prev.S),
        E=dict(prev.E),
        I=dict(prev.I),
        R=dict(prev.R),
        N=dict(prev.N),
    )


def _integrate_week(s0, e0, i0, r0, n, beta, sigma, gamma):
    """Integrate one district's S,E,I,R plus cumulative flows over 7 days.

    y = [S, E, I, R, cum_newinf, cum_e_to_i, cum_i_exit]
    """

    def rhs(_t, y):
        S, E, I, R, _c1, _c2, _c3 = y
        infection = beta * S * I / n if n > 0 else 0.0
        e2i = sigma * E
        iex = gamma * I
        return [
            -infection,
            infection - e2i,
            e2i - iex,
            iex,
            infection,  # cumulative new infections
            e2i,  # cumulative E->I
            iex,  # cumulative I-exit
        ]

    y0 = [s0, e0, i0, r0, 0.0, 0.0, 0.0]
    sol = solve_ivp(
        rhs,
        (0.0, float(DAYS_PER_WEEK)),
        y0,
        method="RK45",
        t_eval=[float(DAYS_PER_WEEK)],
        rtol=1e-8,
        atol=1e-9,
        max_step=1.0,
    )
    if not sol.success:
        raise RuntimeError(f"SEIR integration failed: {sol.message}")
    S, E, I, R, cnew, ce2i, ciex = sol.y[:, -1]
    # Only tiny numerical noise may be clamped; a materially negative compartment
    # indicates a real problem and must NOT be hidden.
    noise = 1e-6 * max(1.0, n)
    vals = {
        "S": S,
        "E": E,
        "I": I,
        "R": R,
        "cum_new": cnew,
        "cum_e2i": ce2i,
        "cum_iexit": ciex,
    }
    for name, v in vals.items():
        if v < -noise:
            raise RuntimeError(
                f"SEIR produced a materially negative quantity {name}={v} "
                f"(noise tol {noise}); integration is unstable"
            )
    clamp = lambda v: v if v > 0 else 0.0
    return clamp(S), clamp(E), clamp(I), clamp(R), clamp(cnew), clamp(ce2i), clamp(ciex)


def step_week(
    state: SEIRState, disease: DiseaseConfig, risk_weight: dict[str, float]
) -> SEIRWeekOutput:
    """One week. Option A: all districts share the same normalized rates.

    risk_weight maps district_id -> rw (scales p_H only).
    """
    disease.validate()
    beta = disease.r0 / disease.infectious_days
    sigma = 1.0 / disease.latent_days
    gamma = 1.0 / disease.infectious_days

    S2, E2, I2, R2, N2 = {}, {}, {}, {}, {}
    i_exit, e_to_i, new_inf, h_need = {}, {}, {}, {}

    # Option A performance optimization: under Option A every district shares the
    # SAME normalized S/E/I/R trajectory (p_H affects only h_need, never the
    # compartments). So we integrate the normalized curve ONCE per unique initial
    # fraction vector and scale by each district's N. Numerically identical to the
    # per-district solve within tolerance (tested). Districts that share a
    # normalized initial state (the default seeded init) reuse one integration.
    cache: dict[tuple, tuple] = {}

    def _norm_key(j, n):
        if n <= 0:
            return None
        return (
            round(state.S[j] / n, 12),
            round(state.E[j] / n, 12),
            round(state.I[j] / n, 12),
            round(state.R[j] / n, 12),
        )

    for j in state.district_ids:
        n = state.N[j]
        key = _norm_key(j, n)
        if key is not None and key in cache:
            fS, fE, fI, fR, fnew, fe2i, fiex = cache[key]
        else:
            # integrate on a unit population (fractions), then store fractions
            s0, e0, i0, r0 = (state.S[j], state.E[j], state.I[j], state.R[j])
            uS, uE, uI, uR, ucnew, uce2i, uciex = _integrate_week(
                s0 / n, e0 / n, i0 / n, r0 / n, 1.0, beta, sigma, gamma
            )
            tot = uS + uE + uI + uR
            if tot > 0:
                if abs(tot - 1.0) > 1e-4:
                    raise RuntimeError(
                        f"SEIR normalized mass drift too large for {j}: {tot} vs 1.0"
                    )
                sc = 1.0 / tot
                uS, uE, uI, uR = uS * sc, uE * sc, uI * sc, uR * sc
            fS, fE, fI, fR = uS, uE, uI, uR
            fnew, fe2i, fiex = ucnew, uce2i, uciex
            if key is not None:
                cache[key] = (fS, fE, fI, fR, fnew, fe2i, fiex)
        S2[j], E2[j], I2[j], R2[j], N2[j] = fS * n, fE * n, fI * n, fR * n, n
        new_inf[j] = fnew * n
        e_to_i[j] = fe2i * n
        ciex = fiex * n
        i_exit[j] = ciex
        p_h_j = min(1.0, max(0.0, disease.p_h * risk_weight.get(j, 1.0)))
        h_need[j] = p_h_j * ciex

    interval = state.week  # interval index = the input boundary index
    end = SEIRState(
        week=interval + 1,  # END boundary index (start boundary of next interval)
        district_ids=state.district_ids,
        S=S2,
        E=E2,
        I=I2,
        R=R2,
        N=N2,
    ).validate()

    return SEIRWeekOutput(
        week=interval,  # INTERVAL index
        state_end=end,
        i_exit=i_exit,
        e_to_i=e_to_i,
        new_infections=new_inf,
        h_need=h_need,
    )
