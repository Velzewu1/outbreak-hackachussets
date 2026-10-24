# Boston hospital cascade: SEIR layer

The epidemic layer of the cascade model: a metapopulation SEIR model with
ward, ICU and deaths, by neighbourhood and age. It outputs the transmission,
incubation and recovery rates alongside the usual curves, plugs into FDNA
through a frozen daily snapshot, and is calibrated and validated on
Massachusetts COVID-19 data. Terminal demos only for now; every command
also prints JSON for a future frontend.

## Install and test

```
pip install -r requirements.txt     # Python 3.11+
pytest                              # 183 tests, about a minute
```

## Terminal demos

```
python examples/quickstart.py               # one run: rates, curves, R_eff, JSON summary
python examples/fdna_plugin.py              # FDNA reads state.epi, writes ICU strain back
python examples/extend_model.py             # waning, vaccination, asymptomatic: no engine changes
python examples/calibrate_massachusetts.py  # fit, backtest and out-of-sample check (about a minute)

python -m cascade.epi presets
python -m cascade.epi info scenarios/omicron_2021.yaml
python -m cascade.epi run scenarios/example_3patch.yaml --weekly
python -m cascade.epi run scenarios/example_3patch.yaml --set disease.r0=2.2 --json
python -m cascade.epi ensemble scenarios/example_3patch.yaml --runs 50
python -m cascade.epi sensitivity scenarios/omicron_2021.yaml --params disease.r0 disease.los_ward
python -m cascade.epi calibrate scenarios/omicron_2021.yaml --observed data/hhs_ma_daily_admissions.csv \
    --weekly --start 2021-12-19 --end 2022-03-05 --fit disease.r0=2:1:5 --fit disease.hosp_scale=1:0.1:5
```

`info` on the Omicron scenario prints:

```
Rates     transmission 0.0331/day, incubation 0.5000/day, recovery 0.2500/day
Spread    R0 1.95: growth +0.134/day, doubling every 5.2 d; generation time 6.0 d
          on day 0 (22% immune): R_eff 1.50, growth +0.076/day, doubling every 9.1 d
```

## In Python

```python
from cascade.epi import ScenarioConfig, simulate

cfg = ScenarioConfig.from_yaml("scenarios/omicron_2021.yaml")
res = simulate(cfg)
res.summary()                      # plain dict: attack rate, peaks, R_eff...
res.ds["transmission_rate"]        # xarray, dims (time, patch, age)
res.to_frame()                     # long table for CSV or a dashboard
```

In the shared loop: `Simulation([SEIRModule.from_config(cfg, feedback=("icu_mortality_multiplier",)), ...])`.
Each day it writes an `EpiSnapshot` to `state.epi` and reads multipliers
from `state.signals["seir"]` the next day.

## Scenarios

YAML with five sections; unknown keys are errors.

```yaml
disease: {preset: covid_omicron, r0: 1.95, hosp_scale: 1.08}   # or give every field
population: {patches: [...], ages: ["0-17", "18-64", "65+"], counts: [[...]]}
mixing: {age_contacts: [[...]], patch_coupling: [[...]], contact_multiplier: {csv: ..., column: ...}}
seeding: {exposed: {Boston: 50}, immune_share: 0.22, initial: {H: {Boston: 280}}}
sim: {start: 2021-12-01, days: 100, substeps: 4, stochastic: false}
```

`example_3patch.yaml` is illustrative; `omicron_2021.yaml` and
`winter_2020.yaml` are the calibrated Massachusetts fits;
`omicron_2021_mobility.yaml` drives transmission by mobility;
`novel_flu.yaml` is a pandemic-flu what-if.

## Validation in short

| check | result |
|---|---|
| Omicron wave fit (admissions) | PASS: all weeks within 40%, peak week exact, height −16% |
| Forecast from 8 or 15 Jan, preset severity | PASS both |
| Forecast with severity also fitted | FAIL both: early weeks can't fix severity |
| Winter 2020-21, ICU census (never fitted) | PASS: peak height 0% |
| Winter 2020-21, all inpatients (never fitted) | FAIL: peak −26%, ward census too low |

Details, the immunity problem and sensitivity: [docs/validation.md](docs/validation.md).
Equations and time stepping: [docs/model.md](docs/model.md). Data sources
and licences: [data/README.md](data/README.md).

## Layout

```
cascade/core.py          shared SimState, Module, Simulation (from the cascade reference)
cascade/epi/             structure, rates, mixing, engine, results, config, presets,
                         adapter (FDNA plug), calibrate, validation, ensemble,
                         sensitivity, data loaders, terminal output, CLI
cascade/{network,allocation,fdna,reroute,equity,recorder,contracts,scenario,api}.py
                         system layer from the cascade reference, unchanged
                         (python -m cascade run systems/boston_city.yaml)
scenarios/  systems/  examples/  data/  docs/  tests/  bench.py
```

## Compatibility

Drop `cascade/epi` into the cascade reference and its 20 tests pass. One
deliberate difference from the reference: stays after infection use
p = rate × dt instead of 1 − exp(−rate × dt), which removes a bias of a few
percent in R0 and hospital census (docs/model.md), so system results shift
slightly (reference demo: 104 deaths here against 110).
