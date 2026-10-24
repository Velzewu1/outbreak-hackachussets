# Prompt — WS4 Hospital state, allocation, and scenario developer

> Do not start until the architecture is approved (gate CLOSED).

You are the **HOSPITAL / ALLOCATION / SCENARIO agent**. Own `pipeline/il2.py`,
`pipeline/analysis.py`, `pipeline/injections.py`, the `HospitalState` logic, and
their tests. Do **not** edit `contracts/`, shared files, SEIR/FDNA modules, or the
app. Do **not** import the reference document's daily diversion / ICU feedback.

Read in authority order: `AGENTS.md`, `Addiotional Info 1.txt`,
`docs/mathematical-model.md` (§3, §5), `docs/weekly-state-machine.md`,
`contracts/pipeline-types.md` (`RequestRow`, `HospitalLoad`, `HospitalState`,
`RerouteRecord/Result`), `contracts/entities.md` (discriminated `Injection`),
`contracts/stage-io-and-signatures.md` (`ScenarioInputs`, `WeekSummary`, IL2/
ANALYSIS signatures, batch-booking/discharge-boundary conventions),
`contracts/validation-rules.md` (§3, §4, §6), `docs/end-to-end-walkthrough.md`
(the whole frozen example), then primary plan §5.5, §5.7 and blueprint §10,
§12, §13.

Implement, strictly following the corrected model:

1. **IL2 requests (new admissions only).** `request[j,i] = s_ji · H_need_j` as
   per-`(district,hospital)` **rows**. Requested-load view:
   `requested_load_i = baseline_i + retained_i + request_i`;
   `own_i = 100·min(1, Ceff_i/requested_load_i)`; closed ⇒ 0. Build the FDNA graph
   (disjoint edge families). Apply injections in the documented order.
2. **Persistent `HospitalState`.** Cohorts `(origin_district_id, admit_week,
   remaining_los, count)`. Discharge-due boundary at week start: decrement
   `remaining_los`, discharge cohorts hitting 0 (so a LOS=1 cohort is **not**
   discharged on its arrival week). `retained = Σ survivors measured BEFORE
   commit`; accepted admissions are booked as new cohorts **once** at commit
   (`committed = baseline + Σ cohorts after commit`; never add accepted twice).
   Existing occupants **survive closure/reduction**
   (`inherited_deficit = max(0, baseline+retained−Ceff)`); never delete cohorts.
3. **Direct reservation + row reroute.** `free_new_i = max(0, Ceff−baseline−
   retained)`. Direct order: districts ascending id, candidates descending share,
   tie `(distance,id)`; keep a **per-row residual**. Reroute: residual rows
   (descending residual, tie `(district,source)`) move to a destination with spare
   `free_new`; emit `RerouteRecord(week, district, source_hospital, destination,
   amount)`. Residuals **stay on their source row** — no reattribution. Then
   `post_request_i = accepted_final_i + Σ_j residual[j,i]`.
4. **Accounting.** `accepted_j + unmet_j = H_need_j` per origin district;
   `accepted_new_i <= free_new_i`; `committed_i <= max(Ceff, baseline+retained)`;
   redirected ⊆ accepted; unmet is people/week need, **never beds**, never silently
   readmitted.
5. **Injections.** start-inclusive/end-exclusive, from base config (no
   compounding); `set_share` keeps `Σ=1`; dependency edge ≠ routing edge
   (`add_route_option` is the separate typed op); reject contradictions.

Tests: R-1..R-9, X-1..X-9, I-1..I-6. Must include the **zero-move ⇒ before==after**
test (walkthrough week 2) and the generalized occupancy / inherited-deficit test
(closure variant). Reproduce the frozen walkthrough week-1 reroute
(`D2, H2→H1, 12.207`) and week-1 residual `D2→H2 = 44.584`.

**Hand-off:** WS2 consumes `HospitalLoad`/`FDNAGraph`; WS5 consumes before/after
loads, `RerouteResult`, `HospitalState`, unmet-by-district, inherited deficit.

Report per the definition of done.
