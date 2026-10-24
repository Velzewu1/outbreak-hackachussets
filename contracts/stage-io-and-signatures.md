# Contracts — stage I/O types and exact signatures

Defines, **once**, every cross-module type referenced elsewhere that was not yet
specified, plus the exact stage and public-API signatures. Specifications only;
gate CLOSED. Conventions from `contracts/README.md` apply (string IDs, explicit
units, immutability, nullable-not-zero). All example numbers are **SYNTHETIC**.

---

## 1. Ingestion and separation types

### RawBundle  (owner WS3; produced by DATA)
Raw, pre-validation inputs grouped together. Opaque to downstream stages.

| Field | Type | Notes |
|---|---|---|
| `tables` | map[string → table] | raw source tables keyed by source name |
| `files` | map[string → path] | geometry/shapefile paths |
| `manifest` | `DataManifest` | provenance (see below) |

### DataManifest  (owner WS3)
| Field | Type | Notes |
|---|---|---|
| `sources` | list of `{name, url, publisher, coverage, downloaded_at, license, sha256, row_count, status}` | `status ∈ {confirmed, awaiting, missing}` |
| `data_mode` | enum | `historical_data` \| `mixed_assumptions` \| `synthetic_demo` |
| `warnings` | list[string] | one caveat per source minimum |

### DataDiagnostics (a.k.a. Diagnostics)  (owner WS3; emitted by every DATA/SEPARATE/check step)
One shared diagnostics type for all validation/check functions.

| Field | Type | Notes |
|---|---|---|
| `ok` | bool | overall pass/fail |
| `errors` | list of `{code, message, offending_ids}` | fatal issues (fail the stage) |
| `warnings` | list of `{code, message, offending_ids}` | non-fatal |
| `counts` | map[string → int] | e.g. rows in/out, matched facilities |

`check_separation`, `check_il1`, `check_seir`, `check_il2`, `check_fdna`,
`check_il3` all return `DataDiagnostics` (aliased `Diagnostics`).

### DistrictTable  (owner WS3)
Ordered collection of `District` (see `entities.md`), as a validated table/
GeoDataFrame indexed by sorted `district_id`. Invariant: unique IDs; one row per
district; `population>0`; valid geometry/centroid.

### HospitalTable  (owner WS3)
Ordered collection of `Hospital`, validated, indexed by sorted `hospital_id`.
Invariant: unique IDs; valid coords; `staffed_beds>0`; `baseline` a bed count.

---

## 2. Validated inputs and scenario inputs

### ValidatedInputs (a.k.a. DataBundle)  (owner WS5; immutable for a run)
The frozen, validated bundle the runner/API consume. One object; two names refer
to the same type (`DataBundle` is the alias used in `simulate_run`).

| Field | Type | Notes |
|---|---|---|
| `config` | `RunConfig` | normalized, validated (see §4) |
| `districts` | `DistrictTable` | |
| `hospitals` | `HospitalTable` | |
| `accessibility` | `Accessibility` | precomputed once (PREP) |
| `observed` | observed table \| null | matched historical pairs, or null |
| `manifest` | `DataManifest` | |

Immutable: UI callbacks never mutate it. A parameter change builds a new
`ValidatedInputs` and a new run.

### ScenarioInputs  (owner WS4; per week, internal to IL2)
The post-injection inputs for one week, derived from `ValidatedInputs` +
active injections. Not persisted beyond the week.

| Field | Type | Notes |
|---|---|---|
| `week` | int | |
| `effective_capacity` | map[hospital_id → float] | after capacity/closure injections |
| `closed` | set[hospital_id] | hospitals with `Ceff=0` this week |
| `score_caps` | map[hospital_id → float] | after `set_score`/`reduce_score` |
| `shares_override` | map[(district_id,hospital_id) → float] | after `set_share`, renormalized to keep `Σ=1` |
| `effective_edges` | list[Edge] | the **resolved** FDNA dependency edge list for this week: the base edges with adds/sets applied and **removed edges omitted** (so `remove_edge` is representable) |
| `route_options` | list[(district_id,hospital_id)] | after `add_route_option` (if used) |
| `active_injections` | list[Injection] | sorted canonical order |

