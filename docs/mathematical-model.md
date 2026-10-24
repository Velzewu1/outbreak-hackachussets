# Mathematical model

Authoritative equations, variable meanings, units, and conservation laws for the
DS+X weekly epidemic → hospital dependency → rerouting → access simulator
(working name *ResiliNet | Boston Hospital Cascade*).

This file is the single source of truth for the math. Where the primary plan
(`docs/source/DSX-project-plan.md`) and the blueprint
(`docs/DSX_Kiro_Master_Implementation_Blueprint.md`) disagree, the mandatory
corrections in `Addiotional Info 1.txt` win and are reflected here. Choices
beyond the explicit corrections are labeled **PROPOSED** and collected in
`docs/architecture-decisions.md`.

> **Status (2026-10-24): gate OPEN.** The architecture and default PROPOSED
> choices were approved and implemented in `pipeline/`. "gate CLOSED" phrases in
> this file are historical; the equations below are the implemented model.

> **Superseded model (do not implement).** An earlier draft used
> `flow = s·H` with `epidemic_demand = Σ H` and rerouted the *standing census*.
> That violated corrections 1 and 5 (it re-allocated existing inpatients and
> conflated unmet need with occupied beds). It is **discarded**. This file and
> all contracts/walkthrough now use **new-admission requests only** with
> persistent retained cohorts, as specified below.

All numeric examples are **SYNTHETIC / ILLUSTRATIVE** unit values, not observed
Boston data. They were verified with transient scripts (see
`docs/end-to-end-walkthrough.md`, "How these numbers were verified").

---

## 0. Index sets, symbols, and units

| Symbol | Meaning | Index | Unit |
|---|---|---|---|
| `j` | district (census tract by default) | `district_id` (string) | — |
| `i`, `h`, `c` | hospital | `hospital_id` (string) | — |
| `t` | simulation week | integer `0..weeks-1` | week |
| `N_j` | district resident population | `[district]` | people |
| `S,E,I,R` | SEIR compartments (**mutually exclusive, sum to N**) | `[district]` | people |
| `H_need_j(t)` | **new-admission need** (auxiliary signal, NOT occupancy) | `[district]` | people/week |
| `new_infections_j(t)` | new infections during week `t` | `[district]` | people/week |
| `d_ji` | great-circle distance district `j` → hospital `i` | `[district,hospital]` | km |
| `a_ji` | accessibility kernel value | `[district,hospital]` | dimensionless index |
| `s_ji` | base catchment share | `[district,hospital]` | fraction, Σ=1 |
| `A_j` | total accessibility index | `[district]` | dimensionless index |
| `C_i` | staffed beds | `[hospital]` | beds |
| `baseline_i` | baseline occupied beds (non-epidemic), a **count** | `[hospital]` | beds |
| `retained_i(t)` | epidemic cohorts surviving after scheduled discharges | `[hospital]` | beds |
| `request_i(t)` | new-admission requests routed to `i` (= `Σ_j request[j,i]`) | `[hospital]` | people/week |
| `accepted_i(t)` | new admissions actually accepted by `i` | `[hospital]` | beds |
| `Ceff_i` | effective capacity after injections | `[hospital]` | beds |
| `committed_i(t)` | committed occupancy = `baseline_i + retained_i + accepted_i` | `[hospital]` | beds |
| `requested_load_i(t)` | `baseline_i + retained_i + request_i` (**need view**) | `[hospital]` | people |
| `own_i` | hospital own operability score | `[hospital]` | 0–100 |
| `P_i` | hospital FDNA operability score (post-cascade) | `[hospital]` | 0–100 |
| `DistrictScore_j` | district FDNA-based access score | `[district]` | 0–100 |
| `α_D` | district dependence strength | scalar | 0–1 |
| `α_H`, `β_H` | hospital↔hospital strength / criticality | scalar | 0–1 / 0–100 |
| `d0` | distance-decay scale | scalar | km |

**Units are never mixed.** `baseline_i` is a bed *count*, never a fraction; a
fallback fraction `f` is converted once as `baseline_i = f · C_i`. Scores (0–100)
are never added to bed counts. **Unmet need is a people/week flow, never
"occupied beds."**

---

