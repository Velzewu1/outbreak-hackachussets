# Weekly state machine

Complete week-by-week execution semantics for the weekly pipeline. Specifies
**exactly when** each event happens, what is mutable vs immutable, and which
canonical type carries each handoff. Implements corrections 1, 2, 3, 5, and 7 of
`Addiotional Info 1.txt` under the **new-admission-request** model (the earlier
standing-census model is discarded — see `docs/mathematical-model.md`).

Related: `docs/mathematical-model.md`, `architecture.md`, `contracts/`,
`docs/integration-plan.md`.

---

## 1. State objects and mutability

| Object | Lifetime | Mutable? | Owner |
|---|---|---|---|
| `ValidatedInputs` (config + data bundle) | whole run | **immutable** | orchestration |
| `Accessibility` (distances, shares, base graph) | whole run | **immutable** after prep | network |
| `HospitalState` | persists across weeks | **mutable** (controlled) | hospital/allocation |
| `SEIRState` | per week boundary | replaced each week | SEIR |
| `WeekSnapshot` (`before` / `after`) | per week | **immutable** once recorded | IL3 |
| `WeekResult` | per week | **immutable** once packaged | IL3 |
| `injection_list` | whole run | **immutable** | scenario |

### 1.1 `HospitalState` (persistent — CORRECTIONS 1, 2, 7)

```
HospitalState (per hospital_id):
  baseline:  non-epidemic occupied beds (count, immovable)
  cohorts:   list of (origin_district_id, admit_week, remaining_los, count)
  # retained(h) = Σ cohorts.count of SURVIVORS, measured BEFORE this week's commit
  # committed(h) = baseline + Σ cohorts.count AFTER commit
  #              = baseline + retained + accepted_new(h)   (equivalently; count accepted ONCE)
  #   committed(h) <= max(Ceff, baseline + retained)   (inherited deficit may exceed Ceff)
```

- **Only new admissions are allocated/rerouted** each week. Existing cohorts keep
  their hospital and origin district ID until discharged (correction 1).
- **Existing occupants survive closure** (correction 7). Closure sets `Ceff=0`;
  `baseline + retained` become an **inherited deficit**; cohort records are
  **never deleted**.
- Scheduled discharges decrement `remaining_los`; elapsed cohorts leave.

### 1.2 Immutable weekly snapshots (CORRECTION 2)

Each week produces two immutable snapshots — `before` and `after` rerouting — for
the same epidemiological week. They are read by the UI, never recomputed on view.

---

## 2. The ordered weekly sequence

One iteration = one week. SEIR may use 7 daily substeps internally; all external
quantities are weekly.

```
PREP (once per run, before week 0):
  P0. DATA -> SEPARATE: district & hospital tables
  P1. build Accessibility (distances, a_ji, s_ji, A_j) and base FDNA graph
  P2. initialize HospitalState (baseline occupancy; empty epidemic cohorts)

FOR week t in [0 .. weeks-1]:

  STEP 1  CARRY / INIT SEIR STATE
          starting_state = init_state(...)   if t==0 else carry_state(prev)  -> SEIRState

  STEP 2  SELECT ACTIVE INTERVENTIONS                      (CORRECTION 2: when interventions activate)
          active = { inj : inj.start_week <= t AND (inj.end_week is null OR t < inj.end_week) }
          # start inclusive; end exclusive; end_week == null => open-ended
          # from immutable base config; capacity factors do NOT compound

  STEP 3  SCHEDULED DISCHARGES                             (CORRECTION 2: when discharges occur)
          for each hospital: remaining_los -= 1 for each cohort;
          discharged(h) = cohorts hitting 0 (removed);
          retained(h)   = Σ surviving cohort counts
          # discharges fire BEFORE new demand is placed, freeing capacity

  STEP 4  GENERATE NEW-ADMISSION NEED                      (CORRECTION 2: when demand is generated)
          epi_out = SEIR.step_week(starting_state, disease_config)
            -> SEIRWeekOutput { state_end, H_need_j, new_infections_j }
          # H_need_j = NEW admission need (people/week), NOT occupancy

  STEP 5  PROVISIONAL REQUESTS + BEFORE LOADS              (CORRECTION 2: provisional assignment)
          apply active injections (ordered, §4)
          request[j,i]        = s_ji * H_need_j
          requested_load_i    = baseline_i + retained_i + request_i   (NEED view)
          own_i(before)       = 100*min(1, Ceff_i / requested_load_i) ; closed => 0
          # provisional: nothing committed to HospitalState yet

  STEP 6  FDNA PASS 1 (BEFORE)                             (CORRECTION 3: pass 1)
          before_fdna = FDNA.solve(own_before)             -> FDNAResult (bounded, converged)
          before_districts = district scores

  STEP 7  DIRECT RESERVATION + ROW REROUTE (global)        (CORRECTIONS 1, 5)
          free_new_i = max(0, Ceff_i - baseline_i - retained_i)
          7a DIRECT: districts ascending id; within district, candidates descending
             share, tie (distance,id). Each (j,h) request row reserves up to free_new_h,
             keeping a per-row residual[j,h] = request[j,h] - direct[j,h].
          7b REROUTE: residual rows (descending residual, tie (district,source)) each
             move to a DESTINATION c != source with spare free_new; record
             RerouteRecord(district, source_hospital, destination, amount).
          accepted[j,i] <= free_new_i ; baseline/retained immovable; closed never receives;
          origin IDs preserved; redirected ⊆ accepted; accepted_j + unmet_j = H_need_j

  STEP 8  AFTER LOADS + FDNA PASS 2                        (CORRECTION 3: pass 2)
          post_request_i = accepted_final_i + Σ_j residual[j,i]   # residuals STAY on source rows
          requested_load_i(after) = baseline_i + retained_i + post_request_i
          own_i(after)  = 100*min(1, Ceff_i / requested_load_i(after)) ; closed => 0
          after_fdna = FDNA.solve(own_after) ; after_districts = district scores
          # INVARIANT: zero reroutes => post_request == request => after == before (loads & scores)
          # exactly two passes; NO score-to-bed feedback, NO capacity<->FDNA loop

  STEP 9  COMMIT ACCEPTED NEW ADMISSIONS                   (CORRECTION 2: when final admissions commit)
          append accepted cohorts to HospitalState.cohorts (BATCH BOOKING, see §3.1):
            (origin_district_id, admit_week=t, remaining_los=los_weeks, count)
          committed_i = baseline_i + Σ (cohorts AFTER append)
                      = baseline_i + retained_i + accepted_new_i   # count accepted ONCE
          committed_i <= max(Ceff_i, baseline_i + retained_i)      # generalized invariant
          record unmet_j  (NOT readmitted, NOT added to cohorts, NOT called beds)
          record inherited_deficit for closed hospitals (occupants survive)

  STEP 10 RECORD FDNA SCORES + PACKAGE                     (CORRECTION 2: when FDNA scores recorded)
          week_result = IL3.package_results(epi_out, before_snapshot, after_snapshot,
                        reroutes, active_injections, diagnostics)  -> WeekResult (immutable)

  STEP 11 NEXT STATE
          prev = IL3.next_state(epi_out)   # SEIR S,E,I,R; UNCHANGED by reroute/injection

END FOR
validate_run_history(); export serializable RunResult
```

