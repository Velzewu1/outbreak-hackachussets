# Requirements: epidemic hospital dependency MVP

> **Reconciliation notice (authoritative).** This legacy spec predates the
> architecture reconciliation driven by `Addiotional Info 1.txt`. The
> authoritative specification is now `architecture.md`,
> `docs/mathematical-model.md`, `docs/weekly-state-machine.md`, `contracts/`,
> `docs/integration-plan.md`, `docs/architecture-decisions.md`, and `AGENTS.md`.
> Where this spec conflicts, those documents win. Key overrides: SEIR conserves
> `S+E+I+R=N` (no `H` compartment; `H_need` is auxiliary need, not beds);
> allocation/rerouting act on **new-admission requests only** with persistent
> retained cohorts; the ledger is `accepted + unmet = need` per origin district
> (not `served + rerouted + unmet = demand`); exactly two bounded FDNA passes with
> no feedback; the implementation approval gate is **CLOSED** (documentation
> only). Requirement 3 below ("S, E, I, R, H") is superseded by the need-state
> model.

## 1. Reproducible project setup

WHEN a developer follows the repository setup instructions
THE SYSTEM SHALL create a Python 3.12 environment with pinned dependencies and runnable quality commands.

WHEN the application runs without network access
THE SYSTEM SHALL use local, validated data snapshots rather than require live APIs.

## 2. Data acquisition and separation

WHEN raw district, hospital, and validation datasets are loaded
THE SYSTEM SHALL validate required columns, row counts, identifiers, coordinate reference systems, units, and missing values.

WHEN hospital location and bed datasets use different names
THE SYSTEM SHALL join them through a reviewable mapping table and report unmatched records.

WHEN validated data is separated
THE SYSTEM SHALL produce district and hospital tables conforming to the documented contracts.

## 3. Weekly epidemic simulation

WHEN a valid district state and disease configuration are provided
THE SYSTEM SHALL run a one-week SEIR step conserving `S+E+I+R=N` and return the
end state plus the auxiliary new-admission need `H_need` (people/week, not beds),
`i_exit`, and `e_to_i` per district. (Superseding the earlier "S, E, I, R, H"
wording; see `contracts/pipeline-types.md`.)

WHEN simulation output is produced
THE SYSTEM SHALL preserve population within tolerance and reject nonfinite or negative compartment values.

## 4. Patient allocation and hospital load

WHEN district admissions and hospital coordinates are available
THE SYSTEM SHALL compute eligible hospitals, normalized distance-based shares, patient flows, capacity utilization, and hospital operability scores.

WHEN no hospital is eligible for a district under the configured radius
THE SYSTEM SHALL report unmet demand or apply an explicitly configured fallback rather than discard patients.

## 5. Dependency propagation

WHEN the network is built
THE SYSTEM SHALL create directed hospital-to-district dependencies and configured symmetric hospital-to-hospital dependencies with bounded strength and criticality values.

WHEN hospital cycles exist
THE SYSTEM SHALL use a documented fixed-point iteration with convergence tolerance and iteration cap, and SHALL report non-convergence.

## 6. Rerouting and scenario injections

WHEN a hospital is over capacity
THE SYSTEM SHALL reroute patients only to eligible hospitals with available capacity, preserve patient totals, and report remaining unmet demand.

WHEN a user injects a closure, capacity change, or network change
THE SYSTEM SHALL preserve the baseline scenario and report before/after hospital and district outcomes.

## 7. Results and validation

WHEN a run completes
THE SYSTEM SHALL present hospital load, district access, reroutes, unmet demand, assumptions, checks, and scenario deltas through a Streamlit interface.

WHEN historical occupancy is available
THE SYSTEM SHALL evaluate next-week predictions on held-out weeks and compare the selected metric with a simple baseline.

## 8. Transparency and ethics

WHEN any modeled value is shown
THE SYSTEM SHALL distinguish observed, derived, fitted, and assumed values.

WHEN results are displayed or exported
THE SYSTEM SHALL state the model's geographic, access, fairness, data, and decision-use limitations.