## 1. SEIR epidemic core and the need signal (CORRECTION 6)

### 1.1 Mass balance excludes hospitalization (resolves H ambiguity)

Correction 6 requires an explicit decision on whether `H` is a mutually exclusive
compartment or an auxiliary metric. **Decision (ADR-SEIR-3, PROPOSED):** the SEIR
compartments are `S, E, I, R` and they alone conserve population:

```
dS/dt = -beta * S * I / N
dE/dt =  beta * S * I / N - sigma * E
dI/dt =  sigma * E        - gamma * I
dR/dt =  gamma * I

beta = R0 / infectious_days ,  sigma = 1 / latent_days ,  gamma = 1 / infectious_days

S_j + E_j + I_j + R_j = N_j          (mass conservation; H is NOT in this sum)
0 <= S_j, E_j, I_j, R_j              (nonnegativity)
```

Hospitalization is an **auxiliary need signal** derived from the infectious
outflow, not a compartment that drains the population. Each weekly quantity is an
**integrated count of people over the week** (not an instantaneous rate, and never
added to a bed stock as a rate):

```
i_exit_j(t)         = integral over week t of ( gamma * I_j )      # people leaving I
e_to_i_j(t)         = integral over week t of ( sigma * E_j )      # people E -> I
new_infections_j(t) = integral over week t of ( beta * S_j * I_j / N_j )   # people S -> E
H_need_j(t)         = p_H_j * i_exit_j(t)                          # new-admission need (people/week)
```

`SEIRWeekOutput` carries `i_exit`, `e_to_i`, `new_infections`, and `H_need` as
per-district people counts (see `contracts/pipeline-types.md`).

`H_need_j(t)` is the count of residents of `j` who **need** a new hospital
admission in week `t`, derived from the `I`-exit count
(`integral of gamma * I` over the week) times `p_H_j`. It is a
demand/epidemiology quantity. It is **never** reported as occupied beds.

> **Fixture note.** The worked example in `docs/end-to-end-walkthrough.md` uses a
> **labeled hand-chosen SEIR fixture** for the `S/E/I/R` states and the weekly
> `I`-exit / new-infection counts. Those numbers are internally consistent
> (`S+E+I+R=N`, balanced flows) but are **not** claimed to be the output of an ODE
> integration. A production SEIR step will integrate the equations above; the
> contract and conservation laws are identical either way. Actual occupancy comes only from accepted hospital
cohorts (§3–§4). This cleanly separates epidemiology/need from actual accepted
occupancy, as the review requires.

This is the "need-state" resolution offered as the acceptable alternative in the
review: `S+E+I+R=N`, and `H_actual` arises only from accepted cohorts. An
equivalent explicit `H` compartment model (people removed from community mixing
on admission) is recorded as an alternative in `docs/architecture-decisions.md`
(ADR-SEIR-3); both are PROPOSED pending approval, and exactly one must be chosen.

### 1.2 Option A — one shared regional curve (PROPOSED, blueprint §8.2)

1. All districts share one normalized `S/E/I/R` trajectory (same `R0`, latent,
   infectious, seed fraction). No between-district coupling.
2. District counts = normalized fractions × `N_j`.
3. Per-district hospitalization risk `p_H_j = clip(p_H · risk_weight_j, 0, 1)`;
   `H_need_j` therefore varies with `risk_weight` while `S/E/I/R` share one curve.
4. `risk_weight` scales **hospitalization need**, not transmission (ADR-SEIR-1).

### 1.3 Option B (metapopulation) — DEFERRED (scope rule 9).

### 1.4 Initial and carried state

- Week 0: `I_j = seed_fraction · N_j`, `S_j = N_j − I_j`, `E_j=R_j=0`.
- Week `t+1` starts from exactly `state_end(t)`.
- Rerouting and injections **do not** change the SEIR state (no feedback in v1).
- `H_need` is recomputed from the epidemic each week; it is not carried.

---

## 2. Accessibility and catchment shares

```
Exponential (default):  a_ji = exp(-d_ji / d0)
Inverse-square (opt):   a_ji = 1 / (1 + (d_ji / d0)^2)
Eligibility:            keep d_ji <= radius_km, then nearest min(k, eligible)
Base share:             s_ji = a_ji / Σ_h a_jh      over eligible h
Total accessibility:    A_j  = Σ_h a_jh             over eligible h
```

