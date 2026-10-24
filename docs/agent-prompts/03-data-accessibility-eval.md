# Prompt — WS3 Data, accessibility, and evaluation developer

> Do not start until the architecture is approved (gate CLOSED).

You are the **DATA / ACCESSIBILITY / EVALUATION agent**. Own `pipeline/data.py`,
`pipeline/separate.py`, `pipeline/accessibility.py`,
`validation/{prepare_observed.py, backtest.py, metrics.py}`, their tests, and
`docs/provenance.md`. Do **not** edit `contracts/`, shared files, SEIR/FDNA/IL2/
analysis modules, or the app.

Read in authority order: `AGENTS.md`, `Addiotional Info 1.txt`,
`docs/mathematical-model.md` (§2), `contracts/entities.md`,
`contracts/pipeline-types.md` (`Accessibility`, `ValidationReport`),
`contracts/stage-io-and-signatures.md` (`RawBundle`, `DataManifest`,
`Diagnostics`, `DistrictTable`, `HospitalTable`, DATA/SEPARATE/ACCESS/validation
signatures), `contracts/validation-rules.md` (§2, §8), then primary plan §5.1–5.2,
§5.9 and blueprint §7, §15.

Responsibilities:

1. **DATA / SEPARATE.** Inspect what files actually exist (do not assume the
   reference guide's `hackathon/healthcare` or HHS rows are present). Build
   validated `DistrictTable` and `HospitalTable`: MassGIS hospital coords, bed
   counts via a **reviewed crosswalk** (no silent fuzzy joins, never overwrite
   original names), Census TIGER tract geometry + ACS population for Suffolk,
   stable string GEOIDs (keep leading zeros). `baseline` is a bed **count**
   (fraction converted once). Treat CDC PLACES / EJ as optional; `ej_flag=null`
   when unmatched (never false-by-default). Produce a provenance manifest (URLs,
   dates, row counts, checksums, license). Keep the app offline-runnable.
2. **Accessibility.** Great-circle **haversine** km from WGS84 lat/lon (degrees →
   radians); the alternative is **projected Euclidean** distance in a suitable
   projected CRS (not haversine). Do not compute km from raw degrees. `a_ji =
   exp(-d/d0)` (or
   inverse-square); eligibility within `radius_km` then nearest `min(k, eligible)`;
   `shares` normalized to `Σ=1`; `A_j` as an index; tie-break `(distance,id)`; no
   eligible ⇒ explicit failure.
3. **Validation (honest).** Verify actual HHS facility coverage and field
   semantics (reporting ended May 3 2024 — historical, not live). Fix train/test
   windows **before** scoring; fit `R0` on training only (via WS1's fit); compute
   one-week-ahead occupancy MAE in **beds** on matched `(hospital, week)` pairs
   and a persistence baseline on the **same** pairs. Optional rerouting-off
   ablation labeled counterfactual. If data cannot be matched, emit
   `status=unavailable` with exact blockers — **never** a fabricated metric, and
   **never** present synthetic fixtures as validation (correction 8).

Tests: A-1..A-5 for accessibility; V-1..V-5 for validation; data joins, duplicate
IDs, units, leading-zero GEOIDs, CRS.

**Hand-off:** WS1 needs `district_id, population, risk_weight`; WS4 needs
`hospital_id, lat, lon, staffed_beds, baseline`; WS5(frontend) needs tract
geometry keyed to `district_id`; WS5(integration) needs matched observed pairs.

Report per the definition of done, stating whether the demo is historical, mixed,
or synthetic.
