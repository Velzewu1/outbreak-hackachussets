# DS+X 2026 project plan: epidemic demand + hospital dependency network (SEIR + FDNA)

Team briefing for the DS+X hackathon and Hackachusetts, BU CDS, Sat 24 to Sun 25 Oct 2026.
Written for teammates **and for the AI assistants they use**. It is long on purpose: everyone, human or AI,
should be able to work from this file without asking what we meant.

This is NOT the project README. The README in the repo should be short and is written separately.

Version: Sat 24 Oct 2026, 15:10. Built from the hand-drawn layer sketch (DSX_PLAN.pdf) plus the team's notes.

---

## 0. Read this first (rules that apply to everyone, including AI assistants)

1. **All project code is written with Kiro.** Hackachusetts requires it ("No Kiro, no Hackachusetts prize"),
   and we decided the whole project is Kiro only. Other AI tools may explain concepts or review this plan,
   but code that goes in the repo comes from Kiro.
2. **The presentation is 3 minutes with no Q&A.** Everything the judges need must be on the slides or in the
   demo. Nobody gets to explain an assumption afterwards.
3. **DS+X requires real data science.** The packet: "Calling an API or LLM, installing a tool, or making
   charts without meaningful analysis does not, by itself, qualify as data science." We need a substantial
   dataset, an identifiable method, and a validation number.
4. **Never invent data.** Where we assume a value (a parameter, a weight), it is labelled as an assumption in
   the code, in the README and on the slides. Assumptions are fine. Hidden assumptions are not.
5. **Every layer is wrapped in small functions with fixed inputs and outputs** (see section 6), including
   stubs that do almost nothing yet. This is deliberate: it lets us add better models later without
   rewriting the pipeline.
6. **AI assistants:** where this file says "decision open" or "assumption", do not silently pick an answer.
   Implement the default given here and leave it configurable.

---

## 1. The project in one paragraph

We model what happens to Boston's hospitals and neighbourhoods during an epidemic. An **SEIR** epidemic
model runs in every district (a small area of the city) and produces how many people from that district need
a hospital bed each week. Those patients are sent to nearby hospitals based on distance. Each hospital gets a
**score from 0 to 100** for how well it is coping (100 = everyone can be treated, 50 = only half can). A
dependency-network method called **FDNA** then spreads hospital trouble outward: hospitals share resources
with each other, and each district depends on the hospitals near it, so we get a number for **how badly each
district loses access to care** when hospitals are overwhelmed or fail. An **analysis** step reroutes excess
patients from overwhelmed hospitals to ones with space, and lets us **inject scenarios** (close a hospital,
cut its capacity for construction, add a link) to test whether a fix relieves the pressure. The whole thing
**steps forward one week at a time**, and we check it by **predicting next week's real hospital occupancy**
and comparing against a simple baseline.

---

## 2. The pipeline (from the sketch)

```
 DATA ──> SEPARATE ──> IL1 ──> SEIR ──> IL2 ──> FDNA ──> ANALYSIS ──> IL3 ──> RESULTS
                        ^                 ^                  |          |
                        |                 └── injections <───┘          |
                        └───────────── next week's state <──────────────┘
```

- **IL = intermediary layer.** Each IL is a translator between two models. It takes the output of the
  previous block, converts it into the input format of the next block, and runs checks on the way through.
  The models themselves (SEIR, FDNA) never read raw data and never talk to each other directly.