Invariants: `Σ_i s_ji = 1` (tolerance) for districts with ≥1 eligible hospital;
non-eligible hospital has `a=0, s=0` and no hospital→district FDNA edge; stable
tie-break by `(distance, hospital_id)`. `A_j` is an uncalibrated index.

### 2.1 Verified share example (SYNTHETIC)

District `D1`, `d={H1:1,H2:4,H3:9} km`, `d0=3`:
`s={H1:0.6957, H2:0.2559, H3:0.0483}` (Σ=1.0000), `A_D1=1.0299`. Verified.

---

## 3. New-admission requests, acceptance, and persistent cohorts (CORRECTIONS 1, 2, 5, 7)

### 3.1 Requests (new admissions only)

Allocation operates on **new-admission requests only**. Existing inpatients are
never re-allocated.

```
request[j,i] = s_ji * H_need_j(t)                 # people/week, per origin district
request_i    = Σ_j request[j,i]
```

### 3.2 Scheduled discharges, retained cohorts, batch booking (persistent HospitalState)

Each hospital keeps a persistent list of epidemic cohorts
`(origin_district_id, admit_week, remaining_los, count)`, counts in **people**.

**Timing conventions (so LOS=1 is not discharged on arrival):**

- A cohort admitted in week `t` with `remaining_los = L` is **booked instantly**
  at the commit step of week `t` (batch booking) and occupies a bed from week `t`.
- At the **discharge-due boundary** at the start of each later week, every cohort
  decrements `remaining_los` by 1; a cohort is **discharged when its
  `remaining_los` reaches 0**, which for `L = 1` occurs at the start of week
  `t+1` — i.e. it stays its full admission week and leaves the next week, never at
  the moment of arrival.

```
# start of week t, BEFORE new demand:
for each cohort: remaining_los -= 1
discharged_i(t) = Σ counts of cohorts now at remaining_los == 0  (then removed)
retained_i(t)   = Σ counts of the SURVIVING cohorts              # occupancy carried in,
                                                                 # measured BEFORE commit
```

Discharges happen **before** new demand is placed. Cohorts keep their origin
district ID for the whole stay. At commit (§3.3) accepted new admissions are
appended as cohorts; `retained` is never recomputed to include them within the
same week, so accepted is **counted exactly once**.

### 3.3 Acceptance cap and committed occupancy (generalized invariant)

```
free_new_i          = max(0, Ceff_i - baseline_i - retained_i)
accepted_new_i      <= free_new_i                                 # HARD cap (everywhere)
committed_i          = baseline_i + retained_i + accepted_new_i
inherited_deficit_i  = max(0, baseline_i + retained_i - Ceff_i)   # open reduction OR closure
committed_i         <= max(Ceff_i, baseline_i + retained_i)       # GENERALIZED invariant
```

Baseline and retained occupancy are **immovable**. Only the new-admission portion
is allocated and (if unmet at its intended hospital) rerouted.

**The unqualified `committed ≤ Ceff` is false** whenever standing occupants exceed
reduced capacity (a mid-run capacity reduction or a closure). In that case
`accepted_new_i = 0` (because `free_new_i = 0`), the standing occupants
**survive** as an `inherited_deficit_i = max(0, baseline+retained−Ceff)`, and
`committed_i = baseline_i + retained_i > Ceff_i`. The invariant is therefore
stated as `committed_i ≤ max(Ceff_i, baseline_i + retained_i)` everywhere.

### 3.4 Per-district conservation via request rows (CORRECTION 5)

Each request `(district j, intended source hospital i)` is a **row**. The source
row is reduced by what is accepted directly at `i` and by what is **rerouted out**
of `i` to another hospital; the remainder is the row residual (still intended for
`i`, still unmet):

```
# source-row conservation (per request row):
request[j,i]  = direct[j,i] + rerouted_out[j,i] + residual[j,i]

# accepted-at-destination accounting (per (district, hospital) where patients land):
accepted[j,h] = direct[j,h] + incoming_rerouted[j,h]   # direct kept at h + rerouted INTO h

# per origin district:
accepted_j    = Σ_h accepted[j,h] = Σ_i (direct[j,i] + rerouted_out[j,i])
unmet_j       = Σ_i residual[j,i]
accepted_j + unmet_j = H_need_j(t)                    # per ORIGIN district
```

