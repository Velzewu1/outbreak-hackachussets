# AGENTS.md — global Kiro agent rules

Rules that apply to **every** Kiro agent working in this repository (the
orchestrator and all five workstream agents). These rules are binding and take
priority over convenience. They implement the mandatory corrections in
`Addiotional Info 1.txt` and the authority order below.

---

## 1. Authority order

1. **`Addiotional Info 1.txt`** — the mandatory corrections. These **override**
   conflicting instructions in the blueprint and both source plans.
2. **`docs/source/DSX-project-plan.md`** — the primary DS+X plan.
3. **`architecture.md`, `docs/mathematical-model.md`,
   `docs/weekly-state-machine.md`, `contracts/`** — the reconciled, authoritative
   specification (these resolve ambiguities; corrections win where they conflict).
4. **`docs/DSX_Kiro_Master_Implementation_Blueprint.md`** — the preferred technical
   starting point, but mathematical consistency and human-approved decisions take
   precedence over reproducing it verbatim.
5. **`docs/source/reference-architecture.md`** — secondary ideas only (typed
   contracts, one composition root, reproducibility, tests). **Never** import its
   daily epidemiology, resource-node FDNA, diversion, or mortality equations.

If two documents conflict, follow the higher authority and record the conflict in
`docs/architecture-decisions.md`.

---

## 2. The implementation approval gate is OPEN (2026-10-24)

- The architecture and default proposals are **APPROVED** (see
  `docs/architecture-decisions.md` header). Full implementation is authorized.
- Implement the APPROVED defaults: need-state SEIR, risk_weight on
  hospitalization, weekly cohort LOS, deterministic allocation priority,
  requested-load FDNA.
- Still prohibited: **commit, push, deploy, external submission, launching other
  agents, or messaging people.** All code is authored through Kiro.

---

## 3. Code authorship

All code placed in this repository must be authored through **Kiro**. Another
assistant may inform or review the specification, but code generation and
repository edits are done by Kiro. All repository edits in this reconciliation
pass were authored through Kiro.

---

## 4. Non-negotiable modeling rules (the corrections)

Every agent must honor these; a change that violates one is rejected in review.

1. **New admissions only.** Allocation and rerouting act on new-admission requests
   (`request[j,i] = s_ji · H_need_j`). Existing inpatients are persistent cohorts;
   never re-allocate them.
2. **Separate the quantities.** Keep incident infections, new-admission need,
   existing occupancy (retained), scheduled discharges, and unmet need distinct.
   `H_need` is a people/week need signal, **never** occupied beds.
3. **Conservation.** `accepted_j + unmet_j = H_need_j` per origin district;
   `committed_i = baseline_i + retained_i + accepted_i`;
   `committed_i ≤ max(Ceff_i, baseline_i + retained_i)` (the generalized
   invariant — an inherited deficit can exceed `Ceff`);
   `accepted_new_i ≤ max(0, Ceff_i − baseline_i − retained_i)`. Redirected
   admissions are a subset of accepted. Unmet is never silently readmitted.
4. **Occupants survive closure.** A closure sets `Ceff=0` but never deletes
   existing cohorts; report them as an inherited deficit.
5. **SEIR mass balance.** `S+E+I+R=N`; `H_need` auxiliary (or the approved explicit
   `H` compartment variant — ADR-SEIR-3). Never call unmet need occupied beds.
6. **Two FDNA passes only.** A pre-reroute pass and a post-reroute pass; no third
   pass, no FDNA↔capacity feedback, no score-to-bed feedback.
7. **Disjoint graph semantics.** Accessibility, patient-flow, and FDNA dependency
   edges are separate. Proximity ≠ dependence. Hospital↔hospital symmetry is a
   configurable assumption. A dependency edge is not a transfer route.
8. **Scenario isolation.** Baseline and intervention runs start from identical
   state and seed; no cross-scenario mutation.
9. **Weekly scope.** Keep the nine-block weekly Python/Streamlit pipeline. No
   daily/ICU/mortality/React/FastAPI/LLM additions in the MVP.
10. **Canonical interfaces.** Every cross-module object has exactly one definition
    in `contracts/`, with units, invariants, serialization, and an owner.

---

## 5. File ownership and prohibited cross-module edits

One owner per shared file; agents submit change proposals rather than editing
another workstream's files.

| Area | Owner (workstream) | Others may… |
|---|---|---|
| `contracts/`, `config.yaml`, `pipeline/{contracts,config,runner,api,il3}.py`, `.kiro/steering/*`, `README.md`, deps | WS5 Orchestration/Integration | propose changes via review |
| `pipeline/{il1,seir}.py`, `validation/fit.py` | WS1 SEIR | not edit |
| `pipeline/fdna.py` | WS2 FDNA | not edit |
| `pipeline/{data,separate,accessibility}.py`, `validation/{prepare_observed,backtest,metrics}.py` | WS3 Data/Accessibility/Eval | not edit |
| `pipeline/{il2,analysis,injections}.py` | WS4 Hospital/Allocation/Scenario | not edit |
| `app/*` | WS5 (frontend) | not edit |

**Prohibited:**

- WS-frontend duplicating SEIR/FDNA/rerouting math in Streamlit, or returning
  unlabeled fake results.
- Any agent importing the reference document's daily resource-node/diversion code
  and calling it authoritative.
- Any agent changing the shared contracts to fit a local preference without a
  reviewed proposal.
- Any agent editing another agent's tests to hide failures.
- Replacing missing real data with guessed Boston-specific numbers.
- Presenting synthetic fixtures or reference illustrative numbers as validated
  metrics.

---

## 6. Evidence and honesty

- Never present synthetic, assumed, fitted, or simulated numbers as observed
  Boston facts. Label synthetic runs `SYNTHETIC / ILLUSTRATIVE`.
- Show real validation (MAE vs persistence) **only when actually computed** on a
  matched historical holdout; otherwise render `Validation unavailable`.
- Every assumption lives in `config.yaml` with units and a provenance label.
- An agent's "done" message lists files changed, commands run, test results,
  fixtures/data used, assumptions introduced, and unresolved blockers.

---

## 7. Definition of "agent done"

Files created/modified; commands run and their actual output; tests passed/failed;
exact fixture or dataset used; scientific assumptions introduced; interface
compatibility; and unresolved blockers. "Implemented" without reproducible
evidence is a draft, not a completion.
