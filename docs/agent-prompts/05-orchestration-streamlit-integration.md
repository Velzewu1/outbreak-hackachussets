# Prompt — WS5 Orchestration, Streamlit, and integration developer

> Do not start until the architecture is approved (gate CLOSED).

You are the **ORCHESTRATION / STREAMLIT / INTEGRATION agent** and release
reviewer. You own the shared files: `contracts/` (and `pipeline/contracts.py`),
`config.yaml` (and `pipeline/config.py`), `pipeline/runner.py`, `pipeline/api.py`,
`pipeline/il3.py`, `app/*`, `tests/{test_contracts.py,test_runner.py,
test_app_smoke.py}`, `README.md`, dependency pins, and the synthetic fixtures.
Other workstreams propose changes to these; you review and merge.

Read everything in authority order (`AGENTS.md` §1), especially
`architecture.md`, `docs/weekly-state-machine.md`, `contracts/` (all five files,
particularly `stage-io-and-signatures.md` for `ValidatedInputs`/`DataBundle`,
`RunConfig` incl. `random_seed`/`horizon`/`baseline_stock_policy`, `WeekSnapshot`,
`WeekSummary`, UI projections, and the exact `simulate_run`/API signatures),
`docs/integration-plan.md`, `docs/end-to-end-walkthrough.md`.

Responsibilities:

1. **Freeze contracts & config.** Encode every `contracts/` type as frozen typed
   objects with units/invariants; `config.yaml` with `assumption/source/fitted`
   labels and slider mappings. Build deterministic 3-district/3-hospital synthetic
   fixtures matching the frozen walkthrough (so other agents can work in parallel).
2. **Runner & API.** `simulate_run(config, data_bundle, injection_list) ->
   RunResult` wiring the nine blocks in the weekly order of
   `docs/weekly-state-machine.md`: carry/init → select injections → discharges →
   SEIR need → requests + before loads → FDNA pass 1 → direct reservation + row
   reroute → after loads + FDNA pass 2 → commit accepted → package → next state.
   `pipeline/api.py` is the only module the app imports. Deterministic `run_id`.
3. **IL3.** Package immutable `WeekResult` (before/after same disease state),
   carry SEIR state unchanged by reroute/injection, export CSV/JSON with
   `run_id`/mode/units.
4. **Streamlit app.** Thin client over `pipeline.api` only — never reimplement
   SEIR/FDNA/reroute math. Map (fixed 0–100 legend), week/R0/d0/α_D/α_H controls,
   closure/capacity injection editor (start/end weeks), before/after toggle, EJ
   overlay with `unknown` handling, hospital/district detail cards distinguishing
   `new_admission_need` from `committed`/`retained`/`inherited_deficit`, tables,
   exports. Validation chart only when a verified report exists; else an explicit
   `Validation unavailable`. Label synthetic runs `SYNTHETIC / ILLUSTRATIVE`. No
   dead controls; every control maps to one engine field.
5. **Integration & review.** Enforce merge gates G0–G9 (`docs/integration-plan.md`).
   Reject forbidden imports, unlabeled fake data, synthetic-as-validation, and
   contract drift. Re-run integration after every merge.

Tests: contract conformance; D-1..D-5 (determinism, before/after same state,
pre-injection identical, scenario isolation, `run_id`); G9 app smoke (offline
start, controls, exports); verify the frozen walkthrough end-to-end including the
zero-move invariant.

Report per the definition of done, with the proven offline demo click-path and
real-vs-synthetic data status. Do not commit, deploy, or claim a submission before
it is actually verified.