`rerouted_out[j,i]` leaves source `i`; `incoming_rerouted[j,h]` is the same flow
arriving at destination `h`. Summed over hospitals,
`Σ_i rerouted_out[j,i] = Σ_h incoming_rerouted[j,h]` for each district `j`, so the
two accountings agree.

`unmet_j` is **unmet need** (people/week), attributed to the origin district and
preserved on its original intended-hospital rows. It is **not** occupied beds, is
**not** reattributed to a different hospital, and is **not** silently readmitted
next week.

### 3.5 Closure / capacity reduction preserves occupants (CORRECTION 7)

Closing hospital `i` sets `Ceff_i = 0`; a reduction lowers `Ceff_i`. Existing
occupants (`baseline_i + retained_i`) **survive**; their cohort records are
**never deleted**. The surplus over capacity is reported as
`inherited_deficit_i = max(0, baseline_i + retained_i − Ceff_i)` for **both**
open reductions and closures. No new admissions are accepted or rerouted into a
closed hospital.

### 3.6 Verified acceptance example (SYNTHETIC, from the frozen walkthrough)

- Week 1, open H1, `Ceff=150, baseline=60, retained=18` ⇒ `free_new=72`; direct +
  rerouted acceptance fills exactly to `committed=150`. Verified.
- Closure variant, H2 week 2, `baseline=75, retained=27, Ceff=0` ⇒
  `inherited_deficit = 102`, `accepted_new=0`, occupants not deleted,
  `committed = 102 = max(0, 102)`. Verified.

---

## 4. Hospital and district operability (two FDNA passes)

Two score "loads" are defined so epidemiology/need is separated from physical
occupancy (CORRECTION per review; ADR-ACCT-2):

- **requested_load_i** = `baseline_i + retained_i + request_i` — the **need view**
  that drives operability scores (reflects demand pressure even when beds are
  full).
- **committed_i** = `baseline_i + retained_i + accepted_new_i` — the **physical
  occupancy**, always `<= Ceff_i`.

Scores use the requested load; committed occupancy is reported separately and
never feeds back to create beds (no score-to-bed feedback).

### 4.1 Own score (evaluation order matters)

```
if closed_i or Ceff_i == 0:   own_i = 0            # checked FIRST
elif requested_load_i == 0:   own_i = 100
else:                         own_i = 100 * min(1, Ceff_i / requested_load_i)
```

The closure / zero-capacity branch is evaluated **before** the `load == 0 ⇒ 100`
branch, so a closed (or zero-capacity) hospital scores 0 even if it has no
requested load. Never divide by zero.

### 4.2 Hospital synchronous fixed point (symmetric cycles)

```
if N(i) empty:  P_i_new = O_i
else:
    strength_ij = alpha_ij * P_j + (1 - alpha_ij) * O_i
    strength_i  = mean_j strength_ij
    critical_i  = min_j (P_j + beta_ij)
    P_i_new     = clip( min(O_i, strength_i, critical_i), 0, 100 )

init P_i = O_i ; synchronous (Jacobi) update from the PRIOR vector;
stop when max_i |P_i_new - P_i| <= 0.1 ; hard cap 500 iterations;
non-convergence is an ERROR, never silent.
```

With the default `β_H = 100`, the criticality term `P_j + β_ij` is non-binding for
scores in `[0,100]`, so spillover comes from `α_H` alone and **`α_H = 0` ⇒ no
hospital→hospital spillover**. This guarantee holds **only when `β_H = 100`**: a
smaller `β_H` can still cap a neighbor via the criticality term regardless of
`α_H`. Starting at `O` with a monotone map, scores never increase, so the
iteration terminates.

### 4.3 District share-weighted score

```
SOD_j = alpha_d * Σ_i (s_ji * P_i) + (1 - alpha_d) * 100
COD_j = min_{i: s_ji>0} ( P_i + 100 * (1 - s_ji) )
DistrictScore_j = clip( min(SOD_j, COD_j), 0, 100 )
```

