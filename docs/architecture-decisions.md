# Architecture decisions

Two sections: **(A) applied corrections** — mandatory, already reflected in all
docs and contracts; and **(B) PROPOSED decisions** — choices beyond the explicit
corrections.

> **APPROVAL GATE: OPEN (2026-10-24).** The user authorized full implementation and
> approved the reconciled architecture and the default proposals below:
> **need-state SEIR** (ADR-SEIR-3 default), **risk_weight on hospitalization**
> (ADR-SEIR-1), **weekly cohort LOS** (ADR-SEIR-2), **deterministic allocation
> priority** (ADR-ACCT-3), and **requested-load FDNA** (ADR-ACCT-2), plus
> ADR-FDNA-1, ADR-ACCT-1, ADR-GRAPH-1, ADR-CFG-1, ADR-VAL-1. These are now
> **APPROVED** and implemented. No commit/push/deploy is authorized.

Authority: `Addiotional Info 1.txt` > primary plan > reconciled docs > blueprint >
reference. See `AGENTS.md`.

---

## A. Applied corrections (binding, from `Addiotional Info 1.txt`)

| # | Correction | Where applied |
|---|---|---|
| C1 | Separate incident infections, new admissions, existing occupancy, discharges, unmet; reroute **new admissions only**; never re-allocate inpatients | math §1,§3,§5; state machine §1–2; walkthrough |
| C2 | Exact weekly timing of interventions, discharges, demand, provisional/ final admissions, FDNA recording; persistent `HospitalState` + immutable snapshots | state machine §2; math §3 |
| C3 | Exactly two bounded FDNA passes; no provisional-assignment commit; no unbounded feedback | math §4.4; state machine STEP 6/8 |
| C4 | Separate accessibility, patient-flow, FDNA dependency edges; proximity ≠ dependence; symmetry is a configurable assumption | math §6; architecture §5 |
| C5 | Global competition; preserve origin IDs; `new_admissions = accepted + unmet`; redirected ⊆ accepted | math §5; walkthrough §1.5–1.7 |
| C6 | Define `H` placement and adapt conservation: **need-state** `S+E+I+R=N`, `H_need` auxiliary | math §1.1 (ADR-SEIR-3) |
| C7 | Scenario isolation (identical init + seed); closure does not erase inpatients | state machine §5; math §3.5 |
| C8 | Synthetic ≠ external validation; historical backtest optional, only after real computation | architecture §7; audit |
| C9 | Keep weekly nine-block Python/Streamlit scope; no daily/ICU/React/FastAPI/LLM | architecture §1,§8 |
| C10 | One canonical definition per cross-module object, with units, invariants, serialization, owner | `contracts/` |

### A.1 Blocking-review corrections (applied)

| Item | Resolution |
|---|---|
| Census-based `flow=s·H` rerouting | **Discarded**. Replaced by new-admission requests only. |
| Unmet reattributed to "primary" hospital | **Removed**. Residuals preserved on original `(district, intended_hospital)` rows. |
| Zero moves changed scores | Fixed: `post_request = request` on zero moves ⇒ identical before/after (verified week 2). |
| `RerouteRecord` fields | Now `(week, district, source_hospital, destination, amount)`. |
| Unqualified `committed ≤ Ceff` | Generalized to `committed ≤ max(Ceff, baseline+retained)`; `inherited_deficit = max(0, baseline+retained−Ceff)` for reductions and closures. |
| Missing numeric SEIR states / event counts | Added for both weeks with `S+E+I+R=N` and `I`-exit / new-infection counts. |
| False ODE-verification claim | Walkthrough SEIR values labeled a hand-chosen fixture; no ODE claim. |
| Demand provenance | `H_need = p_H · rw · I_exit`. |
| Both discharges and retained in one example | Week 1 has nonzero discharges **and** retained (seeded week-0 cohorts with mixed LOS). |

---

## B. PROPOSED decisions (approval gate CLOSED)

Each needs an explicit human decision. Approving the architecture means approving
these (or replacing them). Until then, treat each as tentative.

### ADR-SEIR-1 — `risk_weight` scales hospitalization, not transmission
**Context.** Primary plan shorthand: "split infections by population × risk_weight".
`risk_weight` is defined as hospitalization susceptibility.
**Proposal.** Apply `risk_weight` to `p_H_j`, not to the infection rate; all
districts share one normalized `S/E/I/R` curve.
**Why.** Avoids violating local mass conservation and conflating severity with
transmission.
**Alternatives.** Infection-risk-weighted allocation with an explicit
population-conserving scheme (deferred).
**Status.** PROPOSED. **Decision:** ______  **Approver:** ______  **Date:** ______

