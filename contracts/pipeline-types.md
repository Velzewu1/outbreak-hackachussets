# Contracts — pipeline types

Per-week flow types. Specifications only; gate CLOSED. Units never mixed; IDs are
stable strings; arrays ordered by sorted IDs. All example numbers are
**SYNTHETIC** and come from the frozen example in
`docs/end-to-end-walkthrough.md`.

---

## SEIRState  (owner WS1)

| Field | Type | Unit / constraint |
|---|---|---|
| `week` | int | **boundary** index (start/end of an interval), `>= 0`; distinct from interval indices used by `RerouteRecord.week`/`admit_week` |
| `district_ids` | list[string] | stable sorted |
| `S`,`E`,`I`,`R` | array[float] `[district]` | people; nonnegative; `S+E+I+R = N_j` |

`H` is **not** a compartment here (ADR-SEIR-3 need-state). Example D2 week-1 end:
`S=16800, E=1000, I=1000, R=1200` (Σ=20000).

---

## SEIRWeekOutput  (owner WS1)

| Field | Type | Unit / constraint |
|---|---|---|
| `week` | int | boundary/interval index, zero-based (see below) |
| `state_end` | SEIRState | `S+E+I+R=N` |
| `i_exit` | array[float] `[district]` | **people** leaving `I` during the week (`∫ γ·I`) |
| `e_to_i` | array[float] `[district]` | **people** moving `E→I` during the week (`∫ σ·E`) |
| `new_infections` | array[float] `[district]` | **people** `S→E` during the week (`∫ β·S·I/N`) |
| `H_need` | array[float] `[district]` | **people/week** new-admission need; **NOT beds** |

All weekly quantities are **integrated people counts over the week** (counts, not
instantaneous rates). They are never added to a bed stock as a rate.
`H_need_j = p_H_j · i_exit_j`. Example week 1 (SYNTHETIC):
`i_exit = {D1:500, D2:1000, D3:750}`, `e_to_i = {D1:500, D2:1000, D3:750}`,
`new_infections = {D1:600, D2:1200, D3:900}`, `H_need = {D1:40, D2:120, D3:48}`
(with `p_H = 0.08 · rw_j`).

---

## Accessibility  (owner WS3; immutable for the run)

| Field | Type | Unit / constraint |
|---|---|---|
| `district_ids`,`hospital_ids` | list[string] | sorted |
| `distance_km` | array `[district,hospital]` | km; haversine |
| `eligible` | array[bool] `[district,hospital]` | within radius & nearest-k |
| `a` | array `[district,hospital]` | kernel; 0 if not eligible |
| `shares` (`s_ji`) | array `[district,hospital]` | fraction; `Σ_i s_ji = 1` |
| `total_accessibility` (`A_j`) | array `[district]` | index (not a %); `Σ_i a_ji` |

Example D1: `s = {H1:0.696, H2:0.256, H3:0.048}`, `A=1.030`.

---

## RequestRow / RequestTable  (owner WS4)

A **row** per `(district, intended hospital)`; residuals are preserved per row.

| Field | Type | Unit / constraint |
|---|---|---|
| `district_id` | string | origin (preserved through reroute) |
| `hospital_id` | string | intended (source) hospital |
| `requested` | float | `s_ji · H_need_j` (people/week) |
| `direct_accepted` | float | reserved directly, `<= free_new` |
| `rerouted_out` | float | moved to another hospital by reroute |
| `residual` | float | `requested - direct_accepted - rerouted_out` (stays on this row) |

Invariant per row: `requested = direct_accepted + rerouted_out + residual`.
Example week 1 `D2→H2`: `requested=73.553, direct=16.762, rerouted_out=12.207,
residual=44.584`.

---

## HospitalLoad  (owner WS4; requested-load / need view)

| Field | Type | Unit / constraint |
|---|---|---|
| `hospital_id` | string | |
| `baseline` | float | bed count |
| `retained` | float | bed count (surviving cohorts this week) |
| `request_i` | float | Σ requested rows to `i` (before) |
| `post_request_i` | float | `accepted_final_i + Σ_j residual[j,i]` (after) |
| `requested_load` | float | `baseline + retained + request_i` (or `post_request_i`) |
| `effective_capacity` (`Ceff`) | float | beds; closure ⇒ 0 |
| `own_score` | float | `100·min(1, Ceff/requested_load)`; closed ⇒ 0; 0–100 |
| `excess` | float | `max(0, requested_load − Ceff)` |