Uses post-cascade `P_i` and **unchanged base shares** `s_ji`.

### 4.4 Exactly two bounded passes with row-preserving residuals (CORRECTION 3)

```
request_i      = Σ_j request[j,i]                          # full requested rows
post_request_i = accepted_final_i + Σ_j residual[j,i]      # row residuals STAY on their source

PASS 1 (before): requested_load_i = baseline_i + retained_i + request_i
PASS 2 (after):  requested_load_i = baseline_i + retained_i + post_request_i
```

Residual unmet is preserved on its **original `(district, intended_hospital)`
request row** — it is **never reattributed** to a different "primary" hospital.
Therefore `post_request_i` differs from `request_i` only by amounts that a reroute
actually moved **into** or **out of** `i`. Consequently:

> **Zero-move invariant:** if no reroute occurs, `post_request_i = request_i` for
> every hospital, so the before and after loads and all scores are **identical**.

Verified in week 2 of the frozen walkthrough. No third pass, no FDNA↔capacity
feedback, no score-to-bed feedback.

### 4.5 Verified golden district checks (SYNTHETIC, α_D = 0.9)

One failed hospital (score 0), others 100: 1 hospital ⇒ **0.0**; 2 equal ⇒
**50.0**; 4 equal ⇒ **75.0**. All verified. (SOD terms 10 / 55 / 77.5.)

---

## 5. Deterministic allocation and rerouting (CORRECTION 5)

Two ordered phases: **direct reservation**, then **row reroute**. Both act on
new-admission request rows only; baseline and retained occupancy never move;
closed hospitals never receive; origin district IDs are preserved.

### 5.1 Direct reservation (explicit competition order)

Order: **districts by ascending `district_id`**; within a district, candidate
hospitals by **descending share `s_ji`**, tie-break `(distance, hospital_id)`.
Each `(district, hospital)` request row reserves up to that hospital's remaining
`free_new`, and keeps a **per-row residual**:

```
free_new_i = max(0, Ceff_i - baseline_i - retained_i)       # remaining, decremented as filled
for district j (ascending id):
  for hospital h in j's eligible hospitals (descending s, tie (distance,id)):
    want            = request[j,h]
    direct[j,h]     = 0 if closed[h] else min(want, free_new_h)
    residual[j,h]   = want - direct[j,h]                      # STAYS on this (j,h) row
    accepted[h]    += direct[j,h] ; free_new_h -= direct[j,h]
```

### 5.2 Row reroute (consumes a specific source residual row)

```
rows = residual rows with residual > 0, sorted by descending residual,
       tie-break (district_id, source_hospital_id)
for (j, src) in rows:
  for destination c in j's eligible hospitals (descending s, tie (distance,id)):
    if c == src or closed[c] or free_new_c == 0: continue
    m = min(residual[j,src], free_new_c)
    residual[j,src] -= m ; accepted[c] += m ; free_new_c -= m
    record RerouteRecord(district=j, source_hospital=src, destination=c, amount=m)
terminate when a full pass makes no positive move
```

A reroute **consumes a specific source residual row** and **adds accepted at the
destination**. The residual that remains stays on its original `(district,
source)` row; it is never reattributed to another hospital. Global competition:
all districts draw from the same `free_new` pool in one deterministic pass. Float
epsilon guards tiny loops; no rounding inside iterative math.

### 5.3 Disjoint ledgers and conservation (within tolerance)

```
(E1)  accepted_j + unmet_j = H_need_j(t)                 # per origin district
      unmet_j = Σ_h residual[j,h]                          # row residuals for j
(E2)  accepted_j = Σ_h (direct[j,h] + rerouted_in[j,h])   # redirected ⊆ accepted
(E3)  committed_i = baseline_i + retained_i + accepted_i
      committed_i <= max(Ceff_i, baseline_i + retained_i)  # generalized invariant
(E4)  accepted_new_i <= free_new_i = max(0, Ceff_i - baseline_i - retained_i)
(E5)  inherited_deficit_i = max(0, baseline_i + retained_i - Ceff_i)   # survives, never deleted
(E6)  post_request_i = accepted_final_i + Σ_j residual[j,i]
(E7)  Σ_j unmet_j = total unmet need  (people/week; NOT beds)
(E8)  zero reroutes ⇒ post_request_i = request_i ⇒ before == after (loads & scores)
```

