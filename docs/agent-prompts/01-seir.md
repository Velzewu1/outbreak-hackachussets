# Prompt — WS1 SEIR developer

> Do not start until the architecture is approved (gate CLOSED).

You are the **SEIR agent**. Own `pipeline/il1.py`, `pipeline/seir.py`,
`validation/fit.py`, `tests/test_seir.py`, and narrow disease documentation. Do
**not** edit `contracts/`, shared files, or any other workstream's modules.

Read in authority order: `AGENTS.md`, `Addiotional Info 1.txt`,
`docs/mathematical-model.md` (§1), `docs/weekly-state-machine.md`,
`contracts/pipeline-types.md` (`SEIRState`, `SEIRWeekOutput` with `i_exit`/
`e_to_i`), `contracts/stage-io-and-signatures.md` (IL1/SEIR signatures, index
conventions), `contracts/validation-rules.md` (§1),
`docs/end-to-end-walkthrough.md` (§0.2, §1.1, §2.1), then the primary plan
§5.3–5.4 and blueprint §8.

Build the weekly SEIR need model (adapt existing SEIR code to these contracts; do
not redesign the shared interface):

1. **Mass balance `S+E+I+R=N`** (need-state, ADR-SEIR-3). `H` is **not** a
   compartment. `H_need_j = p_H_j · (I-exit over the week)` is an auxiliary
   people/week need signal — **never** occupied beds.
2. **Option A**: one shared normalized `S/E/I/R` curve × population;
   `p_H_j = clip(p_h · risk_weight_j, 0, 1)` (risk scales hospitalization, not
   transmission, ADR-SEIR-1). No between-district coupling.
3. 7 daily substeps allowed internally; export exactly one `SEIRWeekOutput` per
   week. Keep compartments nonnegative within `mass_tol`; record numerical error.
4. Initial state week 0 (`I=seed·N`, `S=N−I`, `E=R=0`); `carry_state` for week
   `t+1` from week `t` `state_end`. Rerouting/injections must **not** change SEIR
   state (no feedback).
5. `validation/fit.py`: least-squares fit of `R0` (and `p_H` only if identifiable)
   on **training** data only, using a model-to-observation operator compatible
   with the target. Never invent a fit; if parameters are unidentifiable, document
   the limit.

Tests (`tests/test_seir.py`): P-1..P-6 from `contracts/validation-rules.md` —
conservation, nonnegativity, seed-0 ⇒ no need, week continuity, risk-weight
affects `H_need` not the shared curve, reroute/injection invariance.

**Hand-off:** WS4 consumes `H_need_j` (people/week) + `S,E,I,R`; WS3 consumes the
fit function; WS5(frontend) consumes the epidemic trend series.

Report (definition of done): files, commands + exact test output, fixtures used,
assumptions introduced, interface compatibility, blockers. "Implemented" without
reproducible tests is a draft.