- **The loop IL3 → IL1** is the time dimension: one pass through the pipeline is one week.
- **The loop ANALYSIS → IL2** is the scenario/fix loop: when something fails, we change the network
  (topology, weights, a hospital's capacity) at IL2 and rerun FDNA to see whether the change relieves the
  stress. These changes are called **injections**.

### 2.1 The blocks, one line each

| # | Block | Job | In | Out |
|---|---|---|---|---|
| 1 | DATA | Load raw sources | Files and APIs | Raw tables |
| 2 | SEPARATE | Turn raw data into the two kinds of node | Raw tables | District table, hospital table |
| 3 | IL1 | Prepare SEIR input | Districts, disease settings, last week's state | SEIR starting state per district |
| 4 | SEIR | Run the epidemic for one week | Starting state | S, E, I, R, H per district, new admissions |
| 5 | IL2 | Turn epidemic output into a network | SEIR output, hospitals, distances, injections | Patient flows, hospital load scores, FDNA graph with all edge values |
| 6 | FDNA | Spread failure through the network | FDNA graph | Final score for every hospital and every district |
| 7 | ANALYSIS | Reroute overload, run scenario checks | FDNA scores, flows | Rerouting plan, before/after scores, unmet demand, worst-hit lists |
| 8 | IL3 | Package results, prepare next week | Everything above | Results for display, state for next week |
| 9 | RESULTS | Show and validate | IL3 output | Map, charts, forecast vs real data |

---

## 3. Key concepts (short primer for anyone new to these)

### 3.1 SEIR

A model of an epidemic inside **one population**, where everyone is assumed to mix with everyone else.
People move through four boxes:

- **S** susceptible: can catch it.
- **E** exposed: infected, not yet infectious.
- **I** infectious: can spread it.
- **R** removed: recovered (or dead), no longer part of spread.

Rates: `β` (transmission rate), `σ` (1 / latent period), `γ` (1 / infectious period).
`R0 = β / γ` is the average number of people one case infects in a fully susceptible population.

We add an **H** box (hospitalised) because hospital beds are what we care about: a fraction `p_H` of people
leaving I go to H, and people leave H at rate `1 / LOS` (length of stay). This is still called SEIR in the pitch,
but the code should be honest that it is SEIR plus a hospital box.

**SEIR runs inside each district separately.** A plain SEIR does not know other districts exist. Spread
between districts needs an extra coupling term (section 5.3, option B).

### 3.2 FDNA (Functional Dependency Network Analysis)

A method for asking "if this part fails, how much does everything that depends on it suffer?"
Attributed to Garvey and Pinto (MITRE, around 2009). **The formulas below are written from memory: check them
against the paper before they go on a slide.**

- **Nodes** have a **score (operability) from 0 to 100**. 100 = fully working, 0 = failed.
  - Nodes that depend on nothing: **we set the score** (that is the input / scenario).
  - Every other node: **FDNA calculates the score** from the nodes it depends on.
- **Edges** are **one-way**: an edge from A to B means "B depends on A". A failing A pulls B down, not the
  other way. A and B can depend on each other, but that is two separate edges with their own numbers.
- Each edge carries two numbers:
  - **Strength (α, 0 to 1):** how much of the receiver's score comes from this feeder. Gradual decline.
  - **Criticality (β, 0 to 100):** a ceiling. The receiver can be at most β points above this feeder.
    **Low β = very critical.** β = 100 means no ceiling. Sudden drop.
- **Baseline (BOL, 0 to 100):** what the receiver manages on its own when the feeder gives nothing.

Classic formula for receiver i with feeders j:

```
strength term     SODP_ij = α_ij * P_j + BOL_i * (1 - α_ij)
criticality term  CODP_ij = P_j + β_ij
score             P_i = min( mean over j of SODP_ij , min over j of CODP_ij )
```

Worked example. The feeder drops from 100 to 20, the receiver starts at 100:

| Strength | Criticality | Receiver ends at | Real-world example |
|---|---|---|---|
| High (0.9) | High (β 10) | 28 | Life support and power |
| High (0.9) | Low (β 100) | 28 | Factory mostly on grid power |
| Low (0.2) | High (β 10) | 30 | Hospital and oxygen: small share, but fatal when it fails |
| Low (0.2) | Low (β 100) | 84 | Cafe and its Wi-Fi |

Takeaway: strength = how far you slide; criticality = whether there is a hard cap. Criticality matters most
when strength is low ("small but essential").

FDNA calculates **forward only**: known feeders → unknown receivers. It does not natively infer a feeder
from an observed receiver. Classic FDNA also **requires no loops**. Our hospital-to-hospital edges create
loops; section 5.6 says how we handle that.

### 3.3 Why both models

SEIR alone says how many people get sick, not what breaks. FDNA alone says what breaks if something fails,
not why it would fail. Together: the epidemic causes the failure, and the network shows who it reaches.

---

## 4. Network design (the decisions)

### 4.1 Nodes

| Node | What it is | Score means |
|---|---|---|
| **District** | A small area of population: census tract (default) or ZIP code | Access to hospital care for the people living there |
| **Hospital** | One hospital, treated as a single node | How well it can treat the patients sent to it |

Hospitals are generalised to one node each, even though in reality they are made of beds, staff, ICU,
emergency departments, ambulances, supplies, and depend on shared services (EMS, transport, police such as
BUPD, suppliers). That detail is future work (section 13).

### 4.2 Edges

| Edge | Direction (feeder → receiver) | Meaning | Values |
|---|---|---|---|
| Hospital → district | hospital is the feeder | The district depends on the hospital for care. If a hospital fails, it propagates to the districts | From the accessibility function (4.3) |
| Hospital ↔ hospital | both directions, **same values both ways** | Hospitals share resources: transport, EMS, staff, supplies | Uniform default, adjustable (4.4) |
| District → hospital | district is the feeder | **Not an FDNA edge for now.** Districts affect hospitals only through patient numbers (IL2), not through FDNA | none |

**Deliberately asymmetric for this demo:** districts depend on hospitals, hospitals do not depend on districts
inside FDNA. The epidemic reaches hospitals through **patient load**, which sets each hospital's own
starting score in IL2. FDNA then carries hospital trouble out to the districts.

**Hospital-to-hospital is assumed fully symmetric** because we have no data on which hospital relies on
which. This is an assumption, stated on the slides.

### 4.3 District dependency on each hospital: the accessibility function

Each district depends on each hospital according to **how far it is** and **how many other hospitals are
close**. If several hospitals are close, the dependency is spread out and each single hospital matters less.

Step 1. Distance `d_ij` from district j's centre (population-weighted centroid if available, plain centroid
otherwise) to hospital i. Straight-line distance in km is the default; travel time is future work.