`effective_edges` is the fully resolved edge list (not a diff), so `add_edge`,
`set_edge`, and `remove_edge` are all expressible: an added/changed edge appears
with its weights; a removed edge is simply absent. The FDNA stage consumes
`effective_edges` directly.

---

## 3. Allocation snapshot, week snapshot, week summary

### AllocationSnapshot  (owner WS4; one per phase; immutable)
The typed, **phase-specific** allocation state. This is what makes before/after
comparable (the earlier "committed same both phases" was insufficient).

| Field | Type | Unit / semantics |
|---|---|---|
| `phase` | enum | `before` (provisional direct reservations) \| `after` (final, with redirects) |
| `accepted` | map[(district_id, hospital_id) → float] | accepted matrix; BEFORE = `direct` only; AFTER = `direct + incoming_rerouted` |
| `residual_rows` | map[(district_id, source_hospital_id) → float] | per-row residual still intended for the source; BEFORE = after direct reservation; AFTER = after redirects |
| `unmet_by_district` | map[district_id → float] | people/week = Σ residual rows for the district |
| `projected_occupancy` | map[hospital_id → float] | `baseline + retained + Σ accepted[_,h]` for the phase (physical beds) |
| `reroute_volume` | float | BEFORE = 0; AFTER = Σ `RerouteRecord.amount` |
| `reroutes` | list[`RerouteRecord`] | BEFORE = empty; AFTER = the moves |

**Phase semantics (CORRECTION, this review):**

- **BEFORE** = provisional **direct reservations** only: `accepted = direct`,
  `reroute_volume = 0`, `reroutes = []`, `unmet_by_district` = residual after
  direct reservation. **No commit happens at this phase.**
- **AFTER** = **redirects applied, final**: `accepted = direct + incoming
  rerouted`, `reroute_volume > 0` if any move, `unmet_by_district` = residual after
  redirects. **Only the AFTER phase commits** accepted admissions into
  `HospitalState` (see §6 `commit_week`).

`projected_occupancy` in each phase lets the UI compare provisional vs final
occupancy without mutating physical state before the AFTER commit.

**Verified example (frozen walkthrough, week 1 — SYNTHETIC):**
BEFORE `unmet_by_district = {D1:0, D2:56.790623715, D3:30.41636406}`, total unmet
`87.206987775`, `reroute_volume = 0`. AFTER `unmet_by_district = {D1:0,
D2:44.58363594, D3:30.41636406}`, total unmet `75.0`, `reroute_volume =
12.206987775` (one record `week 0, D2, H2→H1`).

### WeekSnapshot  (owner WS5; immutable; one for `before`, one for `after`)
The per-phase bundle inside a `WeekResult`.

| Field | Type | Notes |
|---|---|---|
| `phase` | enum | `before` \| `after` |
| `hospital_loads` | list[`HospitalLoad`] | requested-load view for the phase (`request_i` before, `post_request_i` after) |
| `fdna` | `FDNAResult` | hospital + district scores for the phase |
| `allocation` | `AllocationSnapshot` | phase-specific accepted/unmet/reroute (above) |

The **physical** end-of-week `HospitalState` is a **separate final state** (not a
phase field): it is the result of the AFTER commit and is stored once per week on
the `WeekResult` (`end_hospital_state`), not duplicated in each phase snapshot.

### WeekSummary  (owner WS4→WS5; derived headline numbers for a phase)
| Field | Type | Unit |
|---|---|---|
| `overloaded_hospitals` | int | count with `requested_load > Ceff` in the phase |
| `unmet_need_people` | float | Σ unmet need (people/week) |
| `rerouted_people` | float | `AllocationSnapshot.reroute_volume` |
| `inherited_deficit_beds` | float | Σ inherited deficit |
| `districts_below_threshold` | int | district score `< RunConfig.score_threshold` |
| `worst_hospitals`, `worst_districts` | list | sorted by a documented metric |