### 2.1 Event-timing summary (CORRECTION 2)

| Event | Step | Notes |
|---|---|---|
| Interventions activate | 2 | `start_week <= t AND (end_week is null OR t < end_week)`; no compounding |
| Discharges occur | 3 | before demand; LOS-driven; frees capacity |
| New-admission need generated | 4 | `H_need_j`; never occupancy |
| Provisional requests evaluated | 5 | requested-load scores (need view); not committed |
| FDNA before recorded | 6 | pass 1 |
| Accept + reroute | 7 | new admissions only; global; `accepted+unmet=demand` |
| FDNA after recorded | 8 + 10 | pass 2 |
| Final admissions committed | 9 | into persistent cohorts; unmet not readmitted |

---

## 3. Requested load vs committed occupancy (no feedback)

- **requested_load** (need): `baseline + retained + request_i` (before) or
  `baseline + retained + post_request_i` (after) → drives own/FDNA scores so
  stress is visible even when beds are full. `post_request_i = accepted_final_i +
  Σ_j residual[j,i]`, residuals preserved on their original intended-hospital rows
  (no reattribution).
- **committed occupancy** (physical): `baseline + retained + accepted`, bounded by
  `committed_i <= max(Ceff_i, baseline_i + retained_i)`. When there is no inherited
  deficit (`baseline + retained <= Ceff`), `committed <= Ceff` and typically `<
  Ceff` unless fully filled — it is **not always equal to `Ceff`**. When a
  reduction/closure leaves an `inherited_deficit_i = max(0, baseline_i +
  retained_i - Ceff_i) > 0`, `committed_i = baseline_i + retained_i > Ceff_i`. Only
  this is called "occupied beds"; unmet need is never beds.
- Scores never create or remove beds (no score-to-bed feedback). The two FDNA
  passes differ only by reroute movement; **zero reroutes ⇒ identical before and
  after** loads and scores.

---

## 4. Injection application order within a week (STEP 5)

Applied from the immutable base config (blueprint §10.4):

1. eligibility / `set_share` edits; re-validate `Σ s = 1`.
2. capacity / closure; `set_score` cap / `reduce_score`; validate bounds. Closure
   sets `Ceff=0` and preserves occupants (inherited deficit).
3. hospital↔hospital dependency edits; keep symmetry unless an explicit documented
   directed override.
4. build requests, loads, own scores, graph; FDNA pass 1; accept+reroute; FDNA
   pass 2.
5. log every applied injection in canonical sorted order with old/new values and
   override warnings.

Contradictory injections on the same property/week are rejected (default safe
rule) except documented `reduce_score` stacking.

---

## 5. Scenario isolation (CORRECTION 7)

- Baseline and intervention runs start from **identical initial state and seed**;
  no cross-scenario mutation of `HospitalState`, SEIR state, or inputs.
- A sweep rebuilds state per run (never reuses a mutated object).
- Closing a hospital does not erase inpatients (§1.1).
- An injection beginning at week `t` leaves weeks `0..t-1` identical to baseline.

---

## 6. Worked two-week trace (SYNTHETIC)

`docs/end-to-end-walkthrough.md` gives the fully numeric 3-district / 3-hospital
trace that exercises every step: new-admission need, requested-load scores,
acceptance caps, global reroute, residual unmet need, scheduled discharges,
retained cohorts carried into week 2, and a closure variant showing an inherited
deficit (occupants not deleted). All arithmetic was verified with transient
scripts.
