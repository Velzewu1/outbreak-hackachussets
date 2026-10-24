# Project brief

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

| Type | Required fields |
|---|---|
| District | id, geometry, centroid, population, risk_weight, ej_flag, total_accessibility |
| Hospital | id, name, lat, lon, staffed_beds, icu_beds, baseline_occupancy |
| DiseaseConfig | R0, latent_days, infectious_days, hospitalization_fraction, length_of_stay_days, seed |
| NetworkConfig | distance_decay_km, k_nearest, district_radius_km, hospital_radius_km, district_strength, hospital_strength, hospital_criticality, distance_shape |
| SEIRState | per district: S, E, I, R, H |
| Flow | district_id, hospital_id, share, patients |
| Edge | feeder, receiver, kind, strength, criticality |
| Injection | kind, targets, value, start_week, end_week, note |
| WeekResult | week, hospital rows, district rows, reroutes, unmet demand, injections, checks |
| RunResult | configuration, weekly results, validation metrics |

## Default assumptions

- District unit: Suffolk County census tract.
- Distance accessibility: `exp(-d / 3 km)`.
- Keep up to five hospitals within 10 km.
- District hospital-dependence strength: 0.9.
- Hospital links: within 5 km, symmetric strength 0.1, criticality 100.
- Independent district SEIR+H is the MVP; mobility coupling is later work.
- Patient rerouting is partial, fills only available capacity, and repeats until stable.

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