Step 2. Accessibility of hospital i from district j, a decreasing function of distance:

```
a_ij = exp( - d_ij / d0 )            default d0 = 3 km  (assumption, a slider)
```

Only the `k` nearest hospitals (default `k = 5`) or those within radius `R` (default 10 km) are kept, so the
graph stays sparse. Alternative shape, configurable: `a_ij = 1 / (1 + (d_ij / d0)^2)`.

Step 3. **Share** of district j's dependency (and patients) going to hospital i:

```
s_ij = a_ij / (sum over kept hospitals k of a_kj)
```

The shares of a district sum to 1. One close hospital → its share is near 1. Four equally close hospitals →
0.25 each. This is exactly "more hospitals nearby = less dependency on each".

Step 4. **Total accessibility** of the district, `A_j = sum over k of a_kj`. Not used in FDNA, but reported:
a low A_j means a district far from all care, which matters for the ethics overlay.

Step 5. FDNA edge values for hospital i → district j:

| Value | Default formula | Why |
|---|---|---|
| Strength | district dependence on hospital care overall `α_D` (default 0.9, assumption), split by shares: see 5.6 | Districts rely heavily on hospitals during an epidemic |
| Criticality | `β_ij = 100 * (1 - s_ij)` | Only hospital nearby (s = 1) → β = 0, the district can never be better off than that hospital. One of four (s = 0.25) → β = 75, losing it caps the district at 75 |

The **same shares s_ij** decide where patients go (IL2) and how much each district depends on each hospital
(FDNA). One function, used twice, so the model is consistent and easy to explain.

### 4.4 Hospital-to-hospital edge values

No data, so one uniform setting, adjustable:

- Connect hospitals within `R_H` km of each other (default 5 km, assumption).
- Strength `α_H` = 0.1 both ways (default, slider). Small: one hospital failing hurts its neighbours a little
  through shared resources.
