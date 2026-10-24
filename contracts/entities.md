# Contracts — entities and configuration

Static inputs and configuration. Owner: **WS3** (data entities) / **WS5** (config
types). Specifications only; gate CLOSED.

---

## District

| Field | Type | Unit / constraint | Provenance |
|---|---|---|---|
| `district_id` | string | stable (full Census GEOID, leading zeros kept) | census |
| `geometry` | GeoJSON (WGS84) | valid polygon | TIGER |
| `centroid_lat`, `centroid_lon` | float | WGS84 degrees | derived (projected centroid) |
| `population` | int | `> 0` | ACS |
| `risk_weight` | float | `>= 0`; default `1.0` | CDC PLACES / assumption |
| `ej_flag` | bool \| null | `true`/`false`/**null** (unknown, never false-by-default) | EJ source / `unknown` |

Invariants: unique `district_id`; `population>0`; finite `risk_weight`; centroid
inside or a documented representative point.

**Example (SYNTHETIC — `geometry` abbreviated for readability, PARTIAL):**
```json
{"district_id":"D2","population":20000,"risk_weight":1.5,"ej_flag":null,
 "centroid_lat":42.33,"centroid_lon":-71.08,
 "geometry":{"type":"Polygon","coordinates":[[[-71.09,42.32],[-71.07,42.32],
   [-71.07,42.34],[-71.09,42.34],[-71.09,42.32]]]}}
```
(The polygon above is an illustrative placeholder square, not a real tract
boundary.)

---

## Hospital

| Field | Type | Unit / constraint | Provenance |
|---|---|---|---|
| `hospital_id` | string | stable | MassGIS/CMS crosswalk |
| `name` | string | original, never overwritten by matching | source |
| `lat`, `lon` | float | WGS84; valid | MassGIS |
| `staffed_beds` (`C`) | int | `> 0` | healthcare kit (verify staffed vs licensed) |
| `icu_beds` | int | `>= 0` | kit |
| `baseline_occupancy` (`baseline`) | number | **bed COUNT**, not a fraction | HHS pre-wave / assumption |

**Unit rule (ADR-CFG-1):** `baseline` is a count. A fallback fraction `f`
(default `0.75`) converts **once**: `baseline = f · staffed_beds`. Never add a
fraction to a bed count.

**Example (SYNTHETIC):**
```json
{"hospital_id":"H2","name":"Synthetic General","lat":42.34,"lon":-71.10,
 "staffed_beds":110,"icu_beds":14,"baseline_occupancy":75}
```

---

## DiseaseConfig

| Field | Type | Unit / constraint | Status |
|---|---|---|---|
| `r0` | float | `> 0`; start 2.5, fit when data permit | assumed/fitted |
| `latent_days` | float | `> 0`; default 5 | assumed |
| `infectious_days` | float | `> 0`; default 7 | assumed |
| `p_h` | float | `[0,1]`; default 0.03 | implementation decision (within 2–5%) |
| `los_days` | float | `> 0`; default 7 | assumed |
| `initial_infectious_fraction` | float | `[0,1]`; default 0.001 | assumed |
| `seir_mode` | enum | `A` (default) \| `B` (deferred) | primary default |

`p_h` is scaled per district to `p_H_j = clip(p_h · risk_weight_j, 0, 1)`
(ADR-SEIR-1). `los_days` → cohort `remaining_los` in weeks via a documented
mapping (ADR-SEIR-2).

---

## NetworkConfig

| Field | Type | Unit / constraint | Status |
|---|---|---|---|
| `d0_km` | float | `> 0`; default 3.0 | assumed |
| `k_nearest` | int | `>= 1`; default 5 | assumed |
| `radius_km` | float | `> 0`; default 10.0 | assumed |
| `hospital_link_radius_km` | float | `> 0`; default 5.0 | assumed |
| `alpha_d` | float | `[0,1]`; default 0.9 | assumed |
| `alpha_h` | float | `[0,1]`; default 0.1 | assumed |
| `beta_h` | float | `[0,100]`; default 100 | assumed |
| `distance_shape` | enum | `exponential` (default) \| `inverse_square` | primary default |

Eligibility: within `radius_km`, then nearest `min(k_nearest, eligible)`.

---

## Injection (discriminated union by `kind`)

An injection is a **discriminated union**: `kind` selects an exact typed
`payload`. There is no generic `target_id(s)` or numeric `value`. Common envelope
fields:

| Field | Type | Unit / constraint |
|---|---|---|
| `injection_id` | string | stable |
| `kind` | enum (see below) | selects the payload shape |
| `start_week` | int | `>= 0`; **inclusive** (zero-based week index) |
| `end_week` | int \| null | **exclusive**; `start_week < end_week`; null = open-ended |
| `note` | string | human-readable; mark hypothetical |
| `payload` | object | shape determined by `kind` (below) |

Payloads by `kind`:

| `kind` | payload fields | constraints / effect |
|---|---|---|
| `close_hospital` | `hospital_id: string` | `Ceff=0`, `own=0`; occupants survive (inherited deficit) |
| `set_capacity` | `hospital_id: string`, `factor: float` | `Ceff = C·factor`; `factor∈[0,1]` shortage, `>1` hypothetical surge (annotate) |
| `set_score` | `hospital_id: string`, `value: float [0,100]` | operability cap `min(physical_own, value)` |
| `reduce_score` | `hospital_id: string`, `points: float [0,100]` | lower operability cap by `points`, floor 0 |
| `add_edge` | `hospital_a: string`, `hospital_b: string`, `alpha: float [0,1]`, `beta: float [0,100]` | add **FDNA dependency** edge (default symmetric); **not** a transfer route |
| `remove_edge` | `hospital_a: string`, `hospital_b: string` | remove dependency edge(s) (default symmetric) |
| `set_edge` | `hospital_a: string`, `hospital_b: string`, `alpha: float [0,1]`, `beta: float [0,100]` | change dependency weights; log if asymmetric override |
| `set_share` | `district_id: string`, `hospital_id: string`, `share: float [0,1]` | override base share; renormalize remaining eligible shares to keep `Σ=1` |
| `add_route_option` *(optional, ADR-GRAPH-1)* | `district_id: string`, `hospital_id: string` | grant a **routing-eligibility** edge (separate from FDNA dependency) |

Semantics: applied from **base config** each week (no compounding). Referenced IDs
must exist. Contradictory injections on the same property/week are rejected,
except documented `reduce_score` stacking.

**Example (SYNTHETIC):**
```json
{"injection_id":"inj-1","kind":"close_hospital","start_week":2,"end_week":4,
 "note":"Hypothetical H2 closure weeks 2-3","payload":{"hospital_id":"H2"}}
```
```json
{"injection_id":"inj-2","kind":"set_capacity","start_week":1,"end_week":null,
 "note":"H1 at 60% (hypothetical)","payload":{"hospital_id":"H1","factor":0.6}}
```

---

## Config units & provenance

Every config field has: a single source of truth, a documented unit, an accepted
range, a UI-slider mapping, a cache-key effect, and a provenance label
(`source` / `fitted` / `assumption`). Defaults live in `config.yaml` (owned by
WS5) and are labeled; synthetic-mode defaults are examples only.