Example H2 week 1 before: `requested_load=173.637, own=63.351`.

---

## HospitalState  (owner WS4; persistent, controlled-mutable)

`HospitalState` is **per hospital**. The whole-network state is
`HospitalStateMap = map[hospital_id → HospitalState]` (the alias used by the
runner, `commit_week`, and `WeekResult.end_hospital_state`).

| Field | Type | Unit / constraint |
|---|---|---|
| `hospital_id` | string | |
| `baseline` | float | bed count (immovable) |
| `cohorts` | list of cohort | epidemic occupants |
| cohort.`origin_district_id` | string | preserved for whole stay |
| cohort.`admit_week` | int | zero-based interval index of admission; **`-1` allowed** as the sentinel for pre-simulation seeded cohorts |
| cohort.`remaining_los` | int | weeks; decremented each week |
| cohort.`count` | float | people (= beds) |

Derived quantities (order matters — count accepted exactly once):

```
# within a week, in order:
discharge due cohorts (remaining_los == 0 at the discharge boundary) are removed
retained   = Σ cohorts.count  of SURVIVORS, measured BEFORE this week's commit
accepted_new is booked as NEW cohorts during commit (batch booking)
committed  = baseline + Σ cohorts.count  AFTER commit
           = baseline + retained + accepted_new        # equivalently; never add accepted twice
inherited_deficit = max(0, baseline + retained − Ceff)  # occupants survive; never deleted
committed <= max(Ceff, baseline + retained)             # generalized invariant
```

Occupants **survive closure/reduction**; cohort records are never deleted.

Example H1 cohorts **after the interval-0 commit** (display "Week 1";
`admit_week=0`): `(D1,0,2,27.829), (D2,0,2,27.059), (D3,0,2,4.906),
(D2,0,2,12.207 rerouted)`; `committed = 60 + 90 = 150`. (Weeks are zero-based
interval indices; cohort `admit_week=-1` denotes a pre-simulation seeded cohort.)

---

## FDNAGraph  (owner WS4 build; consumed WS2)

`FDNAGraph` contains **only FDNA dependency edges** — it is one of the three
disjoint edge families (the other two, accessibility and patient-flow, live in
`Accessibility` and `RequestTable` respectively and are **not** part of this
type).

| Field | Type | Unit / constraint |
|---|---|---|
| `hospital_nodes` | list[string] | own score = exogenous upper bound |
| `district_nodes` | list[string] | intrinsic baseline 100 |
| `edges` | list[Edge] | dependency edges only |
| Edge.`feeder`,`receiver` | string | endpoints exist |
| Edge.`kind` | enum | `hospital_hospital` \| `hospital_district` |
| Edge.`alpha` | float | `[0,1]` |
| Edge.`beta` | float | `[0,100]` |

Only `hospital_hospital` (symmetric by default; configurable assumption) and
`hospital_district` (feeder = hospital) dependency edges exist. There is **no**
`district→hospital` edge and **no** accessibility or flow edge in this graph. FDNA
dependency edges are **not** routing/transfer edges (ADR-GRAPH-1).

---

## FDNAResult  (owner WS2; produced twice: before & after)

| Field | Type | Unit / constraint |
|---|---|---|
| `hospital_scores` | map[string→float] | 0–100 |
| `district_scores` | map[string→float] | 0–100 |
| `iterations` | int | `<= max_iterations` |
| `converged` | bool | **must be true** or run errors |
| `max_delta` | float | final residual `<= tol` |

Example week 1 before: H2=63.351, district D2=75.729. After: H2=68.141, D2=78.469.

---

## RerouteRecord / RerouteResult  (owner WS4)

`RerouteRecord` (one per positive move):

| Field | Type | Unit / constraint |
|---|---|---|
| `week` | int | zero-based **interval** index (display "Week 1" = `week 0`) |
| `district` | string | origin |
| `source_hospital` | string | intended hospital whose residual row is consumed |
| `destination` | string | receiving hospital (open, has `free_new`) |
| `amount` | float | `> 0` people/week |

