# Canonical interface contracts

**Specifications, not runnable schemas.** This directory is the single source of
truth for every cross-module object. Each type has exactly one definition, with
explicit units, invariants, serialization conventions, an owning workstream, a
worked example, and validation rules. (Correction 10.)

**Status (2026-10-24): gate OPEN.** These specs are now implemented in
`pipeline/contracts.py`, `pipeline/types.py`, and `pipeline/*`. The implementation
matches these specs; the per-file "gate CLOSED" notes are historical.

Files:

- `entities.md` — static inputs: `District`, `Hospital`, `DiseaseConfig`,
  `NetworkConfig`, the **discriminated** `Injection` (kind/payload), and config
  units.
- `pipeline-types.md` — per-week flow types: `SEIRState`, `SEIRWeekOutput`
  (incl. `i_exit`, `e_to_i`), `Accessibility`, `RequestRow`/`RequestTable`,
  `HospitalLoad`, `HospitalState`, `FDNAGraph` (dependency edges only),
  `FDNAResult`, `RerouteRecord`/`RerouteResult`, `WeekResult`, `RunResult`,
  `ValidationReport`, `WeekView`.
- `stage-io-and-signatures.md` — the remaining cross-module types defined once
  (`RawBundle`, `DataManifest`, `DataDiagnostics`/`Diagnostics`, `DistrictTable`,
  `HospitalTable`, `ValidatedInputs`/`DataBundle`, `ScenarioInputs`,
  `AllocationSnapshot`, `WeekSnapshot`, `WeekSummary`, `RunConfig`,
  `HospitalStateMap`, `ComparisonResult`/`DatasetSummary`), plus exact stage and
  public-API signatures and the boundary-vs-interval index conventions.
  `WeekView` and its subtypes are defined **only** in `pipeline-types.md`
  (referenced, not redefined, elsewhere).
- `validation-rules.md` — invariants, conservation equations, and the
  pass/fail checks each type must satisfy.

Every referenced type is defined exactly once across these files. `RunConfig`
carries the random seed, horizon, and the fixed baseline-stock policy.

Conventions (apply to all types):

- **IDs** are stable **strings** (`district_id`, `hospital_id`); GEOIDs keep
  leading zeros. Arrays are ordered by stable sorted IDs; serialized outputs carry
  named IDs, never rely on row order.
- **Units** are explicit and never mixed. Bed counts are people/beds; scores are
  0–100; `H_need`/`unmet` are people/week (**never** occupied beds); shares are
  fractions summing to 1.
- **Serialization**: JSON/CSV with named columns; floats stay numeric (no display
  rounding in files); UTF-8. Nullable real-observation fields are `null`, never
  zero-filled.
- **Tuple-keyed maps** (e.g. `accepted[(district_id, hospital_id)]`,
  `residual_rows`, `shares_override`) cannot use tuple JSON keys. They serialize as
  a **sorted array of records**, each an explicit object
  `{"district_id": "...", "hospital_id": "...", "value": <number>}`, sorted by
  `(district_id, hospital_id)`. (A single uniquely specified equivalent is allowed
  if documented on the type, but the record-array form above is the default and the
  one used by exports.) Single-keyed maps (e.g. `unmet_by_district`) serialize as
  `[{"district_id": "...", "value": <number>}, …]` sorted by id.
- **Numbers**: finite only. `NaN`, `Infinity`, and `-Infinity` are **rejected** on
  both read and write (they are not valid JSON and would corrupt conservation
  checks); a non-finite value is a validation error, never silently serialized.
- **Immutability**: `WeekResult`/`RunResult`/snapshots are immutable once
  produced; `HospitalState` is the only controlled-mutable object.
- **Numbers** in examples are **SYNTHETIC / ILLUSTRATIVE** and come from the one
  frozen example in `docs/end-to-end-walkthrough.md`.