---

## 4. RunConfig  (owner WS5; normalized, immutable)

The single normalized configuration object. Wraps the entity configs and adds
run-level controls.

| Field | Type | Unit / constraint | Notes |
|---|---|---|---|
| `disease` | `DiseaseConfig` | | §entities |
| `network` | `NetworkConfig` | | §entities |
| `geography` | `{unit, region}` | `census_tract`, `Suffolk County, MA` | primary defaults |
| `weeks` (`horizon`) | int | `>= 1` | number of weekly iterations |
| `random_seed` | int | fixed | seeds any stochastic step; **identical across scenarios** (correction 7) |
| `baseline_stock_policy` | enum | `fixed_count` (default) \| `fraction_of_C` | how `baseline_i` is set |
| `baseline_fraction` | float | `[0,1]`; default `0.75` | used only when policy = `fraction_of_C`; converted once to a count |
| `los_weeks` | int (derived) | `ceil(disease.los_days / 7)` | **derived from `disease.los_days` only** — no second source; not a standalone config field (ADR-SEIR-2) |
| `score_threshold` | float | default `70` | district "below threshold" display cutoff |
| `tolerances` | `{mass_tol:1e-6, share_tol:1e-9, patient_tol:1e-6, move_epsilon:1e-9}` | | **single source**; the `checks.*` names in `docs/mathematical-model.md` §7 are aliases of these `RunConfig.tolerances.*` paths |
| `fdna` | `{convergence_tol_points:0.1, max_iterations:500}` | | |

**Fixed baseline-stock policy.** `baseline_i` is a bed **count**. With
`baseline_stock_policy = fraction_of_C`, it is computed **once** as
`round-free f·C_i` at build time and then treated as a constant stock for the run;
it is never recomputed per week and never mixed with a fraction thereafter. The
baseline stock is held constant across weeks unless a `set_capacity`/closure
injection changes `Ceff` (which affects capacity, not the baseline stock itself).

**Reproducibility.** `run_id = hash(normalized RunConfig + input checksums + algo
version)`. Baseline and intervention runs share the same `random_seed` and initial
state.

---

## 5. Index conventions: boundary vs interval

- **Weeks are zero-based interval indices.** `week = t` denotes the `t`-th weekly
  iteration (the interval `[t, t+1)`). `weeks = horizon` runs `t ∈ {0,…,horizon−1}`.
- **SEIR `state_end`** is the **boundary** value at the end of interval `t`, used
  as the start boundary of interval `t+1` (`carry_state`).
- **Weekly counts** (`i_exit`, `e_to_i`, `new_infections`, `H_need`) are integrals
  **over** interval `t` (interval-indexed), not boundary values.
- **Cohort `admit_week`** is the interval index `t` of admission; discharge occurs
  at the boundary where `remaining_los` reaches 0 (start of a later interval), so a
  `remaining_los = 1` cohort admitted in interval `t` is retained through interval
  `t` and discharged at the start of interval `t+1` — never on arrival.
- **`admit_week = -1`** is the permitted sentinel for **pre-simulation seeded
  cohorts** (admitted before interval 0).
- **`RerouteRecord.week`** is an **interval** index (the interval in which the move
  happens), whereas **`SEIRState.week`** is a **boundary** index. They are not
  interchangeable even though both are zero-based.
- **UI display** may label intervals as "Week 1", "Week 2" (one-based) for humans;
  the example walkthrough uses display weeks 1 and 2 for interval indices 0 and 1
  (so its "Week 1" reroute carries `RerouteRecord.week = 0`). The engine always
  uses zero-based indices.

---

## 6. Exact stage signatures

Signatures describe required interfaces (types from `contracts/`), not code. All
support types below are defined in §6.1 — there are no untyped parameters.

