# End-to-end walkthrough — one frozen, numerically verified two-week example

A single **frozen** numeric trace of **three districts and three hospitals over
two weeks**, exercising every handoff under the corrected **new-admission request**
model with **row-preserving residuals**. Every number was verified with a
transient script (see §7). All values are **SYNTHETIC / ILLUSTRATIVE**, not
observed Boston data.

This is the one canonical example; the math model and contracts reference it and
use no other numbers.

Handoff chain:

```
district SEIR state -> new-admission need (pH * I-exit) -> candidate hospitals ->
provisional requested load -> FDNA before -> direct reservation + row reroute ->
committed admissions -> FDNA after -> scheduled discharges -> next-week state
```

---

## 0. Fixed inputs (SYNTHETIC)

**Districts** (`N`, risk weight `rw`): D1 (10,000, 1.0), D2 (20,000, 1.5),
D3 (15,000, 0.8).

**Hospitals** (`C` staffed, `baseline` occupied count): H1 (150, 60),
H2 (110, 75), H3 (80, 40).

**Distances (km):**

| | H1 | H2 | H3 |
|---|---:|---:|---:|
| D1 | 1 | 4 | 9 |
| D2 | 5 | 2 | 6 |
| D3 | 8 | 7 | 2 |

**Config:** `d0=3`, `radius=10`, `k=5`, `α_D=0.9`, `α_H=0.1`, `β_H=100`,
exponential kernel, `LOS=2 weeks`, `p_H=0.08`. FDNA hospital edge: H1↔H2
(symmetric). H3 isolated.

### 0.1 Accessibility shares (PREP, computed once)

| District | s(H1) | s(H2) | s(H3) | Σ | A_j |
|---|---:|---:|---:|---:|---:|
| D1 | 0.696 | 0.256 | 0.048 | 1.000 | 1.030 |
| D2 | 0.225 | 0.613 | 0.162 | 1.000 | 0.838 |
| D3 | 0.102 | 0.143 | 0.755 | 1.000 | 0.680 |

### 0.2 SEIR fixture (LABELED — not ODE-fitted)

The S/E/I/R states and the weekly `I-exit` and `new_infections` counts are a
**hand-chosen contract fixture** chosen for arithmetic clarity. They are
internally consistent (`S+E+I+R=N`, flows balance) but are **not** claimed to be
the output of an ODE integration. New-admission need is derived as
`H_need_j = p_H · rw_j · I_exit_j`.

Both weeks use the same epidemic fixture: `I_exit = {D1:500, D2:1000, D3:750}`,
`new_infections = {D1:600, D2:1200, D3:900}`, giving

```
H_need = {D1: 0.08*1.0*500 = 40,  D2: 0.08*1.5*1000 = 120,  D3: 0.08*0.8*750 = 48}
```

### 0.3 Validated initial states (SEIR + seeded cohorts)

**Initial SEIR state (start of week 1 / interval 0)** — each row satisfies
`S+E+I+R=N` (validated):

| District | S | E | I | R | Σ = N |
|---|---:|---:|---:|---:|---:|
| D1 | 9,000 | 400 | 500 | 100 | 10,000 |
| D2 | 18,000 | 800 | 1,000 | 200 | 20,000 |
| D3 | 13,500 | 600 | 750 | 150 | 15,000 |

**Seeded prior cohorts (admitted before the first simulated interval,
`admit_week = -1`)** so that interval 0 ("Week 1" in display) has **both** nonzero
scheduled discharges and retained cohorts. All counts nonnegative; each cohort
carries a valid `origin_district_id` and `remaining_los ∈ {1,2}`. `admit_week = -1`
is the sentinel for pre-simulation seeded cohorts (permitted):

| Hospital | cohort (origin, admit_week, remaining_los, count) | Σ count |
|---|---|---:|
| H1 | (D1, −1, 1, 12.0), (D2, −1, 2, 18.0) | 30.0 |
| H2 | (D2, −1, 1, 20.0), (D1, −1, 2, 8.0) | 28.0 |
| H3 | (D3, −1, 1, 10.0), (D3, −1, 2, 6.0) | 16.0 |

These are the validated initial hospital/SEIR states for the seeded fixture; the
runner builds `ValidatedInputs` from them and the initial-state checksum feeds
`run_id` (`contracts/stage-io-and-signatures.md` §7.1).

