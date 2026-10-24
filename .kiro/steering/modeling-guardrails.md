---
inclusion: always
---

# Modeling and evidence guardrails

## Fixed contracts

Use explicit data models for `District`, `Hospital`, `DiseaseConfig`, `NetworkConfig`, `SEIRState`, `Flow`, `Edge`, `Injection`, `WeekResult`, and `RunResult`. Preserve the field definitions in `docs/project-brief.md` unless a reviewed spec change updates them.

## Required invariants

- SEIR+H compartment values remain finite, nonnegative, and population-conserving within documented tolerance.
- A district's kept hospital allocation shares sum to 1 when at least one hospital is eligible.
- Scores stay within 0–100, strengths within 0–1, and criticalities within 0–100.
- Rerouting never exceeds the destination's available capacity, never creates patients, and terminates deterministically.
- Unknown, missing, or unmatched source data produces a visible validation failure or warning; it must not be silently filled with invented observations.
- Every assumption has a named configuration field, documented units, source or `assumption` label, and a sensitivity-ready default.

## Model defaults

- Districts: Suffolk County census tracts.
- Accessibility: `exp(-distance_km / d0_km)` with `d0_km = 3`.
- Keep the five nearest hospitals within a 10 km radius.
- District dependence strength: 0.9.
- Hospital-to-hospital radius: 5 km, symmetric strength 0.1, criticality 100.
- Start with independent district SEIR+H models; add cross-district coupling only after validation.
- Handle cyclic hospital dependencies with a documented fixed-point solver, convergence tolerance, iteration cap, and non-convergence result.

## Evidence and communication

- Verify the FDNA equations against a primary source before using them in a slide or claiming canonical FDNA behavior.
- Report the forecast metric and the simple baseline on the same held-out period.
- Distinguish observed data, derived data, fitted parameters, and assumptions in code and UI labels.
- State that straight-line distance omits travel time, insurance, language access, hospital systems, and transport barriers.
