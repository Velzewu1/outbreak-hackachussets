# Tasks: epidemic hospital dependency MVP

> **Reconciliation notice (authoritative).** These tasks are **not active**: the
> implementation approval gate is **CLOSED** (see `AGENTS.md`). No production
> modules or tests are built until the reconciled architecture
> (`architecture.md` + `docs/` + `contracts/`) is approved. When approved, the
> authorized delegation briefs are in `docs/agent-prompts/`, not this list. The
> "SEIR+H / S,E,I,R,H" and standing-census wording below is superseded by the
> need-state + new-admission-request model.

- [ ] 1. Bootstrap the Python project
  - Create pinned `requirements.txt`, `config.yaml`, package markers, and minimal Streamlit entry point.
  - Configure pytest and Ruff; document setup and commands.
  - Verify a clean local environment can run tests and start the app.

- [ ] 2. Define contracts and configuration validation
  - Implement typed configuration and result containers from `docs/project-brief.md`.
  - Add schema, unit, range, ID, and configuration checks.
  - Add tests for valid and invalid boundaries.

- [ ] 3. Build DATA and SEPARATE layers
  - Implement source-specific fetch/load functions without making runtime depend on live APIs.
  - Create a reviewable hospital-name mapping table and matching report.
  - Produce validated district and hospital clean tables with provenance metadata.

- [ ] 4. Implement IL1 and weekly SEIR+H
  - Prepare per-district starting states from configuration and prior results.
  - Implement a one-week solver with admissions and diagnostics.
  - Test conservation, nonnegativity, deterministic output, and edge cases.

- [ ] 5. Implement accessibility, patient allocation, and hospital load in IL2
  - Compute projected distances, eligible hospitals, accessibility, shares, and flows.
  - Implement the documented empty-candidate behavior and operability mapping.
  - Test share sums, patient conservation, capacity bounds, and monotonicity.

- [ ] 6. Implement graph construction and FDNA propagation
  - Create hospital-to-district and hospital-to-hospital edges.
  - Verify the formula against a primary source and record the citation.
  - Implement the fixed-point solver with convergence diagnostics and tests.

- [ ] 7. Implement rerouting and scenario injections
  - Support closures, capacity changes, and link changes as structured injections.
  - Reroute partial loads without exceeding destination capacity.
  - Report before/after scores, transfers, unmet demand, and affected districts.

- [ ] 8. Implement IL3 and multi-week execution
  - Package complete `WeekResult` objects and construct the next state.
  - Run multiple deterministic weeks and retain checks and provenance.
  - Add an end-to-end synthetic integration test.

- [ ] 9. Build the Streamlit demo
  - Add one clear map, a compact scenario control set, before/after comparison, load charts, and assumptions/limits.
  - Keep UI code separate from scientific modules.
  - Add an offline startup smoke test.

- [ ] 10. Add historical validation
  - Confirm availability and licensing of facility occupancy data before integration.
  - Define the calibration/evaluation split and naive baseline.
  - Report matching coverage, held-out date range, sample size, and the same metric for model and baseline.

- [ ] 11. Finalize reproducibility and submission assets
  - Verify setup from a fresh environment and no-network demo behavior.
  - Update the README with sources, assumptions, results, app, deck, and video links.
  - Run tests, lint, formatting, and the demo smoke test; record known limitations.
