Contents

1. [What the system does](#scope)
2. [Stack](#stack)
3. [Architecture](#architecture)
4. [The daily loop](#loop)
5. [Contracts](#contracts)
6. [Components](#components)
7. [Scenarios and wiring](#composition)
8. [Repository layout](#layout)
9. [Extending the system](#extend)
10. [Scaling](#scale)
11. [Testing](#testing)
12. [Rules and pitfalls](#rules)
13. [Full source](#source)

Boston Hospital Cascade Model · Whole system

# System Architecture Coding Guide

How the layers fit together: data ingestion, SEIR, allocation, FDNA, rerouting, equity, the API and the dashboard. Each layer is a small module with one job, they talk only through typed daily snapshots, and one function wires them up, so the team can build them in parallel and swap any one out.

v1 · 24 Oct 2026Reference code: 20 tests passing200 tracts × 9 ages × 20 hospitals × 365 days in 2.1 s

Reference implementation

Every code block on this page comes from a working package that I built and tested while writing the guide. It's in the project files as `hackathon/cascade-reference/` (also zipped as `hackathon/cascade-reference.zip`). It contains the [SEIR layer](https://claude.ai/artifact/FUq8QqeVhVB8d4bVbMPEPd) unchanged under `cascade/epi/` and adds every other layer around it. The design follows the [technical writeup](https://claude.ai/artifact/G8RPYDJE1TG2Fn1hBwDzZd).

## 01What the system does

Given a scenario file (a disease, a population, a hospital network and optional shocks), the system simulates day by day how the epidemic produces patients, where those patients go, how hospitals and their dependencies lose operability, which hospitals go on diversion, and which neighborhoods lose access to care. It also ranks single points of failure.

#### Takes in

- A SEIR scenario: disease, population by patch and age, mixing, seeding
- The hospital network: beds, ER flag, baseline occupancy, drive times from each patch
- FDNA dependency weights (SOD, COD) for each edge type
- Diversion thresholds and vulnerability weights per patch
- Events: "cap node X at operability Y from day d"

#### Gives out

- One xarray Dataset with dims `time × hospital`, `time × patch` and `time × node`
- The full SEIR result (`time × patch × age`)
- A summary: peak ICU occupancy, diversion days, diverted and overflow patients, lost access, deaths
- A criticality table: extra citywide loss when each node fails

Design goals, in order: layers that can be built and tested alone; boundaries that are typed and stable; one place that knows about every module; the same code for 3 patches and 4 hospitals as for 200 tracts and 60 hospitals; and a dashboard that is a thin client of the same API the tests use.

## 02Stack

Same as the SEIR guide, plus networkx for the dependency graph. Everything runs in one Python process, so no layer needs a serialization format to talk to another.

| Need | Library | Used by |
| --- | --- | --- |
| Arrays and maths | NumPy 2.x | Every layer. Arrays are indexed in `Network` order (patches, hospitals) |
| Tables and ingestion | pandas | `cascade/data`: raw CSVs to processed tables; criticality output |
| Labelled output | xarray | Recorder and SEIR results; NetCDF export |
| Config and validation | pydantic v2 + PyYAML | One `SystemConfig` per scenario, validated on load |
| Dependency graph | networkx | FDNA: cycle check and topological order, once per scenario |
| Optimization, fitting | SciPy | Calibration (`least_squares`); optional LP assigner (`linprog`) |
| Dashboard | Streamlit (+ pydeck for maps) | `app/streamlit_app.py`, calling `cascade.api` only |
| Tests | pytest | Unit tests per layer, system tests, a boundary test |

```
pip install -r requirements.txt     # numpy scipy pandas xarray pydantic pyyaml networkx pytest streamlit
```

## 03Architecture

Three rings. In the middle is the **simulation core**: a shared state object and a loop that calls modules in order. Around it are the **layer modules**, each reading some snapshots and writing exactly one. On the outside are the **edges**: ingestion turns raw files into a validated network, and the API turns a scenario into results for the dashboard, the CLI and notebooks.

Solid lines are calls and data flow within a day. Dashed lines are the two feedback channels, both read on the next day. Only `build()` knows every module; only `cascade.api` is imported by the dashboard.

| Component | Package | Job | Owner can work alone on… |
| --- | --- | --- | --- |
| Ingestion | `cascade/data` | Raw CSVs to one validated hospitals table; drive times; patch populations | Joins and cleaning, tested against the project files |
| Network | `cascade/network.py` | Static hospitals, beds, drive times, gravity shares | Catchment model |
| SEIR | `cascade/epi` | Daily admissions per patch; reads FDNA feedback | Everything in the SEIR guide |
| Allocation | `cascade/allocation.py` | Admissions to hospitals, census and occupancy | Patient choice model, LOS |
| FDNA | `cascade/fdna` | Dependency graph, operability, criticality sweep | Graph design, weights, resource providers |
| Rerouting | `cascade/reroute.py` | Diversion rule; assignment of diverted patients | Policy and assigner |
| Equity | `cascade/equity.py` | Access per patch, vulnerability weighting | Access metric, SVI and EJ weights |
| Recorder + API | `cascade/recorder.py`, `api.py` | Daily snapshots to xarray; public entry points | Output schema, summaries |
| Dashboard | `app/` | Sliders, charts, knock-outs, criticality | UI, against a fixed demo scenario |

## 04The daily loop

One call to `Simulation.run(days)` steps every module once per day, in a fixed order. Order is part of the design: a module may read snapshots written earlier the same day, and anything it wants to send to a module earlier in the order goes through `state.signals` and arrives the next day.

| # | Module | Reads (same day) | Reads (from yesterday) | Writes |
| --- | --- | --- | --- | --- |
| 1 | `seir` | — | `signals["seir"]` ICU mortality multiplier | `state.epi` (EpiSnapshot) |
| 2 | `allocation` | `epi.new_hosp`, `epi.new_icu` | `signals["allocation"]["diverted"]` | `state.load` (HospitalLoad) |
| 3 | `fdna` | `epi.prevalence`, `load` | its own fatigue counters | `state.fdna` (Operability), `signals["seir"]` |
| 4 | `rerouting` | `fdna.hospital_P`, `load.occupancy_*` | its own diversion flags (hysteresis) | `state.diversion`, `signals["allocation"]` |
| 5 | `equity` | `fdna`, `diversion` | — | `state.access` (AccessSnapshot) |
| 6 | `recorder` | all snapshots | — | a row in its own buffer |

Why the one-day lag

Hospital overflow is a cycle: A diverts to B, B degrades, B diverts back. FDNA needs an acyclic graph. The loop keeps each day's graph acyclic (resource → hospital, always) and moves the cycle into time: rerouting decides on day *t*, allocation applies it on day *t+1*. Real diversions take hours to propagate, so a day is a fair resolution. If you need faster dynamics, raise the number of loop steps per day; don't add an edge backwards.

The core is the SEIR guide's `core.py` with one slot per layer added. Each slot holds a frozen snapshot written by exactly one module:

cascade/core.py

```
@dataclass
class SimState:
    day: int = 0
    # One slot per layer. Each is a frozen snapshot from cascade.contracts
    # (or EpiSnapshot), written by exactly one module and read by the others.
    epi: Any = None                       # EpiSnapshot, written by "seir"
    load: Any = None                      # HospitalLoad, written by "allocation"
    fdna: Any = None                      # Operability, written by "fdna"
    diversion: Any = None                 # DiversionStatus, written by "rerouting"
    access: Any = None                    # AccessSnapshot, written by "equity"
    hospitals: Any = None                 # kept for the SEIR-only tests
    # Feedback channel: signals[target_module][name] = value. A module writes
    # signals for a module earlier in the day; the target reads them next day.
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[Any] = field(default_factory=list)


class Module(Protocol):
    name: str

    def step(self, state: SimState, t: int) -> SimState: ...
```

## 05Contracts

Every snapshot lives in `cascade/contracts.py` (EpiSnapshot is re-exported from the SEIR adapter). These are the only types one layer may import from another. Arrays are indexed in `Network` order, so `load.occupancy_icu[h]` and `fdna.hospital_P[h]` refer to the same hospital.

| Snapshot | Field | Shape | Meaning |
| --- | --- | --- | --- |
| EpiSnapshot | `new_hosp`, `new_icu`, `prevalence`, `r_eff`, rates… | \[patch\] | See the SEIR guide, section 06 |
| HospitalLoad | `arrivals_ward`, `arrivals_icu` | \[patch, hospital\] | Patients placed today, after rerouting |
|  | `census_*`, `occupancy_*` | \[hospital\] | Baseline plus COVID patients; occupancy can exceed 1 (surge) |
|  | `diverted`, `overflow` | float | Patients moved off diverted hospitals; patients placed above free beds |
| Operability | `nodes`, `P` | \[node\] | FDNA operability 0–100, topological order |
|  | `hospital_P` | \[hospital\] | The hospital nodes' P, in Network order |
| DiversionStatus | `diverted`, `changed` | \[hospital\] bool, names | Who refuses arrivals tomorrow; who switched today |
| AccessSnapshot | `access`, `lost_person_days`, `weighted_loss` | \[patch\] | Share of usual care still open and operable; loss in person-days, raw and vulnerability-weighted |

cascade/contracts.py (excerpt)

```
@dataclass(frozen=True)
class Operability:
    """Written by FDNA. Operability 0-100 for every node in today's graph."""
    day: int
    nodes: tuple[str, ...]
    P: np.ndarray                   # [node]
    hospital_P: np.ndarray          # [hospital], same order as Network.hospitals

    def of(self, node: str) -> float:
        return float(self.P[self.nodes.index(node)])
```

Signals are the other half of the contract. They are plain dicts so a new feedback path costs nothing, which also makes them easy to misspell. Keep a list of them in this table and in code review:

| Signal | Writer → reader | Shape | Effect |
| --- | --- | --- | --- |
| `signals["seir"]["icu_mortality_multiplier"]` | fdna → seir | \[patch\] | Scales ICU death share via a `Signal` rate provider: `1 + 0.5 · (1 − ICU P / 100)` over each patch's hospitals |
| `signals["allocation"]["diverted"]` | rerouting → allocation | \[hospital\] bool | Hospitals that refuse new arrivals |

## 06Components

### Data ingestion

Ingestion is the only code that knows raw column names. It reads the project CSVs, joins them and writes one validated hospitals table that the rest of the system reads. MassGIS has beds but no CMS id; CMS has the CCN and the ER flag. A hand-made crosswalk links them, and campuses that share a CCN are summed.

data/crosswalk/hospitals.csv (excerpt)

```
id,ccn,massgis_name
MGH,220071,Massachusetts General Hospital
BMC,220031,Boston Medical Center - Menino Pavilion
BIDMC,220086,Beth Israel Deaconess Medical Center - West
BIDMC,220086,Beth Israel Deaconess Medical Center - East
TUFTS,220116,Tufts Medical Center
```

```
from cascade.data import build_from_project, to_specs
df = build_from_project("hackathon/healthcare", "data/crosswalk/hospitals.csv")
#      id     ccn  er  icu_beds  ward_beds  campuses
#   BIDMC  220086  True       95        574         2
#     MGH  220071  True      101        789         1
#    NEBH  220088 False       10        108         1      (no ER: gets no 911 traffic)
hospitals = to_specs(df, ids=["MGH", "BMC", "BIDMC", "TUFTS"])   # -> NetworkConfig.hospitals
```

- **Fail loudly on joins.** `build_hospitals` raises if a crosswalk name is missing from MassGIS or a CCN is missing from CMS. A silent left join drops a hospital from the network.
- **Raw stays raw.** Keep fetched files in `data/raw/`, write cleaned tables to `data/processed/`, and commit the processed files so a slow healthdata.gov doesn't block the team.
- **Still to add:** drive times (OSRM, or haversine × 1.4 from coordinates; the saved MassGIS extract has no geometry, so re-fetch with `returnGeometry=true`), Census ACS populations by patch and age, HHS weekly admissions for calibration, and SVI or EJ weights per patch. The EJ extract in the project is by block group with municipality names only, so neighborhood weights need the block-group geometry.

### Network

`Network` is the static picture: hospital ids, beds, ER flags, baseline occupancy and the `[patch, hospital]` drive-time matrix. It is built once and shared read-only. Its `gravity_shares(decay)` gives each patch's usual split across hospitals, `w ∝ beds · exp(−decay · minutes)` over hospitals with an ER. Allocation, FDNA's staff pools and equity all use the same shares, so "a hospital's catchment" means one thing everywhere.

### SEIR

Unchanged from the SEIR guide. The system only adds one rate override so FDNA feedback reaches the model:

```
base = Constant(epi.disease.by_age("p_death_icu", len(pop.ages)))
rate_overrides["p_death_icu"] = Product(
    base, Signal("icu_mortality_multiplier", default=1.0, per_patch=True))
engine = SEIREngine.from_config(epi, **rate_overrides)
```

### Allocation

Splits each patch's new admissions across hospitals with the gravity shares, hands patients bound for a diverted hospital to the rerouting assigner, and keeps a census per hospital. COVID patients leave at 1 / length of stay; non-COVID patients are held at each hospital's baseline occupancy. ICU transfers follow where each patch's ward patients went that day.

```
intended = epi.new_hosp[:, None] * self.shares
ward, diverted, overflow = self.assign(intended, closed, net.travel, free_ward)
row = ward.sum(axis=1, keepdims=True)
where = np.divide(ward, row, out=self.shares.copy(), where=row > 0)
icu = epi.new_icu[:, None] * where
```

Every admission lands somewhere: if all reachable hospitals are full, the patient goes to the nearest open one and counts as overflow. A test checks that arrivals summed over hospitals equal SEIR admissions every day.

### FDNA

Three files with one job each. `graph.py` holds the maths and nothing else. `resources.py` says how each source node's operability is set from today's state. `build.py` stamps out the city graph from a per-hospital template plus shared nodes.

```
SODP_j = (1/n) · Σ_i [ α_ij · P_i + 100 · (1 − α_ij) ]
CODP_j = min_i ( P_i + β_ij )
P_j    = min( SODP_j, CODP_j, cap_j )      cap_j: optional scenario cap, default 100
```

```
class FDNAGraph:
    def __init__(self, nodes, edges):
        ...
        if not nx.is_directed_acyclic_graph(g):
            raise ValueError(f"FDNA graph must be acyclic within a day; found cycle {nx.find_cycle(g)}")
        self.nodes = tuple(nx.lexicographical_topological_sort(g))
        # For each receiver: feeder indices and their alpha / beta arrays, precomputed once.

    def evaluate(self, base: dict[str, float]) -> np.ndarray:
        P = np.full(len(self.nodes), 100.0)
        for n, v in base.items():
            P[self.index[n]] = v
        for j, feeders, alpha, beta in self._plan:
            Pi = P[feeders]
            sodp = np.mean(alpha * Pi + 100.0 * (1.0 - alpha))
            codp = np.min(Pi + beta)
            P[j] = min(sodp, codp, base.get(self.nodes[j], 100.0))
        return np.clip(P, 0.0, 100.0)
```

Resource providers mirror the SEIR rate providers: each is called as `provider(state, network)` and returns P. Swap one and the module doesn't change.

| Node | Provider | Operability |
| --- | --- | --- |
| `{H}.staff` | `StaffPool` | `100 · (1 − 4 · catchment prevalence − 0.004 · days above 90% occupancy)` |
| `{H}.icu`, `{H}.ward` | `BedBuffer` | `100 · min(1, free / (0.10 · staffed beds))` |
| `ems` | `EMSFleet` | `100 · (1 − 1.5 · diverted share of arrivals)` |
| `oxygen_supplier` | `Fixed` | Constant; knocked out by events |
| `{H}.hospital` | (receiver) | FDNA over its staff, ICU, ward and the shared nodes |

All coefficients are assumptions and live in `FDNAConfig`, so the sensitivity analysis in the writeup is a loop over config values, not a code change.

### Rerouting

Two parts with separate jobs. The `Rerouting` module is the policy: a hospital goes on diversion when P \< 40 or occupancy > 95%, and comes off only when P > 50 and occupancy \< 90%, so it doesn't flap daily. At least `min_open` hospitals stay open, because diversion means nothing when everyone is on it. The `Assigner` is the mechanism allocation calls to move patients, behind a protocol so a greedy pass and an LP are interchangeable.

```
class Assigner(Protocol):
    def __call__(self, intended, closed, travel, free) -> tuple[np.ndarray, float, float]:
        """Return (final [patch, hospital], diverted, overflow)."""
```

Check with the team

Massachusetts ended routine ambulance diversion in 2009, as far as I know. If that holds, "diversion" here models EMS load-balancing and transfers rather than formal diversion status. The code doesn't change, but the pitch wording should, so confirm before the demo.

### Equity

`access[p] = Σ_h usual_share[p, h] · P_h / 100`, with diverted hospitals counted as 0. It measures how much of a neighborhood's usual hospital care is still open and operable. Lost person-days are weighted per patch by vulnerability (SVI or EJ), set in the scenario.

### Recorder and API

The recorder runs last, reads only snapshots, and builds one Dataset at the end. Because it touches every contract each day, it doubles as a check that no module broke one. `cascade.api` is the only thing the dashboard, the CLI and notebooks import:

```
from cascade import api
cfg = api.load("scenarios/boston_demo.yaml")
res = api.run(cfg)
res.summary()
# {'peak_occupancy_icu': 1.56, 'hospital_days_on_diversion': 195,
#  'diverted_patients': 831, 'overflow_patients': 173, 'deaths': 110, ...}
res.system.operability.to_pandas()      # time x hospital
res.epi.ds["new_hosp"]                  # the full SEIR output
api.criticality(cfg, workers=4)         # node, loss, extra_loss, sorted
```

```
python -m cascade run scenarios/boston_demo.yaml --out run.nc
python -m cascade criticality scenarios/boston_demo.yaml --workers 4
```

On the illustrative demo, BMC goes on diversion first (day 81), then Tufts (85), BIDMC (87) and MGH (88): a cascade from the smallest hospital near the hardest-hit neighborhoods outward. The criticality sweep ranks the shared oxygen supplier first, then MGH and BIDMC staff pools. These numbers come from made-up beds and drive times and only show that the mechanics work.

### Dashboard

The Streamlit app is a thin client: it edits a `SystemConfig` from sliders, calls `api.run`, and plots the Dataset. Results are cached on the config's JSON, so moving a slider back is instant.

```
@st.cache_data(show_spinner="Running scenario...")
def run_cached(cfg_json: str):
    res = api.run(api.SystemConfig.model_validate_json(cfg_json))
    return res.system, res.summary()

cfg = cfg.model_copy(update={
    "epi": cfg.epi.model_copy(update={"disease": d.model_copy(update={"r0": r0, "p_hosp": p_hosp})}),
    "events": cfg.events + ([Event(node=knock, value=knock_to, start=knock_day)] if knock != "(none)" else []),
})
system, summary = run_cached(cfg.model_dump_json())
```

It shows four headline metrics, operability and ICU occupancy by hospital, access by neighborhood, diversion days, and a button for the criticality ranking. Add the pydeck map next: hospital points coloured by operability and tract polygons coloured by access, both read from the same Dataset.

## 07Scenarios and wiring

A scenario is one YAML file. It can point at a separate SEIR file, so the epidemic and the network can be varied independently.

scenarios/boston_demo.yaml (illustrative numbers)

```
epi: boston_epi.yaml
network:
  hospitals:
    - {id: MGH,   ccn: "220071", ward_beds: 220, icu_beds: 30, baseline_occupancy: 0.70}
    - {id: BMC,   ccn: "220031", ward_beds: 70,  icu_beds: 10, baseline_occupancy: 0.70}
    - {id: BIDMC, ccn: "220086", ward_beds: 160, icu_beds: 28, baseline_occupancy: 0.70}
    - {id: TUFTS, ccn: "220116", ward_beds: 70,  icu_beds: 14, baseline_occupancy: 0.70}
  travel_minutes:          # rows: Dorchester, Roxbury, Back Bay
    - [20, 12, 18, 15]
    - [15,  8, 10, 10]
    - [10, 10,  8,  7]
fdna:
  per_hospital:
    - {src: staff, sod: 0.8, cod: 30}
    - {src: icu,   sod: 0.6, cod: 40}
    - {src: ward,  sod: 0.5, cod: 60}
  shared:
    - {node: ems, kind: ems, sod: 0.3, cod: 70}
    - {node: oxygen_supplier, kind: fixed, value: 100, sod: 0.5, cod: 20}
rerouting: {p_on: 40, p_off: 50, occ_on: 0.95, occ_off: 0.90, min_open: 1}
equity:
  vulnerability: {Dorchester: 1.3, Roxbury: 1.5, "Back Bay": 0.8}
events: []        # e.g. - {node: BMC.staff, value: 20, start: 30} for a staff outbreak
```

`build()` in `cascade/scenario.py` is the composition root. It is the only function that imports every module, and the only place module order is written down:

```
def build(cfg: SystemConfig, overrides=None):
    net = Network.from_config(cfg.network, pop.patches)
    engine = SEIREngine.from_config(epi, **rate_overrides)
    seir = SEIRModule(engine, epi.seeding)
    alloc = Allocation(net, cfg.allocation.decay, epi.disease.los_ward, epi.disease.los_icu)
    recorder = Recorder(net)
    sim = Simulation([
        seir,
        alloc,
        FDNAModule(net, alloc.shares, cfg.fdna, cfg.events, overrides),
        Rerouting(net, **cfg.rerouting.model_dump()),
        Equity(net, alloc.shares, pop.N.sum(axis=1), vuln),
        recorder,
    ])
    return sim, seir, recorder
```

## 08Repository layout

```
cascade-reference/
  cascade/
    core.py            SimState, Module, Simulation
    contracts.py       HospitalLoad, Operability, DiversionStatus, AccessSnapshot (+ EpiSnapshot)
    network.py         NetworkConfig, Network, gravity shares
    data/ingest.py     raw CSVs -> hospitals table, validation
    epi/               SEIR layer (see the SEIR guide)
    allocation.py      admissions -> hospitals, census
    fdna/
      graph.py         Edge, FDNAGraph: the operability maths
      resources.py     StaffPool, BedBuffer, EMSFleet, Fixed
      build.py         FDNAConfig, per-hospital template -> city graph
      module.py        FDNAModule, Event
      criticality.py   knock-out sweep
    reroute.py         Rerouting policy, Assigner, GreedyAssigner
    equity.py          access per patch
    recorder.py        snapshots -> xarray
    scenario.py        SystemConfig, build()
    api.py             run(), criticality(), RunResult
    __main__.py        CLI
  app/streamlit_app.py
  data/crosswalk/hospitals.csv     (raw/ and processed/ go here too)
  scenarios/           example_3patch.yaml, boston_epi.yaml, boston_demo.yaml
  tests/               test_epi.py (9), test_system.py (11)
  bench.py, bench_system.py
```

Dependencies point inward: the dashboard imports `api`; `api` imports `scenario`; `scenario` imports the layers; layers import only `core`, `contracts` and `network` (allocation also imports the `Assigner` from `reroute`). A test parses the imports and fails if FDNA, allocation, rerouting or equity reach into the SEIR engine or each other.

## 09Extending the system

### A new module (e.g. a strain forecast)

Add a contract, write a class with `name` and `step`, and insert it in `build()`. No existing module changes.

```
@dataclass(frozen=True)
class StrainForecast:              # in contracts.py
    day: int
    p_divert_14d: np.ndarray       # [hospital]

class Forecast:
    name = "forecast"
    def step(self, state, t):
        state.forecast = StrainForecast(t, self.model.predict(state.epi, state.load))
        return state
```

Give `SimState` a `forecast` slot and the recorder a column for it.

### A new FDNA node

Shared nodes are config. A per-hospital node is one template edge plus a provider:

```
fdna:
  per_hospital:
    - {src: ventilators, sod: 0.7, cod: 30}     # then register a provider for "{H}.ventilators" in build.py
  shared:
    - {node: partners_staff_pool, kind: fixed, sod: 0.4, cod: 50, hospitals: [MGH, BWH, FAULKNER]}
```

### A load-balancing assigner

Write a class with the `Assigner` signature that solves `min Σ (travel + λ · load) · x` with `scipy.optimize.linprog`, and pass it as `Allocation(..., assigner=LPAssigner())`.

### A resource optimizer

Treat `api.run` as the objective function: the optimizer edits bed counts or staff in a `SystemConfig`, calls `run`, and reads `summary()["weighted_access_loss"]`. It sits outside the loop and needs no new module.

### Stochastic ensembles

Set `sim.stochastic: true` and a seed per run, then map `api.run` over seeds in a process pool. Stack the Datasets along a new `run` dimension for uncertainty bands.

## 10Scaling

| Patches × ages × hospitals | 365-day coupled run |
| --- | --- |
| 3 × 3 × 4 | 0.41 s (measured) |
| 15 × 3 × 20 | 0.56 s (measured) |
| 200 × 9 × 20 | 2.1 s (measured) |
| 200 × 9 × 60 | 1.9 s (measured) |
| Criticality sweep, demo (14 nodes × 150 days) | 2.2 s, one process (measured) |

Measured with `bench_system.py` on synthetic networks on the cloud machine I used. The SEIR step dominates; FDNA, allocation and rerouting are small next to it at these sizes.

- **Sweeps and ensembles** are embarrassingly parallel: `api.criticality(cfg, workers=n)` already uses a process pool. Keep configs picklable (pydantic models are).
- **Thousands of FDNA nodes**: the per-node loop in `evaluate` becomes the hot path. Group receivers by topological level and evaluate each level with sparse matrix products.
- **Many hospitals with diversion**: the greedy assigner loops over patches; switch to the LP assigner or vectorize by sorting travel times once.
- **Dashboard**: cache on config JSON, and precompute the criticality table for the default scenario rather than on every click.

## 11Testing

The SEIR tests from the SEIR guide still pass unchanged (9). The system adds eleven:

| Test | What it proves |
| --- | --- |
| Ingestion joins the project files | MGH has 101 ICU beds and CCN 220071; BIDMC's two campuses sum to 95 ICU beds; NEBH has no ER |
| FDNA formula matches a hand calculation | SOD and COD terms, including a critical feeder capping the receiver |
| FDNA rejects cycles | A cyclic graph fails at build time, not mid-run |
| Every admission lands somewhere | Hospital arrivals equal SEIR admissions every day |
| Assigner sends patients to the nearest open hospital | Fills free beds by drive time, then spills to the next |
| Strain cascades through diversion | Every hospital diverts at some point, not all on the same day, and `min_open` holds |
| A staff knock-out spreads | BMC's operability drops, neighbors take more patients, access loss rises |
| FDNA feedback reaches SEIR | ICU strain raises deaths compared with feedback turned off |
| Criticality ranks nodes | Sorted by extra loss, every knock-out costs something |
| Runs are reproducible | Same config, identical Dataset |
| Layers only import contracts | Parses imports; FDNA, allocation, rerouting and equity never import the SEIR engine or each other |

```
cd cascade-reference && pip install -r requirements.txt && python -m pytest -q
....................                                     [100%]
20 passed in 10.3s
```

I also ran the dashboard headless with Streamlit's `AppTest`: it renders, a knock-out selection reruns it, and the criticality button returns the ranked table, with no exceptions.

## 12Rules and pitfalls

- **One writer per slot.** If two modules want to write `state.load`, one of them is a different module.
- **Add fields, never rename.** The recorder and the dashboard read snapshot fields by name.
- **Feedback goes through signals, one day late.** Never read a slot written later in the day; it holds yesterday's value and the bug is silent.
- **Index order comes from Network.** Don't sort hospitals or patches anywhere else.
- **Only `build()` knows every module**, and only `api` is imported by the UI.
- **Assumptions live in config**, not code: FDNA weights, staff-loss coefficients, thresholds, vulnerability weights.
- **Stateful modules are rebuilt per run.** Allocation's census and the staff pools' fatigue counters carry over between days, so a criticality sweep calls `build()` for every run. Never reuse a Simulation.
- **Occupancy above 100% is allowed** and reported as overflow. Capping it would hide the surge the model exists to show.
- **Label it a planning simulator** in the UI. The demo numbers are illustrative until beds, drive times and weights come from data.

## 13Full source

Every file the system adds on top of the SEIR package, as tested. The SEIR files are in the SEIR guide. Also in the project files under `hackathon/cascade-reference/`.

cascade/core.py

```
"""Shared simulation state and the module interface every layer implements."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SimState:
    day: int = 0
    # One slot per layer. Each is a frozen snapshot from cascade.contracts
    # (or EpiSnapshot), written by exactly one module and read by the others.
    epi: Any = None                       # EpiSnapshot, written by "seir"
    load: Any = None                      # HospitalLoad, written by "allocation"
    fdna: Any = None                      # Operability, written by "fdna"
    diversion: Any = None                 # DiversionStatus, written by "rerouting"
    access: Any = None                    # AccessSnapshot, written by "equity"
    hospitals: Any = None                 # kept for the SEIR-only tests
    # Feedback channel: signals[target_module][name] = value. A module writes
    # signals for a module earlier in the day; the target reads them next day.
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[Any] = field(default_factory=list)


class Module(Protocol):
    name: str

    def step(self, state: SimState, t: int) -> SimState: ...


class Simulation:
    def __init__(self, modules: list[Module]):
        names = [m.name for m in modules]
        if len(set(names)) != len(names):
            raise ValueError(f"module names must be unique, got {names}")
        self.modules = modules

    def module(self, name: str) -> Module:
        return next(m for m in self.modules if m.name == name)

    def run(self, days: int, state: SimState | None = None) -> SimState:
        state = state or SimState()
        for t in range(days):
            state.day = t
            for m in self.modules:
                state = m.step(state, t)
        return state
```

cascade/contracts.py

```
"""Daily snapshots that modules exchange through SimState.

These are the only types one layer may import from another. Add fields;
never rename or remove one. Arrays are indexed by the order in Network
(patches, hospitals) or by Operability.nodes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .epi.adapter import EpiSnapshot  # re-exported: the SEIR side of the contract


@dataclass(frozen=True)
class HospitalLoad:
    """Written by allocation. Where today's patients went and how full hospitals are."""
    day: int
    arrivals_ward: np.ndarray       # [patch, hospital] COVID ward admissions placed today
    arrivals_icu: np.ndarray        # [patch, hospital] ICU transfers placed today
    census_ward: np.ndarray         # [hospital] all ward patients (baseline + COVID)
    census_icu: np.ndarray          # [hospital]
    occupancy_ward: np.ndarray      # [hospital] census / staffed beds, can exceed 1
    occupancy_icu: np.ndarray       # [hospital]
    diverted: float                 # patients moved away from a hospital on diversion
    overflow: float                 # patients placed above a hospital's free capacity


@dataclass(frozen=True)
class Operability:
    """Written by FDNA. Operability 0-100 for every node in today's graph."""
    day: int
    nodes: tuple[str, ...]
    P: np.ndarray                   # [node]
    hospital_P: np.ndarray          # [hospital], same order as Network.hospitals

    def of(self, node: str) -> float:
        return float(self.P[self.nodes.index(node)])


@dataclass(frozen=True)
class DiversionStatus:
    """Written by rerouting. Which hospitals refuse new arrivals tomorrow."""
    day: int
    diverted: np.ndarray            # [hospital] bool
    changed: tuple[str, ...]        # hospitals that went on or off diversion today


@dataclass(frozen=True)
class AccessSnapshot:
    """Written by equity. Effective access to hospital care per patch."""
    day: int
    access: np.ndarray              # [patch] 0-1
    lost_person_days: np.ndarray    # [patch] population * (1 - access) for today
    weighted_loss: np.ndarray       # [patch] lost_person_days * vulnerability weight


__all__ = ["EpiSnapshot", "HospitalLoad", "Operability", "DiversionStatus", "AccessSnapshot"]
```

cascade/network.py

```
"""Static description of the hospital network: who exists, how big, how far.

Built once per scenario from processed data and shared read-only by
allocation, FDNA, rerouting and equity.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, Field, model_validator


class HospitalSpec(BaseModel):
    id: str                          # short key used in node names, e.g. "MGH"
    ccn: str | None = None           # CMS certification number, join key to HHS
    name: str = ""
    ward_beds: float = Field(gt=0)
    icu_beds: float = Field(ge=0)
    er: bool = True
    baseline_occupancy: float = Field(default=0.75, ge=0, lt=1)   # non-COVID share of beds in use


class NetworkConfig(BaseModel):
    hospitals: list[HospitalSpec]
    # travel_minutes[patch][hospital], in the patch order of the epi config
    travel_minutes: list[list[float]]

    @model_validator(mode="after")
    def _check(self) -> "NetworkConfig":
        ids = [h.id for h in self.hospitals]
        if len(set(ids)) != len(ids):
            raise ValueError("hospital ids must be unique")
        if any(len(row) != len(ids) for row in self.travel_minutes):
            raise ValueError("each travel_minutes row needs one value per hospital")
        return self


@dataclass(frozen=True)
class Network:
    patches: tuple[str, ...]
    hospitals: tuple[str, ...]
    ward_beds: np.ndarray            # [hospital]
    icu_beds: np.ndarray             # [hospital]
    has_er: np.ndarray               # [hospital] bool
    baseline_occupancy: np.ndarray   # [hospital]
    travel: np.ndarray               # [patch, hospital] minutes

    @classmethod
    def from_config(cls, cfg: NetworkConfig, patches) -> "Network":
        travel = np.asarray(cfg.travel_minutes, dtype=float)
        if travel.shape[0] != len(patches):
            raise ValueError(f"travel_minutes has {travel.shape[0]} rows for {len(patches)} patches")
        hs = cfg.hospitals
        return cls(
            patches=tuple(patches), hospitals=tuple(h.id for h in hs),
            ward_beds=np.array([h.ward_beds for h in hs], float),
            icu_beds=np.array([h.icu_beds for h in hs], float),
            has_er=np.array([h.er for h in hs], bool),
            baseline_occupancy=np.array([h.baseline_occupancy for h in hs], float),
            travel=travel,
        )

    @property
    def n_hospitals(self) -> int:
        return len(self.hospitals)

    def gravity_shares(self, decay: float, open_mask: np.ndarray | None = None) -> np.ndarray:
        """Share of each patch's admissions going to each hospital: beds * exp(-decay * minutes)."""
        mask = self.has_er if open_mask is None else self.has_er & open_mask
        w = (self.ward_beds + self.icu_beds) * np.exp(-decay * self.travel) * mask
        total = w.sum(axis=1, keepdims=True)
        return np.divide(w, total, out=np.zeros_like(w), where=total > 0)
```

cascade/data/ingest.py

```
"""Raw project CSVs -> one validated hospitals table.

Ingestion is the only code that knows raw column names. Everything after it
reads the processed table, so a source can change format without touching
the model.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..network import HospitalSpec

HOSPITAL_COLUMNS = ["id", "ccn", "name", "county", "er", "overall_rating",
                    "icu_beds", "ward_beds", "campuses"]


def load_cms(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"facility_id": str})
    return df.rename(columns={"facility_id": "ccn", "facility_name": "cms_name"})


def load_massgis(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df.rename(columns={"name": "massgis_name", "med_surg_beds": "ward_beds"})


def build_hospitals(cms: pd.DataFrame, massgis: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Join CMS (CCN, ER flag) to MassGIS (beds) through a hand-made crosswalk.

    Several MassGIS campuses can share one CCN (BIDMC East and West); their
    beds are summed.
    """
    xw = crosswalk.astype({"ccn": str})
    missing = set(xw.massgis_name) - set(massgis.massgis_name)
    if missing:
        raise ValueError(f"crosswalk names not in MassGIS: {sorted(missing)}")
    missing = set(xw.ccn) - set(cms.ccn)
    if missing:
        raise ValueError(f"crosswalk CCNs not in CMS: {sorted(missing)}")
    beds = (xw.merge(massgis, on="massgis_name")
              .groupby(["id", "ccn"], as_index=False)
              .agg(icu_beds=("icu_beds", "sum"), ward_beds=("ward_beds", "sum"),
                   campuses=("massgis_name", "count")))
    out = beds.merge(cms[["ccn", "cms_name", "county", "emergency", "overall_rating"]], on="ccn")
    out = out.rename(columns={"cms_name": "name"})
    out["er"] = out.pop("emergency").eq("Yes")
    out = out[HOSPITAL_COLUMNS].sort_values("id", ignore_index=True)
    validate_hospitals(out)
    return out


def validate_hospitals(df: pd.DataFrame) -> None:
    if list(df.columns) != HOSPITAL_COLUMNS:
        raise ValueError(f"hospitals table columns {list(df.columns)} != {HOSPITAL_COLUMNS}")
    if df.id.duplicated().any():
        raise ValueError("duplicate hospital ids")
    if (df[["icu_beds", "ward_beds"]] < 0).any().any():
        raise ValueError("negative bed counts")


def to_specs(df: pd.DataFrame, ids: list[str] | None = None,
             baseline_occupancy: float = 0.75) -> list[HospitalSpec]:
    """Hospitals table -> NetworkConfig.hospitals. Drops sites with no ward beds."""
    rows = df if ids is None else df.set_index("id").loc[ids].reset_index()
    return [HospitalSpec(id=r.id, ccn=r.ccn, name=r.name, ward_beds=r.ward_beds,
                         icu_beds=r.icu_beds, er=bool(r.er), baseline_occupancy=baseline_occupancy)
            for r in rows.itertuples() if r.ward_beds > 0]


def build_from_project(healthcare_dir: str | Path, crosswalk_path: str | Path) -> pd.DataFrame:
    d = Path(healthcare_dir)
    return build_hospitals(load_cms(d / "cms-hospitals" / "data.csv"),
                           load_massgis(d / "hospitals" / "data.csv"),
                           pd.read_csv(crosswalk_path, dtype=str))
```

cascade/allocation.py

```
"""Turns per-patch admissions into per-hospital arrivals and census."""
from __future__ import annotations

import numpy as np

from .contracts import HospitalLoad
from .core import SimState
from .network import Network
from .reroute import Assigner, GreedyAssigner


class Allocation:
    """Gravity model for where patients go, then census bookkeeping per hospital.

    COVID census leaves at 1 / length of stay. Non-COVID patients are held at
    each hospital's baseline occupancy.
    """

    name = "allocation"

    def __init__(self, network: Network, decay: float = 0.08, los_ward: float = 5.0,
                 los_icu: float = 9.0, assigner: Assigner | None = None):
        self.net = network
        self.decay = decay
        self.keep_ward = np.exp(-1.0 / los_ward)
        self.keep_icu = np.exp(-1.0 / los_icu)
        self.assign = assigner or GreedyAssigner()
        self.shares = network.gravity_shares(decay)               # [patch, hospital]
        self.covid_ward = np.zeros(network.n_hospitals)
        self.covid_icu = np.zeros(network.n_hospitals)

    def step(self, state: SimState, t: int) -> SimState:
        epi, net = state.epi, self.net
        closed = np.asarray(state.signals.get(self.name, {}).get(
            "diverted", np.zeros(net.n_hospitals, bool)))
        base_ward = net.baseline_occupancy * net.ward_beds
        base_icu = net.baseline_occupancy * net.icu_beds

        self.covid_ward *= self.keep_ward
        self.covid_icu *= self.keep_icu
        free_ward = net.ward_beds - base_ward - self.covid_ward

        intended = epi.new_hosp[:, None] * self.shares
        ward, diverted, overflow = self.assign(intended, closed, net.travel, free_ward)
        # ICU transfers follow where each patch's ward patients went today.
        row = ward.sum(axis=1, keepdims=True)
        where = np.divide(ward, row, out=self.shares.copy(), where=row > 0)
        icu = epi.new_icu[:, None] * where

        self.covid_ward += ward.sum(axis=0)
        self.covid_icu += icu.sum(axis=0)
        census_ward = base_ward + self.covid_ward
        census_icu = base_icu + self.covid_icu
        state.load = HospitalLoad(
            day=t, arrivals_ward=ward, arrivals_icu=icu,
            census_ward=census_ward, census_icu=census_icu,
            occupancy_ward=census_ward / net.ward_beds,
            occupancy_icu=np.divide(census_icu, net.icu_beds, out=np.zeros_like(census_icu),
                                    where=net.icu_beds > 0),
            diverted=diverted, overflow=overflow,
        )
        return state
```

cascade/fdna/graph.py

```
"""FDNA dependency graph and the operability calculation (Garvey and Pinto).

For a receiver j with feeders i:
    SODP_j = (1/n) * sum_i [ alpha_ij * P_i + 100 * (1 - alpha_ij) ]
    CODP_j = min_i ( P_i + beta_ij )
    P_j    = min( SODP_j, CODP_j )
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    sod: float          # strength of dependency, alpha in [0, 1]
    cod: float = 100.0  # criticality of dependency, beta in [0, 100]; 100 = no cap

    def __post_init__(self):
        if not 0.0 <= self.sod <= 1.0:
            raise ValueError(f"SOD for {self.src}->{self.dst} must be in [0, 1]")
        if not 0.0 <= self.cod <= 100.0:
            raise ValueError(f"COD for {self.src}->{self.dst} must be in [0, 100]")


class FDNAGraph:
    """Compiled once per scenario: topological order plus feeder index arrays."""

    def __init__(self, nodes: list[str], edges: list[Edge]):
        g = nx.DiGraph()
        g.add_nodes_from(nodes)
        for e in edges:
            if e.src not in g or e.dst not in g:
                raise ValueError(f"edge {e.src}->{e.dst} names an unknown node")
            g.add_edge(e.src, e.dst, sod=e.sod, cod=e.cod)
        if not nx.is_directed_acyclic_graph(g):
            cycle = nx.find_cycle(g)
            raise ValueError(f"FDNA graph must be acyclic within a day; found cycle {cycle}")
        self.graph = g
        self.nodes = tuple(nx.lexicographical_topological_sort(g))
        self.index = {n: k for k, n in enumerate(self.nodes)}
        self.sources = tuple(n for n in self.nodes if g.in_degree(n) == 0)
        # For each receiver: feeder indices and their alpha / beta arrays.
        self._plan = []
        for n in self.nodes:
            preds = list(g.predecessors(n))
            if preds:
                self._plan.append((self.index[n],
                                   np.array([self.index[p] for p in preds]),
                                   np.array([g[p][n]["sod"] for p in preds]),
                                   np.array([g[p][n]["cod"] for p in preds])))

    def evaluate(self, base: dict[str, float]) -> np.ndarray:
        """Operability of every node, in self.nodes order.

        base gives P for source nodes (required) and an optional self-effectiveness
        cap for receivers (e.g. a scenario that knocks a hospital out directly).
        """
        missing = [n for n in self.sources if n not in base]
        if missing:
            raise KeyError(f"no operability given for source nodes {missing}")
        P = np.full(len(self.nodes), 100.0)
        for n, v in base.items():
            P[self.index[n]] = v
        for j, feeders, alpha, beta in self._plan:
            Pi = P[feeders]
            sodp = np.mean(alpha * Pi + 100.0 * (1.0 - alpha))
            codp = np.min(Pi + beta)
            cap = base.get(self.nodes[j], 100.0)
            P[j] = min(sodp, codp, cap)
        return np.clip(P, 0.0, 100.0)
```

cascade/fdna/resources.py

```
"""How each source node's operability is set from today's state.

A resource provider is called as provider(state, network) and returns P in
[0, 100]. Like SEIR rate providers, any one can be swapped without touching
the FDNA module.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np

from ..core import SimState
from ..network import Network


class ResourceProvider(Protocol):
    def __call__(self, state: SimState, net: Network) -> float: ...


class StaffPool:
    """Staff available at hospital h: falls with community prevalence and with fatigue.

    absent = absence_per_prevalence * catchment prevalence
           + fatigue_per_day * consecutive days above fatigue_occupancy
    """

    def __init__(self, h: int, shares: np.ndarray, absence_per_prevalence: float = 4.0,
                 fatigue_per_day: float = 0.004, fatigue_occupancy: float = 0.9):
        self.h, self.w = h, shares[:, h] / max(shares[:, h].sum(), 1e-12)
        self.k_prev, self.k_fat, self.occ = absence_per_prevalence, fatigue_per_day, fatigue_occupancy
        self.hot_days = 0

    def __call__(self, state, net):
        prev = float(self.w @ state.epi.prevalence)
        occ = max(state.load.occupancy_ward[self.h], state.load.occupancy_icu[self.h])
        self.hot_days = self.hot_days + 1 if occ > self.occ else 0
        absent = self.k_prev * prev + self.k_fat * self.hot_days
        return 100.0 * float(np.clip(1.0 - absent, 0.0, 1.0))


class BedBuffer:
    """P = 100 * min(1, free beds / (buffer * staffed beds)). Full at 0 free beds."""

    def __init__(self, h: int, kind: str, buffer: float = 0.10):
        self.h, self.kind, self.buffer = h, kind, buffer

    def __call__(self, state, net):
        beds = (net.icu_beds if self.kind == "icu" else net.ward_beds)[self.h]
        census = (state.load.census_icu if self.kind == "icu" else state.load.census_ward)[self.h]
        if beds <= 0:
            return 100.0
        return 100.0 * float(np.clip((beds - census) / (self.buffer * beds), 0.0, 1.0))


class EMSFleet:
    """Citywide ambulance capacity: drops as diversions lengthen transports."""

    def __init__(self, loss_per_diverted_share: float = 1.5):
        self.k = loss_per_diverted_share

    def __call__(self, state, net):
        total = float(state.load.arrivals_ward.sum())
        share = state.load.diverted / total if total > 0 else 0.0
        return 100.0 * float(np.clip(1.0 - self.k * share, 0.0, 1.0))


class Fixed:
    """Constant operability, e.g. a shared supplier with no data behind it yet."""

    def __init__(self, value: float = 100.0):
        self.value = value

    def __call__(self, state, net):
        return self.value
```

cascade/fdna/build.py

```
"""Builds the city's FDNA graph from a per-hospital template plus shared nodes."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..network import Network
from .graph import Edge, FDNAGraph
from .resources import BedBuffer, EMSFleet, Fixed, StaffPool


class EdgeSpec(BaseModel):
    src: str
    dst: str = "hospital"
    sod: float = Field(ge=0, le=1)
    cod: float = Field(default=100.0, ge=0, le=100)


class SharedNode(BaseModel):
    node: str
    kind: str = "fixed"          # "ems" or "fixed"
    value: float = 100.0         # for kind="fixed"
    sod: float = Field(ge=0, le=1)
    cod: float = Field(default=100.0, ge=0, le=100)
    hospitals: list[str] | None = None   # None = feeds every hospital


class FDNAConfig(BaseModel):
    # Edges inside each hospital. Node names are local: "staff", "icu", "ward", "hospital".
    per_hospital: list[EdgeSpec] = [
        EdgeSpec(src="staff", sod=0.8, cod=30),
        EdgeSpec(src="icu", sod=0.6, cod=40),
        EdgeSpec(src="ward", sod=0.5, cod=60),
    ]
    shared: list[SharedNode] = [SharedNode(node="ems", kind="ems", sod=0.3, cod=70)]
    staff_absence_per_prevalence: float = 4.0
    staff_fatigue_per_day: float = 0.004
    bed_buffer: float = 0.10
    # Feedback to SEIR: ICU death multiplier = 1 + icu_strain_mortality * (1 - ICU P / 100)
    icu_strain_mortality: float = 0.5


def build_graph(cfg: FDNAConfig, net: Network, shares) -> tuple[FDNAGraph, dict]:
    nodes, edges, providers = [], [], {}
    for h, hid in enumerate(net.hospitals):
        local = {"staff", "icu", "ward", "hospital"} | {e.src for e in cfg.per_hospital}
        nodes += [f"{hid}.{n}" for n in sorted(local)]
        for e in cfg.per_hospital:
            edges.append(Edge(f"{hid}.{e.src}", f"{hid}.{e.dst}", e.sod, e.cod))
        providers[f"{hid}.staff"] = StaffPool(h, shares, cfg.staff_absence_per_prevalence,
                                              cfg.staff_fatigue_per_day)
        providers[f"{hid}.icu"] = BedBuffer(h, "icu", cfg.bed_buffer)
        providers[f"{hid}.ward"] = BedBuffer(h, "ward", cfg.bed_buffer)
    for s in cfg.shared:
        nodes.append(s.node)
        providers[s.node] = EMSFleet() if s.kind == "ems" else Fixed(s.value)
        for hid in s.hospitals or net.hospitals:
            edges.append(Edge(s.node, f"{hid}.hospital", s.sod, s.cod))
    return FDNAGraph(nodes, edges), providers
```

cascade/fdna/module.py

```
"""FDNA as a Module in the daily loop."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..contracts import Operability
from ..core import SimState
from ..network import Network
from .build import FDNAConfig, build_graph


class Event(BaseModel):
    """Scenario knock-out: cap a node's operability at `value` from day `start` to `end`."""
    node: str
    value: float = 0.0
    start: int = 0
    end: int | None = None


class FDNAModule:
    name = "fdna"

    def __init__(self, network: Network, shares: np.ndarray, cfg: FDNAConfig | None = None,
                 events: list[Event] = (), overrides: dict[str, float] | None = None):
        self.net, self.shares = network, shares
        self.cfg = cfg or FDNAConfig()
        self.graph, self.providers = build_graph(self.cfg, network, shares)
        self.events = list(events)
        self.overrides = dict(overrides or {})      # whole-run caps, used by the criticality sweep
        unknown = ({e.node for e in self.events} | set(self.overrides)) - set(self.graph.nodes)
        if unknown:
            raise ValueError(f"events or overrides name unknown FDNA nodes: {sorted(unknown)}")
        self._hosp_idx = np.array([self.graph.index[f"{h}.hospital"] for h in network.hospitals])
        self._icu_idx = np.array([self.graph.index[f"{h}.icu"] for h in network.hospitals])

    def step(self, state: SimState, t: int) -> SimState:
        base = {n: p(state, self.net) for n, p in self.providers.items()}
        for e in self.events:
            if e.start <= t and (e.end is None or t < e.end):
                base[e.node] = min(base.get(e.node, 100.0), e.value)
        for n, v in self.overrides.items():
            base[n] = min(base.get(n, 100.0), v)
        P = self.graph.evaluate(base)
        state.fdna = Operability(day=t, nodes=self.graph.nodes, P=P, hospital_P=P[self._hosp_idx])
        # Feedback for tomorrow's SEIR step: ICU strain in each patch's hospitals.
        icu_P = self.shares @ P[self._icu_idx]                       # [patch]
        mult = 1.0 + self.cfg.icu_strain_mortality * (1.0 - icu_P / 100.0)
        state.signals.setdefault("seir", {})["icu_mortality_multiplier"] = mult
        return state
```

cascade/fdna/criticality.py

```
"""Knock out each node in turn and rank nodes by the citywide loss it causes."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Iterable

import pandas as pd


def criticality(run: Callable[[dict[str, float]], float], nodes: Iterable[str],
                level: float = 0.0, workers: int = 1) -> pd.DataFrame:
    """run(overrides) -> scalar loss. Must be a top-level function if workers > 1."""
    nodes = list(nodes)
    baseline = run({})
    jobs = [{n: level} for n in nodes]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            losses = list(ex.map(run, jobs))
    else:
        losses = [run(j) for j in jobs]
    df = pd.DataFrame({"node": nodes, "loss": losses})
    df["extra_loss"] = df["loss"] - baseline
    return df.sort_values("extra_loss", ascending=False, ignore_index=True)
```

cascade/reroute.py

```
"""Diversion rule and the assignment that moves patients off diverted hospitals.

The Rerouting module decides on day t which hospitals go on diversion.
Allocation applies that decision on day t+1 by calling an Assigner. That
one-day lag is what keeps each day's FDNA graph acyclic.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np

from .contracts import DiversionStatus
from .core import SimState
from .network import Network


class Assigner(Protocol):
    def __call__(self, intended: np.ndarray, closed: np.ndarray, travel: np.ndarray,
                 free: np.ndarray) -> tuple[np.ndarray, float, float]:
        """Return (final [patch, hospital], diverted, overflow)."""


class GreedyAssigner:
    """Nearest open hospital with free beds first; whatever is left goes to the nearest open one.

    Exact for the tiny problems we have. Swap in an LP (scipy.optimize.linprog)
    if you want a load-balanced optimum; the signature stays the same.
    """

    def __call__(self, intended, closed, travel, free):
        final = intended.copy()
        if not closed.any():
            return final, 0.0, float(np.clip(intended.sum(0) - free, 0, None).sum())
        open_idx = np.flatnonzero(~closed)
        if open_idx.size == 0:            # everyone on diversion: nobody can refuse
            return final, 0.0, float(np.clip(intended.sum(0) - free, 0, None).sum())
        moved = intended[:, closed].sum(axis=1)          # [patch]
        final[:, closed] = 0.0
        room = np.clip(free - final.sum(axis=0), 0, None)
        overflow = 0.0
        for p in np.argsort(-moved):                      # biggest flows first
            left = moved[p]
            for h in open_idx[np.argsort(travel[p, open_idx])]:
                take = min(left, room[h])
                final[p, h] += take
                room[h] -= take
                left -= take
                if left <= 1e-12:
                    break
            if left > 1e-12:
                nearest = open_idx[np.argmin(travel[p, open_idx])]
                final[p, nearest] += left
                overflow += left
        overflow += float(np.clip(intended[:, ~closed].sum(0) - free[~closed], 0, None).sum())
        return final, float(moved.sum()), overflow


class Rerouting:
    """Puts a hospital on diversion when operability or occupancy crosses a threshold.

    Hysteresis (separate on and off thresholds) stops hospitals flapping daily.
    """

    name = "rerouting"

    def __init__(self, network: Network, p_on: float = 40.0, p_off: float = 50.0,
                 occ_on: float = 0.95, occ_off: float = 0.90, min_open: int = 1):
        self.net = network
        self.p_on, self.p_off, self.occ_on, self.occ_off = p_on, p_off, occ_on, occ_off
        self.min_open = min_open
        self.diverted = np.zeros(network.n_hospitals, bool)

    def step(self, state: SimState, t: int) -> SimState:
        P = state.fdna.hospital_P
        occ = np.maximum(state.load.occupancy_ward, state.load.occupancy_icu)
        go_on = (P < self.p_on) | (occ > self.occ_on)
        go_off = (P > self.p_off) & (occ < self.occ_off)
        new = np.where(self.diverted, ~go_off, go_on)
        # Diversion only works if somewhere stays open: keep the least strained hospitals open.
        n_open = int((~new).sum())
        if n_open < self.min_open:
            strain = occ - P / 100.0
            for h in np.argsort(strain):
                if new[h] and n_open < self.min_open:
                    new[h] = False
                    n_open += 1
        changed = tuple(h for h, a, b in zip(self.net.hospitals, self.diverted, new) if a != b)
        self.diverted = new
        state.signals.setdefault("allocation", {})["diverted"] = new.copy()
        state.diversion = DiversionStatus(day=t, diverted=new.copy(), changed=changed)
        return state
```

cascade/equity.py

```
"""Access to care per patch, weighted by social vulnerability."""
from __future__ import annotations

import numpy as np

from .contracts import AccessSnapshot
from .core import SimState
from .network import Network


class Equity:
    """access[p] = sum_h usual_share[p, h] * P_h / 100, counting diverted hospitals as 0.

    usual_share is the no-diversion gravity split, so access measures how much
    of a neighborhood's usual hospital care is still open and operable today.
    """

    name = "equity"

    def __init__(self, network: Network, shares: np.ndarray, population: np.ndarray,
                 vulnerability: np.ndarray | None = None):
        self.shares, self.pop = shares, population
        self.vuln = np.ones(len(network.patches)) if vulnerability is None else vulnerability

    def step(self, state: SimState, t: int) -> SimState:
        open_P = state.fdna.hospital_P * ~state.diversion.diverted
        access = self.shares @ (open_P / 100.0)
        lost = self.pop * (1.0 - access)
        state.access = AccessSnapshot(day=t, access=access, lost_person_days=lost,
                                      weighted_loss=lost * self.vuln)
        return state
```

cascade/recorder.py

```
"""Collects every layer's daily snapshot into one labelled xarray Dataset."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .core import SimState
from .network import Network


class Recorder:
    """Runs last each day. Reads snapshots only, so it doubles as a contract check."""

    name = "recorder"

    def __init__(self, network: Network):
        self.net = network
        self.rows: list[dict] = []
        self.nodes: tuple[str, ...] = ()

    def step(self, state: SimState, t: int) -> SimState:
        e, l, f, d, a = state.epi, state.load, state.fdna, state.diversion, state.access
        self.nodes = f.nodes
        self.rows.append(dict(
            date=e.date, new_hosp=e.new_hosp, prevalence=e.prevalence, r_eff=e.r_eff,
            arrivals=l.arrivals_ward.sum(axis=0), occupancy_ward=l.occupancy_ward,
            occupancy_icu=l.occupancy_icu, diverted_patients=l.diverted, overflow=l.overflow,
            operability=f.hospital_P, node_P=f.P, on_diversion=d.diverted,
            access=a.access, lost_person_days=a.lost_person_days, weighted_loss=a.weighted_loss,
        ))
        return state

    def to_dataset(self) -> xr.Dataset:
        r = self.rows
        stack = lambda k: np.stack([x[k] for x in r])
        coords = {"time": pd.DatetimeIndex([x["date"] for x in r], name="time"),
                  "patch": list(self.net.patches), "hospital": list(self.net.hospitals),
                  "node": list(self.nodes)}
        th, tp = ("time", "hospital"), ("time", "patch")
        return xr.Dataset({
            "new_hosp": (tp, stack("new_hosp")), "prevalence": (tp, stack("prevalence")),
            "r_eff": (("time",), stack("r_eff")),
            "arrivals": (th, stack("arrivals")),
            "occupancy_ward": (th, stack("occupancy_ward")), "occupancy_icu": (th, stack("occupancy_icu")),
            "operability": (th, stack("operability")), "on_diversion": (th, stack("on_diversion")),
            "node_operability": (("time", "node"), stack("node_P")),
            "diverted_patients": (("time",), stack("diverted_patients")),
            "overflow": (("time",), stack("overflow")),
            "access": (tp, stack("access")), "lost_person_days": (tp, stack("lost_person_days")),
            "weighted_loss": (tp, stack("weighted_loss")),
        }, coords=coords)
```

cascade/scenario.py

```
"""One YAML file per scenario, and the one function that wires modules together."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, Field

from .allocation import Allocation
from .core import Simulation
from .epi import Constant, Product, ScenarioConfig, SEIREngine, SEIRModule, Signal
from .equity import Equity
from .fdna import Event, FDNAConfig, FDNAModule
from .network import Network, NetworkConfig
from .recorder import Recorder
from .reroute import Rerouting


class AllocationConfig(BaseModel):
    decay: float = Field(default=0.08, gt=0)     # per minute of drive time


class RerouteConfig(BaseModel):
    p_on: float = 40.0
    p_off: float = 50.0
    occ_on: float = 0.95
    occ_off: float = 0.90
    min_open: int = 1                            # never divert the last k hospitals


class EquityConfig(BaseModel):
    vulnerability: dict[str, float] = {}         # patch -> weight, default 1


class SystemConfig(BaseModel):
    epi: ScenarioConfig
    network: NetworkConfig
    allocation: AllocationConfig = AllocationConfig()
    fdna: FDNAConfig = FDNAConfig()
    rerouting: RerouteConfig = RerouteConfig()
    equity: EquityConfig = EquityConfig()
    events: list[Event] = []
    feedback_to_seir: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SystemConfig":
        path = Path(path)
        raw = yaml.safe_load(path.read_text())
        if isinstance(raw.get("epi"), str):        # epi: other_file.yaml, relative to this one
            raw["epi"] = yaml.safe_load((path.parent / raw["epi"]).read_text())
        return cls.model_validate(raw)


def build(cfg: SystemConfig, overrides: dict[str, float] | None = None
          ) -> tuple[Simulation, SEIRModule, Recorder]:
    """The composition root. The only place that knows every module exists."""
    epi = cfg.epi
    pop = epi.population
    net = Network.from_config(cfg.network, pop.patches)

    rate_overrides = {}
    if cfg.feedback_to_seir:
        base = Constant(epi.disease.by_age("p_death_icu", len(pop.ages)))
        rate_overrides["p_death_icu"] = Product(
            base, Signal("icu_mortality_multiplier", default=1.0, per_patch=True))
    engine = SEIREngine.from_config(epi, **rate_overrides)
    seir = SEIRModule(engine, epi.seeding)

    alloc = Allocation(net, cfg.allocation.decay, epi.disease.los_ward, epi.disease.los_icu)
    shares = alloc.shares
    vuln = np.array([cfg.equity.vulnerability.get(p, 1.0) for p in pop.patches])
    recorder = Recorder(net)
    sim = Simulation([
        seir,
        alloc,
        FDNAModule(net, shares, cfg.fdna, cfg.events, overrides),
        Rerouting(net, **cfg.rerouting.model_dump()),
        Equity(net, shares, pop.N.sum(axis=1), vuln),
        recorder,
    ])
    return sim, seir, recorder
```

cascade/api.py

```
"""The public entry points. The dashboard, CLI, notebooks and sweeps call these and nothing else."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import xarray as xr

from .epi import SEIRResult
from .fdna import criticality as _criticality
from .scenario import SystemConfig, build


@dataclass
class RunResult:
    system: xr.Dataset           # time x hospital / patch / node
    epi: SEIRResult              # full SEIR output, time x patch x age

    def summary(self) -> dict:
        s = self.system
        return {
            "peak_occupancy_icu": float(s.occupancy_icu.max()),
            "hospital_days_on_diversion": int(s.on_diversion.sum()),
            "diverted_patients": float(s.diverted_patients.sum()),
            "overflow_patients": float(s.overflow.sum()),
            "lost_access_person_days": float(s.lost_person_days.sum()),
            "weighted_access_loss": float(s.weighted_loss.sum()),
            "deaths": float(self.epi.ds["new_deaths"].sum()),
        }


def load(path: str | Path) -> SystemConfig:
    return SystemConfig.from_yaml(path)


def run(cfg: SystemConfig, days: int | None = None,
        overrides: dict[str, float] | None = None) -> RunResult:
    days = days or cfg.epi.sim.days
    sim, seir, recorder = build(cfg, overrides)
    sim.run(days)
    X0 = seir.engine.initial_state(cfg.epi.seeding)
    epi = SEIRResult.from_records(seir.records, X0, seir.engine.structure, cfg.epi.population)
    return RunResult(system=recorder.to_dataset(), epi=epi)


def _loss(args) -> float:
    cfg, days, overrides = args
    return run(cfg, days, overrides).summary()["weighted_access_loss"]


class _Runner:
    """Picklable run(overrides) -> loss, so the sweep can use worker processes."""

    def __init__(self, cfg, days):
        self.cfg, self.days = cfg, days

    def __call__(self, overrides):
        return _loss((self.cfg, self.days, overrides))


def criticality(cfg: SystemConfig, days: int | None = None, nodes=None, level: float = 0.0,
                workers: int = 1):
    """Rank FDNA nodes by the extra vulnerability-weighted access loss when each is knocked out."""
    if nodes is None:
        sim, _, _ = build(cfg)
        nodes = [n for n in sim.module("fdna").graph.nodes if not n.endswith(".hospital")]
    return _criticality(_Runner(cfg, days), nodes, level, workers)
```

cascade/\_\_main\_\_.py

```
"""Command line: python -m cascade run|criticality scenario.yaml"""
from __future__ import annotations

import argparse
import json

from . import api


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cascade")
    ap.add_argument("command", choices=["run", "criticality"])
    ap.add_argument("scenario")
    ap.add_argument("--days", type=int)
    ap.add_argument("--out", help="NetCDF path for the system dataset (run only)")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)
    cfg = api.load(a.scenario)
    if a.command == "run":
        res = api.run(cfg, a.days)
        print(json.dumps(res.summary(), indent=2))
        if a.out:
            res.system.to_netcdf(a.out)
    else:
        print(api.criticality(cfg, a.days, workers=a.workers).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
```

app/streamlit_app.py

```
"""Dashboard. Calls cascade.api only: run with `streamlit run app/streamlit_app.py`."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cascade import api                                        # noqa: E402
from cascade.fdna import Event                                 # noqa: E402

SCENARIOS = sorted((Path(__file__).resolve().parents[1] / "scenarios").glob("boston_*.yaml"))
SCENARIOS = [p for p in SCENARIOS if not p.name.endswith("_epi.yaml")]


@st.cache_data(show_spinner="Running scenario...")
def run_cached(cfg_json: str):
    # Cache on the config's JSON so any slider change is a new key.
    res = api.run(api.SystemConfig.model_validate_json(cfg_json))
    return res.system, res.summary()


st.set_page_config(page_title="Boston Hospital Cascade", layout="wide")
st.title("Boston hospital cascade")

with st.sidebar:
    path = st.selectbox("Scenario", SCENARIOS, format_func=lambda p: p.stem)
    cfg = api.load(path)
    d = cfg.epi.disease
    r0 = st.slider("R0", 1.0, 4.0, float(d.r0), 0.1)
    hosp_scale = st.slider("Hospitalisation multiplier", 0.5, 3.0, 1.0, 0.1)
    nodes = [f"{h.id}.{k}" for h in cfg.network.hospitals for k in ("staff", "icu", "ward")]
    nodes += [s.node for s in cfg.fdna.shared]
    knock = st.selectbox("Knock out a node", ["(none)"] + nodes)
    knock_day = st.slider("from day", 0, cfg.epi.sim.days - 1, 30)
    knock_to = st.slider("to operability", 0, 100, 20)

p_hosp = [float(x * hosp_scale) for x in d.by_age("p_hosp", len(cfg.epi.population.ages))]
cfg = cfg.model_copy(update={
    "epi": cfg.epi.model_copy(update={"disease": d.model_copy(update={"r0": r0, "p_hosp": p_hosp})}),
    "events": cfg.events + ([Event(node=knock, value=knock_to, start=knock_day)] if knock != "(none)" else []),
})
system, summary = run_cached(cfg.model_dump_json())

cols = st.columns(4)
cols[0].metric("Peak ICU occupancy", f"{summary['peak_occupancy_icu']:.0%}")
cols[1].metric("Hospital-days on diversion", summary["hospital_days_on_diversion"])
cols[2].metric("Patients diverted", f"{summary['diverted_patients']:,.0f}")
cols[3].metric("Deaths", f"{summary['deaths']:,.0f}")

left, right = st.columns(2)
left.subheader("Operability by hospital")
left.line_chart(system.operability.to_pandas())
right.subheader("ICU occupancy by hospital")
right.line_chart(system.occupancy_icu.to_pandas())
left.subheader("Access to care by neighborhood")
left.line_chart(system.access.to_pandas())
right.subheader("Days on diversion")
right.bar_chart(system.on_diversion.sum("time").to_pandas())

if st.button("Rank single points of failure"):
    st.dataframe(api.criticality(cfg, days=cfg.epi.sim.days), hide_index=True)
st.caption("Planning and research simulator. Illustrative numbers; not for live dispatch.")
```

scenarios/boston_demo.yaml

```
# Illustrative system scenario: 3 neighborhoods, 4 hospitals.
# Beds are the share of each hospital's MassGIS capacity assumed to serve
# these three neighborhoods (about a quarter). Drive times are rough guesses.
# Replace both from data/processed before drawing conclusions.
epi: boston_epi.yaml
network:
  hospitals:
    - {id: MGH,   ccn: "220071", ward_beds: 220, icu_beds: 30, baseline_occupancy: 0.70}
    - {id: BMC,   ccn: "220031", ward_beds: 70,  icu_beds: 10, baseline_occupancy: 0.70}
    - {id: BIDMC, ccn: "220086", ward_beds: 160, icu_beds: 28, baseline_occupancy: 0.70}
    - {id: TUFTS, ccn: "220116", ward_beds: 70,  icu_beds: 14, baseline_occupancy: 0.70}
  travel_minutes:          # rows: Dorchester, Roxbury, Back Bay
    - [20, 12, 18, 15]
    - [15,  8, 10, 10]
    - [10, 10,  8,  7]
allocation:
  decay: 0.08
fdna:
  per_hospital:
    - {src: staff, sod: 0.8, cod: 30}
    - {src: icu,   sod: 0.6, cod: 40}
    - {src: ward,  sod: 0.5, cod: 60}
  shared:
    - {node: ems, kind: ems, sod: 0.3, cod: 70}
    - {node: oxygen_supplier, kind: fixed, value: 100, sod: 0.5, cod: 20}
rerouting: {p_on: 40, p_off: 50, occ_on: 0.95, occ_off: 0.90, min_open: 1}
equity:
  vulnerability: {Dorchester: 1.3, Roxbury: 1.5, "Back Bay": 0.8}
events: []
```

tests/test_system.py

```
"""System tests: data ingestion, FDNA maths, the coupled loop, and the module boundaries."""
import ast
from pathlib import Path

import numpy as np
import pytest

from cascade import api
from cascade.data import build_from_project
from cascade.fdna import Edge, Event, FDNAGraph
from cascade.reroute import GreedyAssigner

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "scenarios" / "boston_demo.yaml"
HEALTHCARE = ROOT.parent / "healthcare"      # the project's dataset folder


@pytest.fixture(scope="module")
def cfg():
    return api.load(DEMO)


@pytest.fixture(scope="module")
def base(cfg):
    return api.run(cfg)


@pytest.mark.skipif(not HEALTHCARE.exists(), reason="project datasets not next to the package")
def test_ingest_joins_project_files():
    df = build_from_project(HEALTHCARE, ROOT / "data" / "crosswalk" / "hospitals.csv")
    row = df.set_index("id")
    assert row.loc["MGH", "icu_beds"] == 101 and row.loc["MGH", "ccn"] == "220071"
    assert row.loc["BIDMC", "campuses"] == 2 and row.loc["BIDMC", "icu_beds"] == 95  # East + West
    assert not row.loc["NEBH", "er"]


def test_fdna_formula_matches_hand_calculation():
    g = FDNAGraph(["a", "b", "h"], [Edge("a", "h", sod=0.8, cod=30), Edge("b", "h", sod=0.5)])
    P = dict(zip(g.nodes, g.evaluate({"a": 50.0, "b": 100.0})))
    sodp = ((0.8 * 50 + 20) + (0.5 * 100 + 50)) / 2          # 80
    assert P["h"] == pytest.approx(min(sodp, 50 + 30))        # COD caps at 80 too
    P = dict(zip(g.nodes, g.evaluate({"a": 10.0, "b": 100.0})))
    assert P["h"] == pytest.approx(40.0)                      # critical feeder caps: 10 + 30


def test_fdna_rejects_cycles():
    with pytest.raises(ValueError, match="acyclic"):
        FDNAGraph(["a", "b"], [Edge("a", "b", 0.5), Edge("b", "a", 0.5)])


def test_every_admission_lands_somewhere(base):
    s = base.system
    np.testing.assert_allclose(s.arrivals.sum("hospital"), s.new_hosp.sum("patch"), rtol=1e-9)


def test_assigner_moves_patients_to_nearest_open_hospital():
    intended = np.array([[10.0, 5.0, 0.0]])
    final, diverted, overflow = GreedyAssigner()(
        intended, closed=np.array([True, False, False]),
        travel=np.array([[5.0, 20.0, 10.0]]), free=np.array([0.0, 100.0, 4.0]))
    assert diverted == 10.0 and final[0, 0] == 0.0
    assert final[0, 2] == 4.0 and final[0, 1] == 11.0 and overflow == 0.0


def test_strain_cascades_through_diversion(base):
    s = base.system
    assert s.on_diversion.any("time").all()          # every hospital diverts at some point
    first = s.on_diversion.argmax("time").values
    assert first.min() < first.max()                  # ...but not all on the same day
    assert float(s.diverted_patients.sum()) > 0
    assert (s.on_diversion.sum("hospital") < s.sizes["hospital"]).all()   # min_open holds


def test_staff_knockout_degrades_hospital_and_loads_neighbours(cfg, base):
    knocked = cfg.model_copy(update={"events": [Event(node="BMC.staff", value=20, start=30)]})
    res = api.run(knocked)
    bmc = list(cfg.network.hospitals).index(next(h for h in cfg.network.hospitals if h.id == "BMC"))
    assert float(res.system.operability.isel(hospital=bmc)[40]) < float(base.system.operability.isel(hospital=bmc)[40])
    others = [i for i in range(len(cfg.network.hospitals)) if i != bmc]
    assert float(res.system.arrivals.isel(hospital=others).sum()) > float(base.system.arrivals.isel(hospital=others).sum())
    assert res.summary()["weighted_access_loss"] > base.summary()["weighted_access_loss"]


def test_fdna_feedback_reaches_seir(cfg, base):
    no_feedback = api.run(cfg.model_copy(update={"feedback_to_seir": False}))
    assert base.summary()["deaths"] > no_feedback.summary()["deaths"]


def test_criticality_ranks_nodes(cfg):
    df = api.criticality(cfg, days=120, nodes=["BMC.staff", "MGH.staff", "TUFTS.ward"])
    assert list(df.columns) == ["node", "loss", "extra_loss"]
    assert df.extra_loss.is_monotonic_decreasing and (df.extra_loss > 0).all()


def test_runs_are_reproducible(cfg, base):
    again = api.run(cfg)
    assert base.system.identical(again.system)


def test_layers_only_import_contracts():
    """FDNA, allocation, rerouting and equity never import the SEIR engine or each other's modules."""
    allowed = {"cascade.core", "cascade.contracts", "cascade.network", "cascade.reroute"}
    for path in [*(ROOT / "cascade" / "fdna").glob("*.py"), ROOT / "cascade" / "allocation.py",
                 ROOT / "cascade" / "reroute.py", ROOT / "cascade" / "equity.py"]:
        pkg = "cascade.fdna" if path.parent.name == "fdna" else "cascade"
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                base_pkg = pkg.rsplit(".", node.level - 1)[0] if node.level > 1 else pkg
                mod = f"{base_pkg}.{node.module}" if node.module else base_pkg
                if mod.startswith("cascade.fdna") and pkg == "cascade.fdna":
                    continue
                assert mod in allowed, f"{path.name} imports {mod}"
```

bench_system.py

```
"""Times the full coupled loop: SEIR + allocation + FDNA + rerouting + equity."""
import time

import numpy as np

from cascade import api
from cascade.epi.config import ScenarioConfig
from cascade.network import HospitalSpec, NetworkConfig
from cascade.scenario import SystemConfig


def synthetic(n_patch, n_age, n_hosp, days, seed=0):
    rng = np.random.default_rng(seed)
    patches = [f"p{i}" for i in range(n_patch)]
    W = 0.7 * np.eye(n_patch) + 0.3 * rng.dirichlet(np.ones(n_patch), n_patch)
    epi = ScenarioConfig.model_validate(dict(
        disease=dict(r0=1.6, latent_period=3, infectious_period=5, p_hosp=0.02, p_icu=0.2,
                     p_death_icu=0.3, los_ward=5, los_icu=9),
        population=dict(patches=patches, ages=[f"a{i}" for i in range(n_age)],
                        counts=rng.uniform(300, 900, (n_patch, n_age)).tolist()),
        mixing=dict(patch_coupling=(W / W.sum(1, keepdims=True)).tolist()),
        seeding=dict(exposed={"p0": 50}), sim=dict(start="2021-12-01", days=days)))
    net = NetworkConfig(
        hospitals=[HospitalSpec(id=f"H{h}", ward_beds=rng.uniform(100, 600), icu_beds=rng.uniform(10, 80))
                   for h in range(n_hosp)],
        travel_minutes=rng.uniform(5, 40, (n_patch, n_hosp)).tolist())
    return SystemConfig(epi=epi, network=net)


if __name__ == "__main__":
    for shape in [(3, 3, 4), (15, 3, 20), (200, 9, 20), (200, 9, 60)]:
        cfg = synthetic(*shape, days=365)
        api.run(cfg, days=5)                                 # warm up imports
        t = time.perf_counter()
        api.run(cfg)
        print(f"{shape[0]} patches x {shape[1]} ages x {shape[2]} hospitals, 365 days: "
              f"{time.perf_counter() - t:.2f} s")
```

Built on the SEIR Layer Coding Guide and the Boston Hospital Cascade Model writeup. Hospital beds and CCNs come from the project's MassGIS and CMS files; scenario beds, drive times, FDNA weights and thresholds are illustrative proposals for the team to replace.