# Integration plan

Producer–consumer contract matrix, workstream dependencies, and merge gates for
the five parallel workstreams.

> **Status (2026-10-24): gate OPEN.** The architecture was approved and the system
> is implemented (one Kiro author across all workstreams). The "gate is CLOSED"
> note below is historical.

Workstreams (from `Addiotional Info 1.txt`):

1. **WS1 SEIR** — IL1, SEIR need model, fitting.
2. **WS2 FDNA** — hospital fixed point, district scores (two passes).
3. **WS3 Data/Accessibility/Evaluation** — data, separate, accessibility,
   validation.
4. **WS4 Hospital/Allocation/Scenario** — IL2, analysis (direct reservation +
   reroute), injections, `HospitalState`.
5. **WS5 Orchestration/Streamlit/Integration** — contracts, config, runner, api,
   il3, app.

WS5 owns all shared files (`contracts/`, `config.yaml`,
`pipeline/{contracts,config,runner,api,il3}.py`, app, README, deps). Others
propose changes via review.

---

## 1. Producer → consumer contract matrix

Every cross-module handoff uses exactly one canonical type (`contracts/`). A cell
reads: **producer** emits **type** → **consumers**.

| Canonical type | Producer (owner) | Consumers | Key invariants carried |
|---|---|---|---|
| `DistrictTable` | WS3 (separate) | WS1, WS3(access), WS5 | stable `district_id` (string), `population>0`, `risk_weight>=0`, geometry |
| `HospitalTable` | WS3 (separate) | WS3(access), WS4, WS5 | `hospital_id`, coords, `staffed_beds>0`, `baseline` as bed **count** |
| `Accessibility` | WS3 (accessibility) | WS4 (IL2), WS2 (district) | `Σ s_ji = 1`; eligibility radius+k; `A_j` index |
| `SEIRState` | WS1 (il1) | WS1 (seir), WS5 (il3 carry) | `S+E+I+R=N`; nonnegative |
| `SEIRWeekOutput` | WS1 (seir) | WS4 (IL2), WS5, WS3 (fit) | `H_need_j` (people/week, **not** beds); `S,E,I,R` end |
| `RequestRow` / `RequestTable` | WS4 (il2) | WS4 (analysis), WS2 | `request[j,i]=s_ji·H_need_j`; origin `district_id` kept |
| `HospitalLoad` | WS4 (il2) | WS2 (fdna), WS5 | requested-load view; `own_i`; units documented |
| `FDNAGraph` | WS4 (il2) | WS2 (fdna) | three edge families disjoint; symmetry configurable |
| `FDNAResult` | WS2 (fdna) | WS4 (analysis), WS5 | scores 0–100; `converged`, `iterations`, `max_delta` |
| `RerouteResult` / `RerouteRecord` | WS4 (analysis) | WS5 (il3) | `(district, source_hospital, destination, amount)`; redirected ⊆ accepted |
| `HospitalState` | WS4 (persistent) | WS4, WS5 | cohorts `(origin, admit_week, remaining_los, count)`; occupants survive closure |
| `Injection` | WS4 (injections) | WS4 (il2), WS5 | start-inclusive/end-exclusive; from base config; no compounding |
| `WeekResult` | WS5 (il3) | WS5 (api/app), WS3 (validation) | immutable; before/after same week |
| `RunResult` | WS5 (api) | WS5 (app), WS3 | `data_mode`; deterministic `run_id` |
| `ValidationReport` | WS3 (validation) | WS5 (app) | null/unavailable allowed; real holdout only |
| `WeekView` | WS5 (view_models) | WS5 (app) | flat UI model; nullable observations never zero-filled |

---

## 2. Dependency DAG (who unblocks whom)

```
WS5 contracts+config+fixtures (V0)
   ├─> WS3 DistrictTable/HospitalTable ─┬─> WS3 Accessibility ─┐
   │                                    │                      ├─> WS4 IL2 ─> WS2 FDNA ─> WS4 analysis
   ├─> WS1 SEIRState/SEIRWeekOutput ────┘                      │          (2 passes)        │
   │                                                            └──────────────┐             │
   └─> WS5 runner/api/il3 skeleton <────────────────────────────────── WS4 ───┘             │
                                                                                             │
   WS3 historical data ─> WS1 fit ─> WS3 backtest (MAE vs persistence)                       │
                                                                                             │
   WS5 app (on fixtures first) <────────────────── WeekView / RunResult <────────────────────┘
```

