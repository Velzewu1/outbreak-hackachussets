# Architecture

Authoritative execution pipeline and module responsibilities for the DS+X weekly
epidemic → hospital dependency → rerouting → access simulator (*ResiliNet |
Boston Hospital Cascade*). This is the top-level architecture document referenced
by `Addiotional Info 1.txt`.

Reading order: this file → `docs/mathematical-model.md` →
`docs/weekly-state-machine.md` → `contracts/` → `docs/integration-plan.md`.
Decisions and open items: `docs/architecture-decisions.md`. Agent rules:
`AGENTS.md`.

**Status update (2026-10-24): the implementation approval gate is OPEN.** The
user approved the architecture and default proposals; the engine, data loaders,
validation, tests, benchmarks, and Streamlit app are now implemented under
`pipeline/`, `validation/`, `app/`, `tests/`, and `scripts/`. The phrases below
and in the other design docs that say the gate is "CLOSED" describe the original
documentation phase and are retained for history; see
`docs/architecture-decisions.md` (header) and `AGENTS.md` §2 for the current OPEN
status. No commit/push/deploy is authorized.

---

## 1. Scope (fixed, from the mandatory corrections)

- Weekly nine-block Python/Streamlit pipeline. **No** daily ICU/diversion/
  mortality-feedback architecture, **no** React/FastAPI, **no** LLM layer
  (correction 9).
- Allocation and rerouting operate on **new admissions only**; existing
  inpatients are persistent cohorts (corrections 1, 2).
- Unmet demand is **unmet need** (people/week), never occupied beds; SEIR
  `S+E+I+R=N` with `H_need` auxiliary (corrections 6 and the blocking review).
- Exactly two bounded FDNA passes; no feedback loops (correction 3).
- Three disjoint graph edge families (correction 4).

---

## 2. The nine blocks

```
 DATA ──> SEPARATE ──> IL1 ──> SEIR ──> IL2 ──> FDNA ──> ANALYSIS ──> IL3 ──> RESULTS
                        ^                 ^                   |          |
                        |                 └── injections ─────┘          |
                        └───────────── next week's SEIR state ───────────┘
```

| # | Block | Job | In | Out (canonical type) |
|---|---|---|---|---|
| 1 | DATA | load + validate raw sources | files | `RawBundle`, `DataDiagnostics` |
| 2 | SEPARATE | build node tables | raw | `DistrictTable`, `HospitalTable` |
| 3 | IL1 | prepare / carry SEIR state | districts, disease cfg, prev state | `SEIRState` |
| 4 | SEIR | one week of epidemic | `SEIRState` | `SEIRWeekOutput` (`H_need_j`, `S,E,I,R`) |
| 5 | IL2 | requests, loads, graph, injections | `SEIRWeekOutput`, hospitals, `Accessibility`, injections | `RequestTable`, `HospitalLoad`, `FDNAGraph`, `ScenarioInputs` |
| 6 | FDNA | operability propagation (2 passes) | `HospitalLoad`, `FDNAGraph` | `FDNAResult` (before/after) |
| 7 | ANALYSIS | accept + global reroute + accounting | requests, caps, shares, eligibility | `RerouteResult`, `WeekSummary` |
| 8 | IL3 | package results, next state | all above | `WeekResult`, next `SEIRState` |
| 9 | RESULTS | Streamlit map/charts/validation | `RunResult` | UI view models |

One pipeline iteration = **one week**. SEIR may use 7 daily substeps internally;
all external quantities are weekly.

---

## 3. Composition root and module boundaries

A single pure orchestration function
`simulate_run(config, data_bundle, injection_list) -> RunResult` in
`pipeline/runner.py` is the only place that wires all modules. The Streamlit app
imports the public facade `pipeline/api.py` **only** — never internal `seir`,
`fdna`, or `analysis` modules.

Dependency rules (enforced by review and an import test):

- `pipeline/contracts.py`, `pipeline/config.py`: types, validation, errors only.
  No Streamlit, no stage imports.
- Stages import contracts/config and math helpers. No stage opens raw files
  except DATA/SEPARATE. No stage imports Streamlit.
- `validation/` calls the public API and documented observables only; it never
  monkey-patches internal state.
- `app/` calls `pipeline.api` only; presentation transforms only. A UI callback
  never implements FDNA/SEIR/rerouting math.
- No global mutable model object; no SEIR solver or patient flow reused across
  scenarios (scenario isolation, correction 7).

---

## 4. Module responsibilities and ownership

Shared files (one owner, no concurrent edits): `config.yaml`,
`pipeline/{contracts,config,runner,api,il3}.py`, `.kiro/steering/*`, `README.md`,
dependency pins. Owned by the Orchestration/Integration workstream (WS5).