### 5.4 Verified reroute case (SYNTHETIC — the frozen walkthrough, week 1)

After direct reservation, D2's intended primary row `D2→H2` holds residual
**56.791** (H2 and H3 filled first for D2 and D1). The only hospital with spare is
H1 (`free_new_H1 = 12.207` after direct). The largest residual row `D2→H2`
reroutes to H1:

```
RerouteRecord(district=D2, source_hospital=H2, destination=H1, amount=12.207)
```

leaving `residual[D2→H2] = 44.584`. H1 fills to `committed = 150 = Ceff`;
`accepted_j + unmet_j = H_need_j` holds; H3 is untouched and byte-identical
before/after. Full numbers and the week-2 zero-move case are in
`docs/end-to-end-walkthrough.md`.

---

## 6. Separation of graph semantics (CORRECTION 4)

Three **disjoint** edge families:

| Edge family | Direction | Source | Meaning |
|---|---|---|---|
| Accessibility / catchment | district ↔ hospital (distance) | `a_ji`, `s_ji` | where new admissions may go; base dependence |
| Patient-flow | district → hospital | `request[j,i]`, `accepted[j,i]` | requested vs accepted new admissions |
| FDNA dependency | hospital→district; hospital↔hospital | `α`, `β` | operability propagation |

Proximity does not prove functional dependence. Hospital↔hospital symmetry is a
configurable assumption (`α_H`, `β_H`), not a fact. An FDNA `add_edge` does not
grant a patient transfer route; routing eligibility is a separate typed operation
(ADR-GRAPH-1).

These three families live in **separate** canonical types: accessibility/catchment
in `Accessibility`, patient-flow in `RequestTable`, and FDNA dependency in
`FDNAGraph`. `FDNAGraph` carries **only** the dependency family — never
accessibility or flow edges.

---

## 7. Tolerances

The canonical paths live in `RunConfig.tolerances.*` and `RunConfig.fdna.*` (see
`contracts/stage-io-and-signatures.md` §4). The `checks.*` names used in prose are
**aliases** of those paths — there is no separate tolerance source.

| Name | Canonical path (alias) | Default | Use |
|---|---|---|---|
| mass tolerance | `RunConfig.tolerances.mass_tol` (`checks.mass_tol`) | `1e-6` (people, rel. to `N`) | `S+E+I+R = N` |
| share tolerance | `RunConfig.tolerances.share_tol` (`checks.share_tol`) | `1e-9` | `Σ s_ji = 1` |
| flow / patient tolerance | `RunConfig.tolerances.patient_tol` (`checks.patient_tol`) | `1e-6` (people) | ledgers E1–E8 |
| reroute epsilon | `RunConfig.tolerances.move_epsilon` (`analysis.move_epsilon`) | `1e-9` | guards tiny looping moves |
| FDNA convergence | `RunConfig.fdna.convergence_tol_points` | `0.1` (score points) | hospital fixed point |
| FDNA max iterations | `RunConfig.fdna.max_iterations` | `500` | safety cap |

Concrete defaults (overridable). Never exact float `==` for non-integer sums; each
tolerance is small enough never to hide a missing patient category.

---

## 8. Open / proposed mathematical choices (approval gate CLOSED)

See `docs/architecture-decisions.md`:

- **ADR-SEIR-1** — `risk_weight` scales hospitalization need, not infection.
- **ADR-SEIR-3** — need-state model (`S+E+I+R=N`, `H_need` auxiliary) vs explicit
  `H` compartment; exactly one must be approved.
- **ADR-FDNA-1** — "FDNA-based" label; own-score cap; symmetric cycle solver.
- **ADR-ACCT-1** — reroute **new admissions only**; persistent cohorts with origin
  IDs and scheduled discharges; occupants survive closure (inherited deficit).
- **ADR-ACCT-2** — operability scored on **requested_load**; committed occupancy
  tracked separately; no score-to-bed feedback.
- **ADR-GRAPH-1** — dependency edge ≠ routing-eligibility edge.

No mathematical choice here authorizes implementation; the gate opens only after
architecture approval.