- Criticality `β_H` = 100 both ways (default). No hard cap, because no single neighbour is essential.
- Same values in both directions (symmetric).

Patient overflow between hospitals is **not** modelled through these edges. Overflow is handled as actual
patient numbers in ANALYSIS (section 5.7). These edges are only for shared-resource strain.

---

## 5. Layer-by-layer specification

Each layer: purpose, inputs, outputs, method, stubs. Function names are suggestions for Kiro; keep the
inputs and outputs as specified.

### 5.1 DATA

Purpose: get every raw source into `data/raw/`, once, and commit the cleaned versions. **The demo must never
depend on a live API during judging.**

| Source | What we take | Notes |
|---|---|---|
| Hospital locations: MassGIS acute care hospitals layer | Name, coordinates | Request with geometry. The healthcare kit's hospitals file has no coordinates |
| Hospital beds: healthcare kit `hospitals` dataset (103 MA rows) | ICU, med-surg, paediatric beds | Join to MassGIS by name; fix mismatches by hand and keep the mapping table in the repo |
| Hospital list: healthcare kit `cms-hospitals` (84 rows) | Backup identifiers, ratings | Optional |
| District population: US Census (ACS) by tract for Suffolk County (option: Greater Boston) | Population, tract geometry | Census TIGER shapefiles for geometry |
| District health risk: CDC PLACES by tract | Chronic disease prevalence | Optional weight for hospitalisation risk (5.3) |
| Environmental justice: healthcare kit `ej` (2,604 MA block groups) | EJ flags | Ethics overlay on the map |
| Validation: HHS "COVID-19 Reported Patient Impact and Hospital Capacity by Facility" (healthdata.gov) | Weekly beds used and staffed beds per hospital | **Availability not yet verified. Check first.** This is our real-data target |
| Calibration: county-level hospital admissions for the same period | Weekly admissions, Suffolk | To fit β; source to confirm (the same HHS data summed works) |

Functions: `load_raw()`, `save_clean()`, `validate_raw()` (stub: row counts, required columns present).

### 5.2 SEPARATE

Purpose: produce the two node tables.

- `build_districts()` → table: `district_id, geometry, centroid, population, risk_weight (default 1.0), ej_flag`.
- `build_hospitals()` → table: `hospital_id, name, lat, lon, staffed_beds C_i, icu_beds, baseline_occupancy`.
  - `baseline_occupancy`: normal non-epidemic patients, from HHS data before the outbreak. If missing, assume
    75% of beds (assumption, slider).
- `check_separation()` (stub): every district has population > 0, every hospital has coordinates and beds,
  every district has at least one hospital within R.

### 5.3 IL1: prepare SEIR

Purpose: turn districts plus disease settings into the SEIR starting state, and on later weeks take last week's
state from IL3.

Inputs: district table, disease config, `state_prev` (None in week 0).

Disease config (all assumptions, all sliders, all fitted where data allows):

| Setting | Default | Note |
|---|---|---|
| `R0` | fitted (start near 2.5) | β = R0 · γ |
| latent period | 5 days | σ = 1/5 |
| infectious period | 7 days | γ = 1/7 |
| hospitalisation fraction `p_H` | fitted or ~2–5% | scaled per district by `risk_weight` |
| length of stay `LOS` | 7 days | |
| seed | 0.1% of population infectious in week 0 | or a chosen district for scenarios |

These defaults are illustrative, not sourced. Fit what we can (5.4) and label the rest.

Two options for how districts relate (decision: **start with A**):

- **A. One SEIR curve, split by district.** Fit one SEIR for the whole region, then split each week's infections
  across districts by population × risk_weight. Fast (about 1 hour), fits real data cleanly.
- **B. Coupled SEIR per district (metapopulation).** Each district has its own S, E, I, R. Infection pressure
  on district j: `λ_j = β * (I_j + sum over k of m_jk * I_k) / N_j`, where `m_jk` is mixing between districts
  (assume it decays with distance). Shows waves crossing the city, but the per-district parameters cannot be
  fitted with available data. Only if A is done early.