| Module | Responsibility | Owning workstream |
|---|---|---|
| `pipeline/data.py`, `pipeline/separate.py` | ingest, clean, crosswalk, provenance | WS3 Data/Accessibility/Eval |
| `pipeline/il1.py`, `pipeline/seir.py`, `validation/fit.py` | SEIR+H need model, Option A, fit | WS1 SEIR |
| `pipeline/accessibility.py` | distances, kernels, shares, `A_j` | WS3 |
| `pipeline/il2.py` | requests, requested-load, own scores, graph, injections | WS4 Hospital/Allocation/Scenario |
| `pipeline/fdna.py` | hospital fixed point, district score (2 passes) | WS2 FDNA |
| `pipeline/analysis.py` | accept + global reroute + disjoint ledgers | WS4 |
| `pipeline/injections.py` | injection lifecycle (start-inclusive/end-exclusive) | WS4 |
| `pipeline/il3.py`, `pipeline/runner.py`, `pipeline/api.py` | packaging, week loop, facade | WS5 |
| `validation/backtest.py`, `metrics.py`, `prepare_observed.py` | holdout MAE vs persistence | WS3 |
| `app/*` | Streamlit UI over `pipeline.api` | WS5 (frontend) |

The five workstreams map to the team roles in `Addiotional Info 1.txt`:
1 SEIR, 2 FDNA, 3 Data/accessibility/evaluation, 4 Hospital state/allocation/
scenario, 5 Orchestration/Streamlit/integration. See `docs/agent-prompts/`.

> **Note on SEIR/FDNA existing code.** SEIR and FDNA implementations may exist
> elsewhere. Those workstreams adapt to the frozen contracts in `contracts/`; the
> shared interfaces are **not** redesigned around inaccessible code.

---

## 5. HospitalState and the two score views

`HospitalState` (persistent across weeks) holds `baseline` plus a list of epidemic
cohorts `(origin_district_id, admit_week, remaining_los, count)`. Two derived
quantities are kept strictly separate:

- **requested_load** = `baseline + retained + requests` — drives operability
  scores (epidemiology / need view).
- **committed occupancy** = `baseline + retained + accepted` — physical beds,
  `≤ max(Ceff, baseline + retained)`. It equals `Ceff` when not over-occupied and
  equals `baseline + retained` when a reduction/closure leaves an
  `inherited_deficit = max(0, baseline + retained − Ceff)`. Only this is "occupied
  beds"; unmet need is never beds.

Scores never change physical beds (no score-to-bed feedback). Full semantics in
`docs/weekly-state-machine.md` and `docs/mathematical-model.md`.

---

## 6. Repository layout (proposed, for after approval)

```
repo/
  README.md
  architecture.md                     <- this file
  AGENTS.md
  config.yaml
  contracts/                          <- canonical typed interface SPECIFICATIONS (docs)
  docs/
    DSX_Kiro_Master_Implementation_Blueprint.md
    source/DSX-project-plan.md
    source/reference-architecture.md
    mathematical-model.md
    weekly-state-machine.md
    architecture-decisions.md
    integration-plan.md
    end-to-end-walkthrough.md
    documentation-audit.md
    agent-prompts/
  pipeline/   (data, separate, il1, seir, accessibility, il2, fdna,
               analysis, injections, il3, runner, api, contracts, config)   [post-approval]
  validation/ (prepare_observed, fit, backtest, metrics)                     [post-approval]
  app/        (streamlit_app, components, map_view, view_models, styles)      [post-approval]
  tests/      (mirrors pipeline; golden fixtures)                             [post-approval]
```

Only the documentation directories (`contracts/`, `docs/`, this file, `AGENTS.md`)
are created now. `pipeline/`, `validation/`, `app/`, `tests/` are created **after**
architecture approval.

---

## 7. Data mode and honesty

`RunResult.data_mode` distinguishes `historical_data`, `mixed_assumptions`,
`synthetic_demo`. Synthetic recovery experiments are **not** external validation
(correction 8). Historical backtests are optional and reported only after actual
computation. Every assumption is a named config field with units and a provenance
label.

---

## 8. What this architecture deliberately excludes (v1)

Daily age-stratified SEIR; ICU/ward/EMS/oxygen resource nodes; mortality feedback;
formal ambulance diversion hysteresis; volume-over-capacity placement; DAG-only
FDNA; capacity-weighted gravity shares; React/FastAPI; LLM layers. These are
future work behind new interfaces, not the v1 contract (corrections 4, 9;
blueprint §2.3, §25).
