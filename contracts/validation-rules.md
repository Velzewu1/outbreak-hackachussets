# Contracts — validation rules

Invariants and pass/fail checks every implementation must satisfy. Specifications
only; gate CLOSED. Tolerances are named in `config.yaml` and must be small enough
never to hide a missing patient category. Never use exact float `==` for
non-integer sums.

---

## 1. Population / epidemic

| ID | Rule |
|---|---|
| P-1 | `\| S_j + E_j + I_j + R_j − N_j \| <= mass_tol` (per district, each week boundary) |
| P-2 | `0 <= S_j, E_j, I_j, R_j` |
| P-3 | `H_need_j = p_H_j · (I-exit_j) >= 0`, units people/week, **never** beds |
| P-4 | seed 0 ⇒ `H_need = 0` and no epidemic admissions |
| P-5 | week `t+1` starts from week `t` `state_end`; not a fresh seed |
| P-6 | rerouting / injections do **not** change SEIR state (no feedback) |

## 2. Accessibility

| ID | Rule |
|---|---|
| A-1 | `\| Σ_i s_ji − 1 \| <= share_tol` for each district with ≥1 eligible hospital |
| A-2 | non-eligible hospital: `a=0, s=0`, no hospital→district FDNA edge |
| A-3 | eligibility = within `radius_km` then nearest `min(k, eligible)` |
| A-4 | tie-break `(distance, hospital_id)`; results ID-order independent |
| A-5 | no eligible hospital ⇒ explicit validation failure (no silent 0/100) |

## 3. Requests, acceptance, occupancy

| ID | Rule |
|---|---|
| R-1 | `request[j,i] = s_ji · H_need_j` |
| R-2 | per row: `requested = direct_accepted + rerouted_out + residual` |
| R-3 | `free_new_i = max(0, Ceff_i − baseline_i − retained_i)` |
| R-4 | `accepted_new_i <= free_new_i` (hard cap, everywhere) |
| R-5 | `committed_i = baseline_i + retained_i + accepted_new_i` |
| R-6 | `committed_i <= max(Ceff_i, baseline_i + retained_i)` (generalized) |
| R-7 | `inherited_deficit_i = max(0, baseline_i + retained_i − Ceff_i)`; occupants survive, cohorts never deleted |
| R-8 | `accepted_j + unmet_j = H_need_j` per origin district; `unmet_j = Σ_i residual[j,i]` |
| R-9 | `unmet` is people/week need, never beds, never silently readmitted |

## 4. Rerouting

| ID | Rule |
|---|---|
| X-1 | reroute moves **new-admission residual rows only**; baseline/retained immovable |
| X-2 | no move into a closed/ineligible hospital or back to its own source |
| X-3 | each `RerouteRecord` = `(week, district, source_hospital, destination, amount>0)` |
| X-4 | residual stays on its original `(district, source)` row (no reattribution) |
| X-5 | `post_request_i = accepted_final_i + Σ_j residual[j,i]` |
| X-6 | redirected ⊆ accepted (not a separate demand category; no double count) |
| X-7 | **zero reroutes ⇒ before == after** (loads and all scores identical) |
| X-8 | post-reroute total positive excess `<=` pre-reroute (float tol) |
| X-9 | deterministic: direct order (district asc, candidate desc share, tie dist/id); reroute order (residual desc, tie district/source) |
| X-10 | source-row conservation: `request[j,i] = direct[j,i] + rerouted_out[j,i] + residual[j,i]`; destination accounting `accepted[j,h] = direct[j,h] + incoming_rerouted[j,h]` |
| X-11 | `AllocationSnapshot`: BEFORE phase has `reroute_volume=0`, `reroutes=[]`, `accepted=direct`, no commit; AFTER phase applies redirects and is the **only** phase that commits to `HospitalState` |

## 5. FDNA

| ID | Rule |
|---|---|
| F-1 | golden: one failed hospital, others 100, α_D=0.9 ⇒ district 0 / 50 / 75 for 1 / 2 / 4 equal hospitals |
| F-2 | own score: closed/`Ceff=0` ⇒ 0 (checked **first**); else `load==0` ⇒ 100; else `100·min(1, Ceff/requested_load)` |
| F-3 | hospital solve: synchronous Jacobi from own-score init; stop `max\|ΔP\| <= 0.1`; cap 500; non-convergence raises (never silent) |
| F-4 | `alpha_h = 0` ⇒ no hospital→hospital spillover **when `beta_h = 100`**; with smaller `beta_h` the criticality term may still cap a neighbor |
| F-5 | closed node stays 0; healthy neighbor cannot lift it above own |
| F-6 | district uses post-cascade `P_i` and unchanged base shares |
| F-7 | all scores in `[0,100]`; ID-order independent |

## 6. Injections

| ID | Rule |
|---|---|
| I-1 | active iff `start_week <= t` and (`end_week is null` or `t < end_week`); weeks before `start` identical to baseline |
| I-2 | applied from base config; no capacity-factor compounding across weeks |
| I-3 | `set_share` keeps `Σ s = 1` over the authorized eligible set |
| I-4 | `add_edge` changes FDNA dependency only; routing eligibility is a separate typed op |
| I-5 | invalid target / out-of-range value ⇒ explicit error |
| I-6 | contradictory injections on same property/week rejected (except documented `reduce_score` stacking) |

## 7. Run / reproducibility

| ID | Rule |
|---|---|
| D-1 | identical config + data ⇒ identical `RunResult` within tolerance |
| D-2 | `before`/`after` share one disease state |
| D-3 | baseline vs intervention: pre-injection weeks byte-identical |
| D-4 | scenarios start from identical init + seed; no cross-scenario mutation |
| D-5 | `run_id` = hash(normalized config + input checksums + algo version) |

## 8. Validation (honesty)

| ID | Rule |
|---|---|
| V-1 | MAE vs persistence computed on identical matched `(hospital, week)` pairs |
| V-2 | missing observation excluded from **both** methods; reason recorded |
| V-3 | dataset unavailable ⇒ `status=unavailable`, null MAE, no fake 0 |
| V-4 | synthetic fixture never marked `verified` or shown as a real metric |
| V-5 | rerouting-off is a labeled counterfactual ablation, not causal proof |

## 9. Walkthrough acceptance (the frozen example)

The one example in `docs/end-to-end-walkthrough.md` must satisfy P-1, A-1, R-4,
R-6, R-7, R-8, X-6, X-7, F-1 with the exact numbers shown there (verified by a
transient script). Any contract change that alters those numbers must update the
walkthrough in the same change (see `docs/integration-plan.md` §5).
