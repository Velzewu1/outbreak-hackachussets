# Implementation checklist (live backlog)

Status of all review items. [x] done, [~] in progress, [ ] todo.

## Engine correctness
- [x] Need-state SEIR (S+E+I+R=N), H_need auxiliary, risk on hospitalization
- [x] SEIR normalized-once-per-week optimization (scale by N), correctness preserved
- [x] Accessibility haversine + radius/k + no-catchment reject + explicit fallback policy
- [x] IL2 new-admission requests, requested-load scores, effective shares honor set_share
- [x] FDNA two passes, synchronous cycles, alpha_h=0 (beta caveat), golden 0/50/75
- [x] ANALYSIS direct reservation + row-preserving global reroute; zero-move identity
- [x] HospitalState immutable (frozen Cohort/HospitalState); discharge/commit build new
- [x] commit_week rejects BEFORE phase
- [x] Inherited deficit (occupants survive closure, never deleted)
- [x] run_id hashes full entity/config/accessibility/initial-state/scenario content
- [x] Invalid week/phase rejected; invariant failures raise (no false diagnostic)
- [x] Deep immutability of result history (state, maps, alloc, cohorts, payload, manifest, diagnostics) + FrozenDict |= blocked
- [x] Duplicate district/hospital/injection ID validation; seeded cohort validation

## Data
- [x] Real MassGIS tracts (POP20, zero-pop excluded) + hospitals (licensed proxy) + crosswalk
- [x] HHS loader: duplicate-key detection, suppression/coverage masking, finite checks
- [x] baseline_fraction sourced from RunConfig (no hidden default)
- [x] No invented population (removed max(pop,1))
- [ ] data/raw/MANIFEST.json with sources/licenses/checksums
- [ ] Offline source allowlist (un-ignore the ~1MB snapshots) so fresh checkout reproduces

## Evaluation
- [x] Facility-level fixed-origin backtest (CCN crosswalk, split-before-mask, 7d persistence)
- [x] MIN_COVERAGE=7 (full weekly-mean support)
- [x] Rolling-origin 1-week forecast, expanding-window train fit, leakage-free by construction
- [x] Scored prediction/observed/persistence rows saved for charts + recompute
- [x] Evaluation exposed via pipeline.api (app does not read artifact directly)
- [ ] run_backtest writes artifacts/evaluation.json with provenance/checksums
- [ ] Leakage perturbation test (future obs change doesn't alter an origin's forecast)

## App (Streamlit)
- [x] Imports only pipeline.api; hero map default-on; map_style=None offline render
- [x] Controls: dataset, R0/d0/alphaD/alphaH/p_H/seed/weeks, events, before/after, fallback checkbox
- [x] Injection validated before append; stale events purged on dataset/weeks change
- [x] Baseline delta same-phase; neutral no-reroute reason; capacity-proxy caption
- [x] Cached export bytes (no engine re-run on interaction)
- [ ] EJ overlay control (disabled with unknown/unavailable explanation)
- [ ] Observed-vs-model-vs-persistence chart w/ per-facility selector, dated rows, source
- [ ] Selected tract detail + access-over-time
- [ ] reroute CSV export button (engine export exists; wire in UI) [done in exports dict]
- [ ] No numeric validation headline unless status verified and pairs>0
- [ ] seed fraction slider format .003 (not 0.00); tooltips show names + actual scores
- [ ] Validation tab via api.evaluation_report()

## Tests
- [x] SEIR, FDNA, walkthrough, injections, runner/api, data/backtest, conservation property
- [ ] Immutability tests (attr assignment + nested cohort/payload/manifest/provenance)
- [ ] commit_week BEFORE-rejection test
- [ ] SEIR normalized-vs-independent + convergence test
- [ ] AppTest controls (week/phase/event/reset/download/fallback)
- [ ] Rolling leakage perturbation test

## Packaging / docs / CI
- [ ] requirements.txt / config.yaml consistency check
- [ ] Ruff check + format clean
- [x] pyproject.toml ruff/pytest config
- [ ] README with setup/run/test commands, sources+crosswalk+limitations, actual results
- [ ] demo-script.md
- [ ] verification report (evidence: files/commands/tests/bench/eval)
- [ ] CI workflow (offline tests + lint + smoke; no publishing)
- [ ] Reconcile stale "gate CLOSED" in active docs; preserve source originals
- [ ] benchmark: output-byte determinism + labeled traced-alloc AND peak RSS