`remaining_los=1` cohorts (seeded at `admit_week=-1`) reach 0 at the discharge-due
boundary at the start of interval 0 ("Week 1") and discharge then;
`remaining_los=2` cohorts are retained through interval 0 and discharge at the
start of interval 1 ("Week 2"). This matches the batch-booking /
discharge-due-boundary convention in `contracts/stage-io-and-signatures.md` §5
(a cohort is never discharged on the interval it arrives).

**Index convention:** display weeks "1" and "2" below are zero-based interval
indices **0** and **1**. `SEIRState.week` is a **boundary** index (the boundary at
the start/end of an interval), while `RerouteRecord.week` and cohort `admit_week`
are **interval** indices. Thus the week-1 reroute record carries `week = 0`.

---

## 1. WEEK 1

### 1.1 SEIR states (STEP 1/4)

| District | S start | E start | I start | R start | → | S end | E end | I end | R end |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| D1 | 9,000 | 400 | 500 | 100 | | 8,400 | 500 | 500 | 600 |
| D2 | 18,000 | 800 | 1,000 | 200 | | 16,800 | 1,000 | 1,000 | 1,200 |
| D3 | 13,500 | 600 | 750 | 150 | | 12,600 | 750 | 750 | 900 |

`S+E+I+R = N` at start and end (10,000 / 20,000 / 15,000). Event counts:
`new_infections = {600, 1200, 900}`, `I_exit = {500, 1000, 750}`.

### 1.2 Discharges and retained (STEP 3)

| Hospital | discharged | retained_in |
|---|---:|---:|
| H1 | 12.0 | 18.0 |
| H2 | 20.0 | 8.0 |
| H3 | 10.0 | 6.0 |

### 1.3 Need and requests (STEP 4/5)

`H_need = {D1:40, D2:120, D3:48}`. `request[j,i] = s_ji · H_need_j`, summed:
`request_i = {H1:59.793, H2:90.637, H3:57.570}`.

### 1.4 BEFORE requested load and FDNA pass 1 (STEP 5/6)

`requested_load_i = baseline + retained + request_i`:

| Hospital | requested_load | own (before) | FDNA P (before) |
|---|---:|---:|---:|
| H1 | 137.793 | 100.000 | 96.335 |
| H2 | 173.637 | 63.351 | 63.351 |
| H3 | 103.570 | 77.242 | 77.242 |

District scores (before): **D1 88.273, D2 75.729, D3 79.491**.

### 1.5 Direct reservation — explicit order (STEP 7a)

Deterministic order: **districts by ascending id**; within a district, candidate
hospitals by **descending share**, tie-break `(distance, hospital_id)`. Each
`(district, hospital)` request row reserves up to that hospital's remaining
`free_new = max(0, Ceff − baseline − retained)`:

`free_new` start = H1 72, H2 27, H3 34.

| Request row | requested | direct accepted | row residual |
|---|---:|---:|---:|
| D1→H1 | 27.829 | 27.829 | 0 |
| D1→H2 | 10.238 | 10.238 | 0 |
| D1→H3 | 1.934 | 1.934 | 0 |
| D2→H2 | 73.553 | 16.762 | **56.791** |
| D2→H1 | 27.059 | 27.059 | 0 |
| D2→H3 | 19.388 | 19.388 | 0 |
| D3→H3 | 36.248 | 12.678 | 23.570 |
| D3→H1 | 4.906 | 4.906 | 0 |
| D3→H2 | 6.846 | 0 | 6.846 |

After direct reservation, **D2's total residual = 56.791** (all on its intended
primary row D2→H2, since H2 filled first for D2). D3 residual = 30.416
(23.570 on D3→H3 + 6.846 on D3→H2). D1 residual = 0.

### 1.6 Row reroute (STEP 7b)

Residual rows are offered to **other** eligible hospitals with remaining
`free_new`. After direct reservation only H1 has spare (`free_new_H1 = 72 − 27.829
− 27.059 − 4.906 = 12.207`). Residual rows are processed by descending residual:
the largest is **D2→H2 (56.791)**, which reroutes to H1:

```
RerouteRecord: week=0, district=D2, source_hospital=H2, destination=H1, amount=12.207
```

This consumes H1's last spare. D2→H2 residual drops **56.791 → 44.584**. No other
destination has spare, so D3's residual rows cannot move.

**AllocationSnapshot BEFORE vs AFTER (phase comparison):** the `before` snapshot is
the provisional direct reservation (no commit); the `after` snapshot has redirects
applied and is the only one that commits.

| phase | unmet D1 | unmet D2 | unmet D3 | total unmet | redirected |
|---|---:|---:|---:|---:|---:|
| **before** (direct only) | 0 | 56.790623715 | 30.41636406 | **87.206987775** | 0 |
| **after** (final) | 0 | 44.58363594 | 30.41636406 | **75.0** | **12.206987775** |