```
# DATA (WS3)
load_raw(manifest: DataManifest) -> RawBundle
validate_raw(raw: RawBundle) -> DataDiagnostics
save_clean(clean: CleanTables, destination: Path) -> DataManifest

# SEPARATE (WS3)
build_districts(raw: RawBundle, config: RunConfig) -> DistrictTable
build_hospitals(raw: RawBundle, crosswalk: HospitalCrosswalk, config: RunConfig) -> HospitalTable
check_separation(d: DistrictTable, h: HospitalTable, config: RunConfig) -> DataDiagnostics

# ACCESSIBILITY (WS3)
build_accessibility(d: DistrictTable, h: HospitalTable, net: NetworkConfig) -> Accessibility

# IL1 / SEIR (WS1)
init_state(d: DistrictTable, disease: DiseaseConfig) -> SEIRState
carry_state(prev: SEIRState) -> SEIRState
check_il1(s: SEIRState, d: DistrictTable) -> DataDiagnostics
step_week(s: SEIRState, disease: DiseaseConfig) -> SEIRWeekOutput
check_seir(o: SEIRWeekOutput, d: DistrictTable) -> DataDiagnostics

# HOSPITAL STATE (WS4) — persistent cohorts
discharge_due(state: HospitalStateMap, week: int) -> (state_out: HospitalStateMap,
    discharged: dict[hospital_id, float], retained: dict[hospital_id, float])
    # decrements remaining_los; removes cohorts hitting 0; returns survivors BEFORE commit
commit_week(state: HospitalStateMap, accepted: AllocationSnapshot, week: int,
    los_weeks: int) -> HospitalStateMap
    # AFTER phase only: appends accepted cohorts (origin_district_id, admit_week=week,
    # remaining_los=los_weeks, count); counts accepted exactly once

# IL2 (WS4)
apply_injections(base: ValidatedInputs, injections: list[Injection], week: int) -> ScenarioInputs
compute_requests(epi: SEIRWeekOutput, acc: Accessibility, scn: ScenarioInputs) -> RequestTable
compute_loads(requests: RequestTable, hospitals: HospitalTable,
    retained: dict[hospital_id, float], scn: ScenarioInputs, phase: str,
    allocation: AllocationSnapshot | None = None) -> list[HospitalLoad]
    # phase="before": allocation is None; uses request_i from the ORIGINAL requests.
    # phase="after":  allocation is REQUIRED (the AFTER AllocationSnapshot); uses
    #                 post_request_i = accepted_final_i + Σ_j residual[j,i], i.e. the
    #                 accepted/incoming-move data lives in `allocation`.
build_graph(hospitals: HospitalTable, acc: Accessibility, scn: ScenarioInputs) -> FDNAGraph
check_il2(requests: RequestTable, loads: list[HospitalLoad], acc: Accessibility) -> DataDiagnostics

# FDNA (WS2)
solve_hospitals(loads: list[HospitalLoad], graph: FDNAGraph, cfg: RunConfig) -> dict[hospital_id, float]
solve_districts(hospital_scores: dict[hospital_id, float], acc: Accessibility,
    net: NetworkConfig) -> dict[district_id, float]
solve(loads: list[HospitalLoad], graph: FDNAGraph, acc: Accessibility, cfg: RunConfig) -> FDNAResult
check_fdna(r: FDNAResult) -> DataDiagnostics

# ANALYSIS (WS4)
reserve_direct(requests: RequestTable, baseline: dict[hospital_id, float],
    retained: dict[hospital_id, float], scn: ScenarioInputs) -> AllocationSnapshot
    # phase="before"; reroute_volume=0
    # `baseline` is the per-hospital baseline occupied-bed stock (from HospitalTable
    #  via RunConfig.baseline_stock_policy); needed because free_new =
    #  max(0, Ceff - baseline - retained) and ScenarioInputs/retained alone omit it.
    #  Equivalent: pass hospitals: HospitalTable and read baseline from it.
reroute(before: AllocationSnapshot, acc: Accessibility, scn: ScenarioInputs) -> AllocationSnapshot
    # phase="after"; consumes residual rows into destinations with spare free_new
summarise(before: WeekSnapshot, after: WeekSnapshot) -> WeekSummary

# IL3 (WS5)
package_results(o: SEIRWeekOutput, before: WeekSnapshot, after: WeekSnapshot,
    end_state: HospitalStateMap, injections: list[Injection],
    diag: dict[str, DataDiagnostics]) -> WeekResult
next_state(o: SEIRWeekOutput) -> SEIRState
export_results(run: RunResult, format: str) -> bytes

# RUNNER (WS5)
simulate_run(config: RunConfig, data_bundle: ValidatedInputs,
    injection_list: list[Injection]) -> RunResult
```

