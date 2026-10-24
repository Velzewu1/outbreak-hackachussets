# Design: epidemic hospital dependency MVP

> **Reconciliation notice (authoritative).** Superseded where it conflicts with
> `architecture.md`, `docs/mathematical-model.md`, `docs/weekly-state-machine.md`,
> and `contracts/`. The SEIR+H wording here is replaced by the need-state model
> (`S+E+I+R=N`, `H_need` auxiliary); allocation/rerouting operate on new-admission
> requests only with persistent retained cohorts and row-preserving residuals;
> there are exactly two bounded FDNA passes with the zero-move ⇒ identical
> before/after invariant. The implementation gate is **CLOSED**.

## Architecture

Implement a functional pipeline with explicit data contracts and validation at every boundary:

```text
raw sources
  -> data.load_raw / data.validate_raw / data.save_clean
  -> separate.make_districts / separate.make_hospitals
  -> il1.prepare_seir_input
  -> seir.run_week
  -> il2.compute_accessibility / allocate_patients / build_graph
  -> fdna.solve
  -> analysis.reroute / compare_injection
  -> il3.package_week / next_state
  -> Streamlit presentation + validation reports
```

The scientific modules must not import Streamlit. Configuration is loaded once, validated, and passed explicitly.

## Data and types

Use typed dataclasses or similarly lightweight validated models for configuration and result containers. Use DataFrames and GeoDataFrames for tabular/geospatial collections, with schema-check functions at module boundaries. IDs are stable strings. Coordinates are transformed to a suitable projected CRS before distance calculations, while display geometry remains WGS84.

## SEIR+H

Start with independent district models. Integrate over seven days using a deterministic solver. Make rates and hospitalization behavior explicit, document units, preserve totals, and expose diagnostics. Keep a later mobility-coupled model behind the same `run_week` contract.

## Accessibility and flows

Compute projected straight-line distance from district centroids to hospitals. Keep the configured nearest hospitals within the radius, calculate accessibility, normalize shares, and allocate district admissions. Handle empty candidate sets explicitly. Use the same shares for patient flow and district dependency construction.

## Hospital score

Define a transparent, monotone mapping from load/capacity to 0–100 operability in configuration and tests. Do not hide smoothing or clipping. Capacity modifications are applied before load scores and recorded in scenario metadata.

## FDNA solver

Implement the documented strength and criticality terms as a pure update function. Because hospital links can be cyclic, iterate synchronously from known hospital input scores until the maximum absolute change is below tolerance or the iteration cap is reached. Return convergence status, iterations, and residual. Verify formulas against a primary source before representing the implementation as canonical FDNA.

## Rerouting

Use deterministic partial transfers: rank eligible destinations by a documented rule, move no more than destination spare capacity, update flows and loads, and repeat until stable. Preserve total demand. Keep unmet demand separate from epidemic transmission.

## Validation

Split calibration and evaluation by time. Compare the model's one-week-ahead occupancy forecast with a naive baseline on identical held-out rows. Report the same metric for both, sample size, date range, missing-data policy, and matching coverage.

## Testing

- Unit tests for every formula and boundary validator.
- Property tests or parameterized cases for conservation, bounds, monotonicity, share sums, rerouting capacity, and solver termination.
- Integration test for one small synthetic week using clearly labeled synthetic fixtures.
- Offline smoke test for the Streamlit entry point.