Both options output the same thing (per-district weekly numbers), so everything after IL1 is unchanged.

Functions: `init_state(districts, config)`, `carry_state(state_prev)`, `check_il1()` (stub: S+E+I+R+H = N
per district).

### 5.4 SEIR

Purpose: run one week (7 daily steps, or an ODE solver over 7 days).

Output per district j for week t: `S, E, I, R, H` (people in hospital beds), `admissions_j(t)` (new hospital
admissions that week), `new_infections_j(t)`.

Fitting (this is the data science core): fit `R0` (and `p_H` if possible) by least squares between modelled
regional hospital census and real reported census for a chosen past wave. Report the fit quality.

Functions: `step_week(state, config)`, `fit_params(observed_series)`, `check_seir()` (stub: no negative
compartments, totals conserved).

### 5.5 IL2: from epidemic to network

Purpose: turn SEIR output into (a) patient numbers at each hospital, (b) each hospital's own score, and
(c) the full FDNA graph. **This is also where injections are applied.**

Step 1. Patient flow from district j to hospital i:

```
flow_ij = s_ij * H_j
```

Step 2. Demand at hospital i (epidemic patients plus normal patients):

```
D_i = baseline_occupancy_i + sum over j of flow_ij
```

Step 3. Capacity after injections:

```
C_eff_i = C_i * capacity_factor_i          capacity_factor_i = 1 normally, e.g. 0.6 under construction, 0 closed
```

Step 4. Hospital's own score, from how many patients it cannot accommodate:

```
own_i = 100 * min(1, C_eff_i / D_i)
```

Reading: at or under capacity → 100. Demand 25% over capacity → 80 (it can treat 80% of patients).
Also record `excess_i = max(0, D_i - C_eff_i)`, the number of people it cannot take.
This mapping is deliberately simple; a smoother curve is a later option.

Step 5. Build the FDNA graph: hospital nodes with `BOL_i = own_i`, district nodes with `BOL_j = 100`, edges
from 4.3 and 4.4, then apply topology injections (Step 6).

Step 6. **Injections** (manual for now, structured so an analysis tool can generate them later):

| Injection | Effect |
|---|---|
| `close_hospital(i)` | capacity_factor = 0, own score forced to 0 |
| `set_capacity(i, factor)` | construction, staffing shortage, partial failure |
| `set_score(i, value)` / `reduce_score(i, amount)` | directly set or lower a hospital's score, e.g. to test it under normal conditions with no epidemic |
| `add_edge / remove_edge(a, b)` | change topology, e.g. a new transfer agreement |
| `set_edge(a, b, α, β)` | change one dependency |
| `set_share(j, i, s)` | change where a district's patients go |

Every injection has a start week and optional end week, and is logged in the results so the demo can say
exactly what was changed.

Functions: `compute_flows()`, `compute_own_scores()`, `build_graph()`, `apply_injections()`,
`check_il2()` (stub: flows sum to H per district, shares sum to 1, all scores within 0 to 100).

### 5.6 FDNA

Purpose: compute every final score.

**Order:** hospitals first (they depend only on each other), then districts (they depend only on hospitals).

Hospitals, with the symmetric loop:

```
start:   P_i = own_i for every hospital
repeat:  P_i_new = min( own_i, FDNA formula over its hospital neighbours using current P )
until:   no score changes by more than 0.1
```

The `min(own_i, ...)` clamp means a struggling hospital is never lifted above its own state by a healthy
neighbour. Starting from own scores, the scores can only go down, so the loop always stops. This is our
adaptation for loops; classic FDNA has none. The alternative, also allowed: use last week's neighbour scores
(one-week lag), which removes the loop entirely.

Districts, with a **share-weighted** strength term:

