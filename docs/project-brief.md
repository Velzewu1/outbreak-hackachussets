# Project brief

> **Reconciliation notice (authoritative).** This brief is a high-level summary.
> The **authoritative** specification is the reconciled set produced from
> `Addiotional Info 1.txt`: `architecture.md`, `docs/mathematical-model.md`,
> `docs/weekly-state-machine.md`, `contracts/`, `docs/integration-plan.md`,
> `docs/architecture-decisions.md`, and `docs/end-to-end-walkthrough.md`. Where
> this brief's older wording conflicts with those documents, **those documents
> win**. In particular, the obsolete bits below are superseded:
> allocation/rerouting act on **new admissions only** (not a standing `H`
> census); SEIR conserves `S+E+I+R=N` with `H_need` an auxiliary need signal (not
> an `H` compartment / not occupied beds); the ledger is
> `accepted + unmet = need` per origin district with persistent retained cohorts,
> not `served + rerouted + unmet = demand`. The canonical typed contracts live in
> `contracts/`, not in the table below.

## Goal

Model how a weekly epidemic wave affects Boston-area hospital capacity and neighborhood access to care, then test whether rerouting or scenario changes reduce harm.

## Pipeline

```text
DATA -> SEPARATE -> IL1 -> SEIR+H -> IL2 -> FDNA -> ANALYSIS -> IL3 -> RESULTS
                         ^                          |          |
                         +------ next week --------+----------+
```

- **DATA:** acquire and validate public source tables.
- **SEPARATE:** create district and hospital node tables.
- **IL1:** produce district SEIR+H starting states.
- **SEIR+H:** simulate one week and produce admissions and compartment states.
- **IL2:** allocate patients, compute hospital load scores, and build the FDNA graph.
- **FDNA:** propagate hospital disruption to dependent hospitals and districts.
- **ANALYSIS:** reroute overload and compare scenario injections.
- **IL3:** package results and the next week's state.
- **RESULTS:** show the map, charts, assumptions, and forecast validation.

## Core data contracts

The canonical typed contracts (with units, invariants, serialization, and owners)
are defined once in **`contracts/`** — see `contracts/entities.md` and
`contracts/pipeline-types.md`. Do not duplicate or redefine them here. The headline
types are `District`, `Hospital`, `DiseaseConfig`, `NetworkConfig`, `Injection`,
`SEIRState` (`S,E,I,R`; `H` is **not** a compartment), `SEIRWeekOutput`
(`H_need`), `Accessibility`, `RequestRow`, `HospitalLoad`, `HospitalState`,
`FDNAGraph`, `FDNAResult`, `RerouteRecord`/`RerouteResult`, `WeekResult`,
`RunResult`, `ValidationReport`, `WeekView`.

> The earlier `Flow { district_id, hospital_id, share, patients }` (standing
> census) and `SEIRState` with an `H` field are **withdrawn** — superseded by
> `RequestRow` (new-admission requests) and the need-state `SEIRState` in
> `contracts/`.

## Default assumptions

- District unit: Suffolk County census tract.
- Distance accessibility: `exp(-d / 3 km)`.
- Keep up to five hospitals within 10 km.
- District hospital-dependence strength: 0.9.
- Hospital links: within 5 km, symmetric strength 0.1, criticality 100.
- Independent district SEIR is the MVP (Option A); mobility coupling is later work.
- Rerouting is partial and fills only available `free_new` capacity, acting on
  **new-admission requests only** (existing inpatients are persistent retained
  cohorts, never re-allocated). See `docs/mathematical-model.md` §5.

Every default above must remain configurable and visibly labeled as an assumption.

## Candidate public sources

- MassGIS acute-care hospital locations.
- Massachusetts healthcare datasets for hospital beds and identifiers.
- US Census ACS and TIGER/Line tract population and geometry.
- CDC PLACES tract health indicators, if useful and available.
- Massachusetts environmental-justice indicators for the map overlay.
- HHS historical facility-level hospital capacity for validation, subject to availability verification.

## Validation and safety

- Compare next-week hospital occupancy predictions with real held-out occupancy and a simple baseline.
- Report one clear error metric for both model and baseline.
- Use aggregate data only and expose missing-data or matching failures.
- The output is an educational what-if model, not an operational recommendation.
