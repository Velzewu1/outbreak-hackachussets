---
inclusion: always
---

# Modeling and evidence guardrails

> **Reconciliation notice (authoritative).** The authoritative modeling spec is
> the reconciled set driven by `Addiotional Info 1.txt`: `architecture.md`,
> `docs/mathematical-model.md`, `docs/weekly-state-machine.md`, `contracts/`,
> `docs/architecture-decisions.md`, and `AGENTS.md`. Where this older steering
> conflicts, those documents win. In particular the withdrawn items below are
> superseded.

## Fixed contracts

The canonical typed contracts are defined **once** in `contracts/`
(`entities.md`, `pipeline-types.md`, `stage-io-and-signatures.md`). Do not
redefine them here or in `docs/project-brief.md`.

> **Withdrawn:** the old `SEIRState { S,E,I,R,H }` and `Flow { district_id,
> hospital_id, share, patients }` (standing-census) contracts are replaced by the
> need-state `SEIRState { S,E,I,R }` + `SEIRWeekOutput { H_need, i_exit, e_to_i }`
> and `RequestRow` (new-admission requests). `Injection` is a discriminated
> union by `kind`.

## Required invariants (authoritative summary; full set in `contracts/validation-rules.md`)

- SEIR conserves `S + E + I + R = N` within `mass_tol` (1e-6); `H` is **not** a
  compartment; `H_need` is auxiliary people/week need, **never** occupied beds.
- Allocation and rerouting act on **new-admission requests only**; existing
  inpatients are persistent retained cohorts and are never re-allocated.
- `accepted_j + unmet_j = H_need_j` per origin district; `accepted_new_i ≤
  max(0, Ceff_i − baseline_i − retained_i)`; `committed_i ≤ max(Ceff_i,
  baseline_i + retained_i)` (an inherited deficit may exceed `Ceff`).
- A district's kept hospital allocation shares sum to 1 when at least one hospital
  is eligible.
- Scores stay within 0–100, strengths within 0–1, criticalities within 0–100.
- Rerouting never exceeds a destination's `free_new`, never creates patients, and
  terminates deterministically; **zero reroutes ⇒ identical before/after** loads
  and scores.
- Existing occupants survive a closure/reduction (inherited deficit); cohort
  records are never deleted.
- Unknown, missing, or unmatched source data produces a visible validation
  failure or warning; it is never silently filled with invented observations.
- Every assumption has a named config field, documented units, source or
  `assumption` label, and a sensitivity-ready default.

## Model defaults

- Districts: Suffolk County census tracts.
- Accessibility: `exp(-distance_km / d0_km)` with `d0_km = 3`.
- Keep the five nearest hospitals within a 10 km radius.
- District dependence strength: 0.9.
- Hospital-to-hospital radius: 5 km, symmetric strength 0.1, criticality 100.
- Start with the independent district SEIR need model (Option A); add
  cross-district coupling only after validation.
- Handle cyclic hospital dependencies with a documented synchronous fixed-point
  solver (convergence tolerance 0.1, cap 500 iterations, non-convergence is an
  error).

## Evidence and communication

- Verify the FDNA equations against a primary source before using them in a slide or claiming canonical FDNA behavior.
- Report the forecast metric and the simple baseline on the same held-out period.
- Distinguish observed data, derived data, fitted parameters, and assumptions in code and UI labels.
- State that straight-line distance omits travel time, insurance, language access, hospital systems, and transport barriers.