```
strength term     SOD_j  = α_D * (sum over i of s_ij * P_i) + (1 - α_D) * 100
criticality term  CODP_ij = P_i + β_ij           with β_ij = 100 * (1 - s_ij)
district score    P_j = min( SOD_j , min over i of CODP_ij )
```

Why share-weighted instead of the classic plain mean: with the plain mean, a district with 5 nearby
hospitals would barely notice losing its main one, because the shares already dilute it and the mean would
dilute it again. **This is our modification; say "FDNA-based" on the slides, not "FDNA" unqualified.**

Check examples (α_D = 0.9, one hospital fails to 0, others at 100):

| District has | Share of the failed one | Result |
|---|---|---|
| 1 hospital | 1.0 | 0 |
| 2 equal hospitals | 0.5 | 50 (capped by criticality) |
| 4 equal hospitals | 0.25 | 75 |

Functions: `solve_hospitals()`, `solve_districts()`, `check_fdna()` (stub: all scores in 0 to 100, closing a
hospital never raises any score).

### 5.7 ANALYSIS: rerouting and scenario checks

Purpose: find overwhelmed hospitals, move pressure elsewhere, report who is hurt, and support the
injection loop back to IL2.

**Rerouting algorithm (default, greedy):**

```
for each overwhelmed hospital h (excess_h > 0), most overwhelmed first:
    list the districts sending patients to h, largest flow first
    for each such district j, in that order:
        list j's other hospitals by share s_ij, highest first (closest / most accessible)
        for each candidate hospital c with spare beds (C_eff_c - D_c > 0):
            move  m = min(excess_h, flow_jh, spare_c)  patients from h to c
            update flow_jh, flow_jc, D_h, D_c, excess_h
            if excess_h == 0: stop with h
        if j has nothing left to move or no candidate had room: go to the next district
    if excess_h > 0 after all districts: record it as unmet demand for h, split by district
```

In words: take the district putting the most pressure on the overwhelmed hospital and move its patients to
its next-best hospital. If that hospital cannot take them, try its next option; when that district runs out of
options, go to the next-biggest district and repeat. Whatever cannot be placed is **unmet demand**.

Decisions open (defaults in bold): partial moves allowed (**yes**); whether rerouting may push a receiving
hospital to exactly full (**yes, never over**); one rerouting pass or repeat until nothing moves (**repeat**).

After rerouting, rerun IL2 steps 2 to 5 and FDNA with the new flows, giving **before** and **after** scores.

Reported every week:
- hospital: demand, capacity, own score, final score, excess before / after rerouting
- district: final score before / after, unmet demand, total accessibility A_j, EJ flag
- worst-hit lists: top hospitals by excess, top districts by score drop
- total check: `served + rerouted + unmet = total demand` (must hold exactly)

**Scenario loop:** if the after-rerouting picture still shows failure, a person (or later a tool) adds an
injection at IL2 (e.g. raise capacity at one hospital, add a transfer link, open a field hospital as a new node)
and reruns the week. Compare the two runs: did unmet demand fall, did the worst districts recover? That
comparison is how we test whether a proposed fix actually relieves the stress.

Functions: `find_overloaded()`, `reroute()`, `summarise()`, `compare_runs(run_a, run_b)`,
`analysis_hook()` (stub: an empty plug-in point where a smarter optimiser can be added later).

### 5.8 IL3: package and loop

Purpose: (a) hand results to the display, (b) hand next week's starting state to IL1.

- Results record per week: everything from ANALYSIS plus the injections active that week.
- State for next week: SEIR compartments per district (H is carried forward, rerouting does not change
  how many people are sick), active injections.
- Decision open: whether unmet demand feeds back into the epidemic (e.g. higher death rate). Default **no**,
  outcomes only, to keep the epidemic fit clean.

Functions: `package_results()`, `next_state()`, `export_results()` (CSV / JSON for the app and for the
Devpost page), `check_il3()` (stub).

### 5.9 RESULTS: display and validation

**Validation (this is the DS+X data science score):**