### 6.1 Minimal support types / aliases

| Name | Definition |
|---|---|
| `Path` | filesystem path string |
| `CleanTables` | `{districts: DistrictTable, hospitals: HospitalTable, observed: ObservedTable \| null}` |
| `ObservedTable` | rows `{week_start, hospital_id, reported_occupied_beds, reported_staffed_beds}` |
| `HospitalCrosswalk` | rows `{source_name, hospital_id, canonical_name, match_method, review_status}` |
| `HospitalStateMap` | `map[hospital_id → HospitalState]` (see `pipeline-types.md`) |
| `FrozenValidationCfg` | `{target_variable, source_url, training_start, training_end, test_start, test_end, reporting_week_convention}` — fixed **before** scoring |
| `DatasetSummary` | `{name, data_mode, n_districts, n_hospitals, has_observed}` |
| `ComparisonResult` | `{weeks: list[{week, baseline: WeekView, scenario: WeekView, deltas: map[str,float]}], matched: bool}` |

`free_new` is not a public parameter: it is computed inside `reserve_direct` /
`reroute` as `max(0, Ceff_i − baseline_i − retained_i − accepted_so_far_i)` and
exposed only via `AllocationSnapshot.projected_occupancy`.

---

## 7. Exact public API signatures  (WS5; `pipeline/api.py`)

```
available_datasets() -> list[DatasetSummary]
load_inputs(mode: str, data_root: path, config_path: path) -> ValidatedInputs
run_scenario(inputs: ValidatedInputs, injections: list[Injection] = []) -> RunResult
compare_scenarios(inputs: ValidatedInputs, injections: list[Injection]) -> ComparisonResult
get_week(run: RunResult, week_index: int, phase: str = "after") -> WeekView
export_csv(run: RunResult, table_name: str) -> bytes
export_json(run: RunResult) -> bytes
validation_report(data_root: Path, frozen_validation_cfg: FrozenValidationCfg) -> ValidationReport | None
```

`ComparisonResult`, `DatasetSummary`, and `FrozenValidationCfg` are defined in
§6.1. `compare_scenarios` requires matched region/hospitals/districts/dates/base
settings; differences are attributable only to documented injections.

`run_scenario` returns both before/after per week from one canonical pipeline; the
UI never recomputes model math. Model calls take ordinary validated inputs, never
a `st.session_state` object, so every run is reproducible.

### 7.1 `run_id` must hash scenario + inputs, not config alone

```
run_id = hash(
    normalized RunConfig,
    ordered injection_list / ScenarioSpec,       # scenario identity
    initial SEIRState checksum,                  # seeded initial epidemic state
    initial HospitalStateMap checksum,           # seeded prior cohorts (change results)
    DistrictTable + HospitalTable checksums,     # data identity
    Accessibility checksum,
    algorithm_version
)
```

Hashing config alone would make two scenarios (baseline vs an intervention) with
the same base config **collide**. The ordered injection list / scenario spec and
the initial-state/data checksums are therefore part of the key. The initial
`HospitalStateMap` checksum is included because **seeded prior cohorts change
results** (different seeded occupancy ⇒ different free capacity ⇒ different
allocation). Injections and all maps are serialized in canonical sorted order so
the hash is stable.