`RerouteResult`: list of records + final `accepted[j,i]`, `residual[j,i]`,
`unmet_j`. Redirected ⊆ accepted. **Zero records ⇒ loads/scores identical
before/after.**

Example: `{week:0, district:"D2", source_hospital:"H2", destination:"H1",
amount:12.207}` (the frozen walkthrough's "Week 1" reroute).

---

## WeekResult  (owner WS5 IL3; immutable)

| Field | Type | Notes |
|---|---|---|
| `week` | int | zero-based interval index; optional `week_start`/`week_end` dates |
| `state` | SEIRState | SEIR end-of-week (boundary) |
| `before` | WeekSnapshot | provisional direct reservations; `AllocationSnapshot.phase=before` |
| `after` | WeekSnapshot | redirects applied, final; `AllocationSnapshot.phase=after` |
| `end_hospital_state` | HospitalStateMap | **physical** end-of-week state after the AFTER commit (single, not per-phase) |
| `active_injections` | list[Injection] | sorted canonical order |
| `diagnostics` | map | `mass`, `share`, `patient`, `fdna_convergence` checks |

`before`/`after` share one disease state; no hidden recompute on view. Only the
AFTER phase commits; `end_hospital_state` is the committed physical result (see
`contracts/stage-io-and-signatures.md` §3). Per-district unmet and per-hospital
inherited deficit live inside each phase's `AllocationSnapshot`.

---

## RunResult  (owner WS5 API; immutable)

| Field | Type | Notes |
|---|---|---|
| `run_id` | string | hash of normalized config **+ ordered injections/scenario spec + initial SEIRState checksum + initial HospitalStateMap checksum + data checksums** + algo version (see `stage-io-and-signatures.md` §7.1; config alone would let scenarios collide, and seeded cohorts change results) |
| `data_mode` | enum | `historical_data` \| `mixed_assumptions` \| `synthetic_demo` |
| `config` | normalized config | |
| `weeks` | list[WeekResult] | one per week |
| `validation` | ValidationReport \| null | |
| `data_manifest` | map | sources, dates, warnings |
| `warnings` | list[string] | |

---

## ValidationReport  (owner WS3)

| Field | Type | Notes |
|---|---|---|
| `status` | enum | `verified` \| `unavailable` \| `incomplete` |
| `target_variable` | string \| null | exact observed field |
| `source_url`, `source_last_data_date` | string/date \| null | |
| `training_*`, `test_*` | date \| null | windows fixed before scoring |
| `matched_hospitals`, `forecast_pairs` | int | |
| `fitted_r0`, `fitted_p_h` | float \| null | |
| `model_mae_beds`, `persistence_mae_beds`, `rerouting_off_mae_beds` | float \| null | |
| `notes` | list[string] | limitations/exclusions |

If `status != verified` or `forecast_pairs == 0`: no numeric headline; render a
neutral explanation. Synthetic fixtures never set `verified`.

---

## WeekView  (owner WS5 view_models; flat UI model)

Flattened, serialized projection of one `WeekResult` phase for the app:
`run_id, data_mode, week_index, week_label, scenario_id, phase (before|after),
active_injections, metrics{overloaded_hospitals, unmet_need_people,
inherited_deficit_beds, rerouted_people, districts_below_threshold},
hospitals[HospitalWeekView], districts[DistrictWeekView], reroutes[RerouteRecord],
geometry_join_field=district_id, warnings`.

- `HospitalWeekView`: `hospital_id, name, lat, lon, staffed_beds,
  effective_capacity_beds, baseline_beds, retained_beds, request_people,
  accepted_new_beds, committed_beds, inherited_deficit_beds, requested_load,
  own_score, fdna_final_score, excess, injection_flag`.
- `DistrictWeekView`: `district_id, population, centroid_lat, centroid_lon,
  access_score, accessibility_index, new_admission_need_people,
  unmet_need_people, ej_flag, hospital_shares`.

All optional real-observation fields are nullable and never zero-filled. The UI
derives this from the API; it never recomputes model math.