- Pick a past wave with real per-hospital data (HHS facility data, if available for Boston hospitals).
- Fit on the first part of the wave, then step week by week: at week t predict each hospital's occupancy at
  t+1, compare with the real number.
- Metrics: mean absolute error (beds), and the same for a **naive baseline: next week = this week**.
- Also run with rerouting off, to show whether the network part adds anything (ablation).
- The slide shows one number: "our model's error vs the baseline's error". If we lose to the baseline, say so
  and show where (honesty scores better than a hidden loss).

**App (Streamlit):**

- Map of districts coloured by score, hospitals as dots sized by beds and coloured by score.
- Week slider, R0 slider, d0 slider, α_D and α_H sliders.
- "Close hospital" / "reduce capacity" controls = injections.
- Before / after rerouting toggle.
- EJ overlay toggle.
- Chart: predicted vs real occupancy for a chosen hospital, with the baseline.
- Table view of all numbers (accessibility, and judges who want the data).

---

## 6. Data types (the contract between layers)

| Type | Fields |
|---|---|
| `District` | id, geometry, centroid, population N, risk_weight, ej_flag, total_accessibility A |
| `Hospital` | id, name, lat, lon, staffed_beds C, icu_beds, baseline_occupancy |
| `DiseaseConfig` | R0, latent_days, infectious_days, p_H, LOS_days, seed |
| `NetworkConfig` | d0, k_nearest, R, R_H, α_D, α_H, β_H, distance_shape |
| `SEIRState` | per district: S, E, I, R, H |
| `Flow` | district_id, hospital_id, share s, patients |
| `Edge` | feeder, receiver, kind (hospital_district / hospital_hospital), α, β |
| `Injection` | kind, target(s), value, start_week, end_week, note |
| `WeekResult` | week, per-hospital rows, per-district rows, reroutes, unmet, injections, checks passed |
| `RunResult` | config, list of WeekResult, validation metrics |

Keep every config value in one config file, never hard-coded inside functions. Every slider maps to one
config field.

---

## 7. Repo layout and stack

```
repo/
  README.md          short: what, how to run, data sources, assumptions, demo link, video link
  requirements.txt   pinned
  config.yaml        every parameter, with comments saying which are assumptions
  data/raw/          downloaded originals (if small enough) and fetch scripts
  data/clean/        cleaned tables, committed
  pipeline/          one module per block: data, separate, il1, seir, il2, fdna, analysis, il3
  app/               Streamlit app
  validation/        backtest and metrics
  tests/             the check_* stubs grow into tests here
```

Stack: Python, pandas, geopandas/shapely, numpy, scipy (ODE + fitting), networkx or plain matrices,
Streamlit with pydeck or folium, hosted on Streamlit Community Cloud. All written in Kiro.

---

## 8. Deadlines (Sat 24 Oct is today)

| When | What |
|---|---|
| Sat 18:30 | Hackachusetts submission, advised time (Sundai portal: repo + video demo) |
| **Sat 20:00** | **Hackachusetts hard deadline** |
| Sat 20:15 | Mandatory DS+X evening session, room 164 |
| **Sat 21:30** | **DS+X Devpost project page must exist**, all teammates listed (unlisted = cannot win) |
| Sat 22:00 | BU students cannot re-enter the building after this |
| **Sun 10:00** | Submit DS+X by this time. Devpost header says 10:00, slides say 11:00, organisers were unsure: treat 10:00 as real |
| Sun 11:30–13:00 | DS+X presentations, 3 minutes, no Q&A |
| Sun 11:00 | Hackachusetts finalists present at WHOOP (clashes with DS+X; decide who goes if we are a finalist) |

DS+X submission must contain: GitHub repo with README, app link, slide deck link, video showing setup and use.
On Devpost the status must read **Submitted**, not saved.

---

## 9. Judging and how this project hits each part