### ADR-SEIR-3 — need-state vs explicit `H` compartment
**Context.** Correction 6 requires deciding whether `H` is a mutually exclusive
compartment or auxiliary.
**Proposal (default).** Need-state: `S+E+I+R=N`; `H_need = p_H·(I-exit)` is an
auxiliary demand signal; actual occupancy comes only from accepted cohorts.
**Alternative.** Explicit `H` compartment (admitted people removed from community
mixing), with `S+E+I+R+H=N`. Mathematically coherent but double-tracks occupancy
against `HospitalState`.
**Decision required:** choose exactly one. The contracts are written to the
need-state default; switching to explicit `H` changes `SEIRWeekOutput`.
**Status.** PROPOSED. **Decision:** ______  **Approver:** ______  **Date:** ______

### ADR-SEIR-2 — LOS discretization and cohort schedule
**Proposal.** Weekly cohorts with integer `remaining_los` decremented once per
week; discharge when it reaches 0; default `LOS = 2 weeks` in the example
(config `los_days` maps to weeks via `ceil(los_days/7)` — itself PROPOSED).
**Open.** Whether LOS is deterministic per cohort or a distribution.
**Status.** PROPOSED. **Decision:** ______

### ADR-FDNA-1 — "FDNA-based" adaptation
**Proposal.** Label the method "FDNA-based", not classical FDNA: own-score cap
`min(O_i, …)`, symmetric hospital cycle solved by synchronous fixed point,
share-weighted district SOD/COD. Convergence tol 0.1, max 500 iters,
non-convergence is an error.
**Status.** PROPOSED. **Decision:** ______

### ADR-ACCT-1 — new-admission reroute + persistent cohorts
**Proposal.** Reroute new admissions only; persistent cohorts carry
`(origin_district_id, admit_week, remaining_los, count)`; scheduled discharges
fire before demand; occupants survive closure (inherited deficit).
**Status.** PROPOSED (encodes corrections 1,2,5,7). **Decision:** ______

### ADR-ACCT-2 — operability on requested load; committed tracked separately
**Proposal.** Own/FDNA scores use `requested_load` (need view); `committed`
(physical beds) is tracked separately and never feeds back to beds. Residuals are
row-preserving; zero moves ⇒ identical before/after.
**Status.** PROPOSED. **Decision:** ______

### ADR-ACCT-3 — direct-reservation and reroute ordering
**Proposal.** Direct reservation order: districts by ascending id, candidates by
descending share then `(distance,id)`. Reroute order: residual rows by descending
residual then `(district,source)`. Deterministic and tie-stable.
**Open.** Whether to prefer an equity-weighted order (e.g. EJ districts first) —
**not** adopted in MVP; would change results and must be a labeled scenario.
**Status.** PROPOSED. **Decision:** ______

### ADR-GRAPH-1 — dependency edge ≠ routing-eligibility edge
**Proposal.** `add_edge`/`set_edge`/`remove_edge` change **FDNA dependency** only.
A patient transfer route is a separate, explicitly typed
`add_route_option(district,hospital)` / `allow_transfer(src,dst)` operation. If the
UI promises a transfer agreement, that typed op must exist and be tested; otherwise
the control is hidden and listed as future work.
**Status.** PROPOSED. **Decision:** ______

### ADR-CFG-1 — units and conversions
**Proposal.** `baseline` stored as a bed **count**; fallback fraction converted
once `baseline = f·C`. `capacity_factor` applied from base config each week (no
compounding). Injection weeks start-inclusive, end-exclusive.
**Status.** PROPOSED. **Decision:** ______

### ADR-VAL-1 — validation honesty
**Proposal.** Report MAE vs persistence only after a real matched HHS holdout is
computed; synthetic fixtures are never shown as validation; rerouting-off is a
labeled counterfactual ablation, not proof.
**Status.** PROPOSED (encodes correction 8). **Decision:** ______

---

## C. Unresolved / needs-data decisions (cannot close in documentation)

| ID | Question | Blocker |
|---|---|---|
| U1 | Which historical wave / HHS facility rows for the backtest? | requires actual HHS download + crosswalk; see audit |
| U2 | Fitted `R0` (and whether `p_H` is identifiable)? | requires real training data |
| U3 | Real Suffolk tract geometry/population + MassGIS hospital beds | requires data acquisition (WS3) |
| U4 | EJ flag join method (block group → tract) | requires EJ shapefile |
| U5 | `weeks` horizon and `start_date` | depends on real data availability |

These remain open by necessity; the architecture can be approved with them flagged,
but no validation metric may be claimed until U1/U2 are actually computed.
