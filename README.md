# ResiliNet | Boston Hospital Cascade

A Boston-focused what-if simulator: a weekly district-level **SEIR** epidemic model
produces new-admission demand; distance-based accessibility routes **new admissions
only** to hospitals; an **FDNA-based** dependency network propagates operability
loss to hospitals and neighborhoods; and a capacity-aware **rerouting** step tests
whether spare beds reduce the modeled shortfall. A Streamlit app drives the whole
pipeline through one public API.

**Research simulation — not for emergency planning, triage, or hospital
operations.** Synthetic runs are labeled; the "real" mode uses real Suffolk
geography with a **licensed-bed capacity proxy** and a **simulated** epidemic.

## Quick start

```bash
# Python 3.12
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Run the app (offline; renders polygons/points without external tiles)
.venv/bin/python -m streamlit run app/streamlit_app.py
# -> http://127.0.0.1:8501

# Tests, lint, format
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .

# Offline smoke + frozen-walkthrough verification
PYTHONPATH=. .venv/bin/python scripts/smoke_demo.py
PYTHONPATH=. .venv/bin/python scripts/verify_demo.py

# Benchmark (fixed-seed; wall time + traced-alloc + RSS; determinism by bytes)
PYTHONPATH=. .venv/bin/python scripts/benchmark.py     # -> artifacts/benchmark.json

# Historical backtest (real HHS; writes artifacts/evaluation.json)
PYTHONPATH=. .venv/bin/python scripts/run_backtest.py
```

The app imports only `pipeline.api`. Model calls take ordinary validated inputs
and are cached by content, so runs are reproducible.

## Architecture (weekly nine-block pipeline)

```
DATA -> SEPARATE -> IL1 -> SEIR -> IL2 -> FDNA -> ANALYSIS -> IL3 -> RESULTS
```

- **SEIR (need-state):** one shared normalized S/E/I/R curve (`S+E+I+R=N`, H is
  not a compartment); `H_need = p_H · i_exit` is a people/week need signal, never
  beds. `risk_weight` scales hospitalization need, not transmission. Integrated
  with SciPy; normalized once per week and scaled by population.
- **Accessibility:** `exp(-d/d0)` shares, nearest-k within radius (haversine km).
- **IL2 / allocation:** new-admission **requests only**; existing inpatients are
  persistent retained cohorts (never re-allocated). Operability scored on
  requested load; committed occupancy tracked separately (no score→bed feedback).
- **FDNA:** exactly two bounded passes (before/after reroute); synchronous
  hospital cycles; share-weighted district scores; golden checks 0/50/75.
- **ANALYSIS:** direct reservation then row-preserving global reroute of unmet
  requests; `accepted + unmet = need` per origin district; zero moves ⇒ before ==
  after. Occupants survive closure as an **inherited deficit** (never deleted).

Authoritative specs: `architecture.md`, `AGENTS.md`, `docs/mathematical-model.md`,
`docs/weekly-state-machine.md`, `contracts/`, `docs/end-to-end-walkthrough.md`.

## Data sources, crosswalk, and limitations

Offline snapshots live in `data/raw/` with provenance/licenses/checksums in
`data/raw/MANIFEST.json` (allowlisted so a fresh checkout reproduces the real demo).

- **Hospitals:** MassGIS Suffolk acute-care facilities (WGS84 coords,
  `DPH_FACILITY_ID`, bed breakdown). 9 general **adult acute** hospitals are
  included; pediatric-only (Boston Children's, Shriners', Franciscan), specialty
  (Mass Eye & Ear, Dana-Farber + its unit), non-acute/rehab/psych (Hebrew Rehab,
  Spaulding, Lemuel Shattuck), a zero-bed satellite ED, and historically-closed
  Carney are excluded with documented reasons (`pipeline/data_real.py`).
  **Capacity is a licensed-bed PROXY, not verified staffed beds** → `mixed_assumptions`.
- **Districts:** MassGIS Census-2020 Suffolk tracts (`POP20`, **decennial**, not
  ACS). 4 zero-population tracts are excluded from modeling (geometry preserved).
  One NE-Suffolk peninsula tract is >10 km from any included hospital; the
  **explicit, disclosed nearest-outside-radius fallback** assigns it its nearest
  hospital rather than dropping it.
- **Historical validation:** HHS facility COVID occupied beds (weekly means),
  2020-10-04 .. 2021-05-30, via the audited CCN crosswalk (BIDMC E+W → 220086).

**Measured validation result (honest):** both the fixed-origin and rolling-origin
one-week-ahead facility backtests have **higher MAE than the naive persistence
baseline** — the model loses. We report it as measured; see
`artifacts/evaluation.json` and `docs/verification-report.md`. No tuning to the
holdout; a simple shared-curve SEIR does not beat "next week = this week" here.

### Limitations

Suffolk is not a closed catchment; proximity ≠ real referral/transfer; Option A has
no neighborhood transmission wave; beds alone oversimplify capacity; unmet is a
modeled capacity gap (not deaths); FDNA weights are assumptions; no behavioral
feedback; HHS target is a weekly mean compared via a declared weekly-batch operator.

## Guardrails

Public aggregate data only; never patient-level. Assumptions are named config
fields with provenance. Synthetic runs labeled `SYNTHETIC / ILLUSTRATIVE`. All
code authored through Kiro.