Packet weights (the Devpost page lists different ones; the packet's are below):

| Criterion | Weight | How we score |
|---|---|---|
| Impact | 25 | Hospital overflow and unequal access to care are real Boston problems; the tool answers "which neighbourhoods lose care if X happens" |
| Data science | 25 | Real data (census, hospitals, HHS occupancy), two named methods (SEIR fitted to data, FDNA-based propagation), validation against a baseline |
| Technical | 20 | Layered pipeline, weekly time loop, rerouting algorithm, scenario injections, working app |
| Design | 10 | One clear map, few controls, before/after toggle |
| Ethics | 10 | Aggregate data only (no patients), EJ overlay, every assumption listed, limits stated |
| Presentation | 10 | 3-minute script below |

3-minute outline: 0:00 problem (one Boston fact) · 0:25 live demo: close a hospital, watch districts drop,
reroute · 1:35 data and method, validation number vs baseline · 2:15 ethics and limits · 2:40 impact and next
steps.

---

## 10. Ethics and limits (for the slide and the README)

- **Privacy:** only public, aggregate data. No patient records.
- **Fairness:** the EJ overlay shows whether low-access districts are also environmental-justice
  communities. Distance-based access ignores insurance, language, hospital system and transport, which hit
  some groups harder: state it.
- **Transparency:** every assumed parameter is in `config.yaml` with a comment, and listed in the README.
- **Not a decision tool:** it is a what-if model. Real hospital planning needs real transfer and staffing data.

---

## 11. Team plan (fill in names)

| Person | Owns |
|---|---|
| A | DATA + SEPARATE: hospitals with coordinates and beds, tracts with population, HHS validation pull |
| B | IL1 + SEIR + fitting |
| C | IL2 + FDNA + ANALYSIS (rerouting, injections) |
| D | App, slides, video, Devpost/Sundai pages |

Checkpoints: **16:00** clean node tables + SEIR fitted · **17:30** IL2 + FDNA producing scores · **18:30**
rerouting + map working, submit to Hackachusetts (repo + video) · **21:30** Devpost page created with everyone
listed · Sunday morning: validation numbers, slides, final video, submit by 10:00.

If behind schedule, cut in this order: option B SEIR (never started), hospital-to-hospital edges (set α_H = 0),
smooth score curves, extra sliders. **Never cut validation.**

---

## 12. Open decisions (defaults already chosen; change in config, not in code)

1. Districts: census tracts (default) or ZIP codes.
2. Region: Suffolk County (default) or wider Greater Boston.
3. Distance shape: exponential with d0 = 3 km (default) or inverse-square.
4. k nearest hospitals: 5 (default).
5. α_D = 0.9, α_H = 0.1, β_H = 100, R_H = 5 km (all assumptions).
6. SEIR option A (default) or B.
7. Rerouting: partial moves, fill to full not over, repeat until stable.
8. Unmet demand affects outcomes only, not the epidemic.
9. Which past wave to validate on: pick once the HHS data is confirmed.

---

## 13. Next steps (for the last slide)

- Split hospitals into resources (ICU, ED, staff, oxygen, ambulances) where FDNA's criticality really matters.
- District → hospital FDNA edges for staff: infection in a district reduces hospital staff.
- Real transfer data and hospital-system clusters (transfers mostly stay within a system).
- Travel time instead of straight-line distance.
- An optimiser in the analysis hook: where would one extra field hospital or transfer link help most?
- Coupled SEIR across districts (option B) with real mobility data.

---

## 14. Glossary

| Term | Meaning |
|---|---|
| District | Small population area, a census tract by default |
| Share s_ij | Fraction of district j's patients and dependency assigned to hospital i |
| Accessibility a_ij | How reachable hospital i is from district j; falls with distance |
| Own score | A hospital's score from its own load: `100 * min(1, capacity / demand)` |
| Final score | Score after FDNA propagation |
| Excess | Patients a hospital cannot take |
| Unmet demand | Excess that rerouting could not place anywhere |
| Injection | A manual change to the network or a hospital, used for scenarios and to test fixes |
| IL | Intermediary layer: a translator between two blocks, with checks |
| BOL | Baseline operability: what a node manages without its feeders |
| α, β | FDNA strength and criticality of an edge |