(The rounded `56.791 / 44.584 / 12.207` used above are these full-precision
values.)

### 1.7 Committed occupancy and residual rows FINAL (STEP 9)

`accepted_final = {H1:72, H2:27, H3:34}` (each at `free_new` cap).
`committed = baseline + retained + accepted = {H1:150, H2:110, H3:80}` (all `=
Ceff`). Final residual rows: D2→H2 44.584, D3→H2 6.846, D3→H3 23.570.

Unmet need by origin district (sum of that district's residual rows):
**D1 0, D2 44.584, D3 30.416**. `accepted_j + unmet_j = H_need_j` holds.

### 1.8 AFTER requested load and FDNA pass 2 (STEP 8/10)

`post_request_i = accepted_final_i + Σ residual rows still intended for i`:

- H1: 72 + 0 = 72
- H2: 27 + (D2→H2 44.584 + D3→H2 6.846) = 78.430
- H3: 34 + (D3→H3 23.570) = 57.570

`requested_load_after = baseline + retained + post_request`:

| Hospital | requested_load (after) | own (after) | FDNA P (after) |
|---|---:|---:|---:|
| H1 | 150.000 | 100.000 | 96.814 |
| H2 | 161.430 | 68.141 | 68.141 |
| H3 | 103.570 | 77.242 | 77.242 |

District scores: **D1 89.676, D2 78.469, D3 80.150**.

Only H1 and H2 change (H1 absorbed the rerouted row; H2 shed 12.207). **H3 is
byte-identical before/after** because no row touched it — residuals stay on their
own rows, never reattributed. (Contrast: week 2 below, with zero moves, is
identical before/after everywhere.)

### 1.9 Cohorts committed (origin IDs preserved, LOS=2)

Direct + rerouted accepted admissions become cohorts with `admit_week=0` (interval
0) and `remaining_los=2`, e.g. H1 gains (D1,0,2,27.829), (D2,0,2,27.059),
(D3,0,2,4.906), and the rerouted (D2,0,2,12.207). These are retained into interval
1 ("Week 2").

---

## 2. WEEK 2

### 2.1 SEIR states

| District | S start | E start | I start | R start | → | S end | E end | I end | R end |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| D1 | 8,400 | 500 | 500 | 600 | | 7,800 | 600 | 500 | 1,100 |
| D2 | 16,800 | 1,000 | 1,000 | 1,200 | | 15,600 | 1,200 | 1,000 | 2,200 |
| D3 | 12,600 | 750 | 750 | 900 | | 11,700 | 900 | 750 | 1,650 |

`S+E+I+R=N` holds. `H_need = {40, 120, 48}` again.

### 2.2 Discharges and retained

Week-0 LOS-2 cohorts discharge now; week-1 LOS-2 cohorts are retained:

| Hospital | discharged | retained_in |
|---|---:|---:|
| H1 | 18.0 | 72.0 |
| H2 | 8.0 | 27.0 |
| H3 | 6.0 | 34.0 |

### 2.3 BEFORE load and FDNA pass 1

`requested_load = baseline + retained + request_i`:

| Hospital | requested_load | own (before) | FDNA P (before) |
|---|---:|---:|---:|
| H1 | 191.793 | 78.209 | 76.099 |
| H2 | 192.637 | 57.102 | 57.102 |
| H3 | 131.570 | 60.804 | 60.804 |

District scores (before): **D1 73.448, D2 65.785, D3 65.655**.

### 2.4 Direct reservation, reroute, commit

`free_new = max(0, Ceff − baseline − retained)` = H1 18, H2 8, H3 6 — small,
because retained cohorts fill most beds. Direct reservation accepts only
`{H1:18, H2:8, H3:6}`; every hospital's `free_new` is exhausted, so **no reroute
is possible (zero moves)**.

- `accepted_final = {H1:18, H2:8, H3:6}`, `committed = {H1:150, H2:110, H3:80}`
  (all `= Ceff`).
- unmet need: **D1 12.066, D2 115.934, D3 48.0**;
  `accepted_j + unmet_j = H_need_j` holds.

### 2.5 AFTER — identical to BEFORE (zero-move invariant)

With zero reroutes, every residual row stays on its intended source hospital, so
`post_request_i = request_i` and:

| Hospital | requested_load (after) | own (after) | FDNA P (after) |
|---|---:|---:|---:|
| H1 | 191.793 | 78.209 | 76.099 |
| H2 | 192.637 | 57.102 | 57.102 |
| H3 | 131.570 | 60.804 | 60.804 |

District scores (after): **D1 73.448, D2 65.785, D3 65.655** — **identical** to
before. This is the required invariant: **zero moves ⇒ identical before/after
loads and scores**, verified exactly by the script.

---

## 3. Conservation summary (verified both weeks)

| Check | Week 1 | Week 2 |
|---|---|---|
| `S+E+I+R=N` per district | holds | holds |
| `Σ_i s_ji = 1` | holds | holds |
| `accepted_j + unmet_j = H_need_j` | holds | holds |
| `accepted_new_i ≤ max(0, Ceff−baseline−retained)` | holds | holds |
| `committed_i ≤ max(Ceff, baseline+retained)` | holds (=Ceff) | holds (=Ceff) |
| inherited_deficit `= max(0, baseline+retained−Ceff)` | 0 (all) | 0 (all) |
| redirected ⊆ accepted | 12.207 ⊆ 72 (H1) | n/a |
| zero moves ⇒ before==after | n/a (1 move) | **holds** |
| no negative occupancy | holds | holds |

No duplicated admissions, no negative occupancy, no capacity violations for
accepted patients, no ambiguous graph-edge semantics.

---

## 4. Closure / capacity-reduction variant — inherited deficit (SYNTHETIC)

If instead H2 is **closed in week 2** (`Ceff_H2=0`) or reduced below its standing
occupancy, the generalized invariant applies:

```
inherited_deficit_i = max(0, baseline_i + retained_i - Ceff_i)
```

For closed H2 in week 2: `baseline 75 + retained 27 = 102` occupants who
**survive**; `Ceff=0` ⇒ `inherited_deficit = 102`, `accepted_H2 = 0`,
`own_H2 = 0`. Cohort records are **not deleted**. The same formula covers a
partial reduction (e.g. `Ceff=90` ⇒ `inherited_deficit = max(0,102−90)=12`). This
is why the occupancy invariant is stated as `committed ≤ max(Ceff,
baseline+retained)` and never the unqualified `committed ≤ Ceff`.

---

## 5. RerouteRecord shape (from this example)

```
RerouteRecord { week:0, district:"D2", source_hospital:"H2",
                destination:"H1", amount:12.207 }   // week 0 = display "Week 1"
```

A reroute always names the origin district, the intended source hospital (whose
residual row it consumes), and the destination. See `contracts/`.

---

## 6. Canonical type at each handoff

| Handoff | Producer → consumer | Canonical type |
|---|---|---|
| epidemic state → need | SEIR → IL2 | `SEIRWeekOutput` (`H_need_j`, `S,E,I,R`) |
| need → candidates | IL2 | `Accessibility` (`s_ji`) |
| requests → provisional load | IL2 | `HospitalLoad`, `RequestRow` |
| load → FDNA before | FDNA | `FDNAResult` |
| direct + reroute | ANALYSIS | `AllocationSnapshot` (before/after), `RerouteRecord` |
| committed admissions | hospital state | `HospitalState` |
| load → FDNA after | FDNA | `FDNAResult` |
| discharges → next state | IL3 | `SEIRState`, `WeekResult` |

---

## 7. How these numbers were verified

Computed with a **transient Python script run in the shell** (no project code
added, nothing committed). The script:

1. built shares `exp(-d/3)`, radius 10, k=5;
2. used the labeled SEIR fixture to produce `S/E/I/R` and
   `H_need = p_H · rw · I_exit`;
3. applied scheduled discharges to seeded cohorts, computed `retained`,
   `free_new`;
4. ran direct reservation (districts by id, candidates by descending share),
   keeping a **per-row residual** `residual[(district,hospital)]`;
5. ran the row reroute consuming specific residual rows into destinations with
   spare `free_new`, recording `(district, source, destination, amount)`;
6. computed `post_request_i = accepted_final_i + Σ residual rows intended for i`,
   then requested-load own scores, the synchronous hospital FDNA fixed point, and
   share-weighted district scores for both passes;
7. asserted every equation in §3 — including the **zero-move ⇒ before==after**
   invariant and the generalized occupancy invariant — raising on any failure.

All assertions passed. The script independently reproduced the FDNA golden checks
(1/2/4 equal hospitals → 0/50/75). It is intentionally **not** part of the
repository; reproduce it from `docs/mathematical-model.md`. No real data, APIs, or
network calls were used, and no ODE integration is claimed — the SEIR numbers are
a labeled fixture.