WS1, WS2, WS4-math, and WS5-app can all start against **frozen synthetic
fixtures** once V0 contracts are frozen. Real data (WS3) and fitting (WS1) proceed
in parallel and must not block the vertical slice.

> SEIR and FDNA may reuse existing code from elsewhere, but they **adapt to these
> contracts**; the shared interfaces are not redesigned around inaccessible code.

---

## 3. Merge gates

A branch merges only when all gates for its type pass. WS5 verifies.

### G0 — contract conformance (every workstream)
- Emitted/consumed objects match `contracts/` exactly: field names, types, units,
  ID ordering, serialization.
- No forbidden imports (no stage imports Streamlit; app imports `pipeline.api`
  only; FDNA/SEIR/analysis do not import each other except via contracts).

### G1 — SEIR (WS1)
- `S+E+I+R=N` within `mass_tol`; nonnegative; seed 0 ⇒ zero need; week continuity
  (week `t+1` starts from `t` end); rerouting/injection leave SEIR unchanged.
- `H_need` distinct from occupancy; derived from `p_H·(I-exit)`.

### G2 — Accessibility (WS3)
- `Σ s_ji = 1` (tol); radius+k eligibility; tie-break `(distance,id)`; no eligible
  ⇒ explicit failure.

### G3 — IL2 / allocation (WS4)
- `request=s·H_need`; direct reservation order deterministic; row residuals
  preserved; `accepted_new_i ≤ free_new_i`; `committed ≤ max(Ceff,
  baseline+retained)`; `inherited_deficit` computed; `accepted_j+unmet_j=H_need_j`.

### G4 — FDNA (WS2)
- Golden district checks 0/50/75 (1/2/4 equal hospitals); cyclic solve converges;
  `alpha_h=0` ⇒ no spillover; non-convergence raises; ID-order independence.

### G5 — Reroute / accounting (WS4)
- `RerouteRecord(district, source, destination, amount)`; redirected ⊆ accepted;
  no move into closed/ineligible/source; **zero moves ⇒ before==after** (loads &
  scores); monotone excess reduction.

### G6 — Injections (WS4)
- start-inclusive/end-exclusive; no capacity compounding; `set_share` keeps
  `Σ=1`; dependency edge ≠ routing edge; contradictions rejected.

### G7 — Runner/API/IL3 (WS5)
- ≥2-week deterministic run; before/after same disease state; pre-injection weeks
  identical to baseline; reproducible `run_id`.

### G8 — Validation (WS3)
- MAE vs persistence on identical matched pairs **only if** real data; else
  `status=unavailable`; synthetic never shown as verified.

### G9 — Frontend (WS5)
- Offline start; every control maps to one engine field; no dead controls; no
  fabricated observed series; exports carry `run_id`/mode/units.

---

## 4. Vertical-slice milestones

| Milestone | Content | Gates |
|---|---|---|
| V0 | frozen contracts/config + synthetic fixtures + runner skeleton | G0 |
| V1 | synthetic 2-week SEIR → IL2 → FDNA before/after, no injections | G1,G2,G3,G4,G7 |
| V2 | direct reservation + reroute + injections; conservation & zero-move | G3,G4,G5,G6 |
| V3 | Streamlit on fixtures: map, controls, before/after, tables | G9 |
| V4 | real data + fit + holdout MAE vs persistence (or `unavailable`) | G8 |
| V5 | offline demo, README, exports | all |

Re-run integration after every merge. No branch introduces renamed fields or
duplicate modules. Use branches/worktrees when available; otherwise strict file
ownership.

---

## 5. Change-control for shared contracts

A contract change requires: (1) a written proposal referencing the affected type;
(2) sign-off from every consuming workstream; (3) simultaneous update of
`contracts/`, the math model/state machine if semantics change, and the
walkthrough if numbers change. No agent edits `contracts/` unilaterally.
