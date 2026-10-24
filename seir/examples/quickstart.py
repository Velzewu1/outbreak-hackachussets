"""A first run of the SEIR layer, in the terminal.

    python examples/quickstart.py
    python examples/quickstart.py scenarios/omicron_2021.yaml

Runs a scenario (by default the guide's three-neighbourhood example) and
prints what the layer produces: the rates it used (transmission, incubation,
recovery), the standard SEIR outputs, hospital demand per neighbourhood, the
same thing from a stochastic run, and the plain-dict summary a frontend or
API would serve.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cascade.epi import ScenarioConfig, SEIREngine, terminal   # noqa: E402

WIDTH = 56


def main(path: str | Path = ROOT / "scenarios" / "example_3patch.yaml") -> None:
    cfg = ScenarioConfig.from_yaml(path)
    engine = SEIREngine.from_config(cfg)
    about = engine.describe(seeding=cfg.seeding)
    pop = cfg.population

    print(f"Scenario: {Path(path).name}, {len(pop.patches)} patches x {len(pop.ages)} age groups, "
          f"{about['population']:,.0f} people, {cfg.sim.days} days from {cfg.sim.start}")
    print(terminal.key_values({
        "R0": round(about["r0"], 2),
        "R_eff on day 0": round(about["r_eff_start"], 2),
        "transmission rate beta0": f"{engine.beta0:.4f} per day",
        "incubation rate sigma": f"{about['incubation_rate']:.4f} per day (1 / {cfg.disease.latent_period:g} d)",
        "recovery rate gamma": f"{about['recovery_rate']:.4f} per day (1 / {cfg.disease.infectious_period:g} d)",
        "generation time": f"{about['generation_time_days']:.1f} days",
        "doubling time at start": (f"{about['doubling_time_start']:.1f} days"
                                   if about["doubling_time_start"] else "not growing"),
    }))

    # ---- deterministic run --------------------------------------------------
    res = engine.run(cfg.seeding, cfg.sim.days)
    print("\nStandard outputs, all patches (each line scaled to its own peak)")
    for label, name in (("new infections", "infections"), ("in E (exposed)", "E"),
                        ("in I (infectious)", "I"), ("admissions", "new_hosp"),
                        ("inpatients (H+C)", "inpatients"), ("in ICU", "icu"), ("deaths", "new_deaths")):
        s = res.series(name)
        print(f"  {label:<18}{terminal.sparkline(s.values, WIDTH)}  peak {s.max():>9,.0f} on {s.idxmax():%d %b}")
    r = res.ds["r_eff"].values
    print(f"  {'R_eff':<18}{terminal.sparkline(r, WIDTH, low=0)}  {r[0]:.2f} on day 0, {r[-1]:.2f} at the end")

    print("\nRates are outputs too (dataset variables with attrs kind='rate'):")
    print("  " + ", ".join(res.rates.data_vars))
    print("  e.g. res.ds['transmission_rate'] per day; res.observed_rates() gives the realised ones")

    print("\nBy neighbourhood")
    rows = []
    for patch in pop.patches:
        adm = res.series("new_hosp", patches=[patch])
        inpatients = res.inpatients().sel(patch=patch).to_series()
        n = float(res.population.sel(patch=patch).sum())
        rows.append({"patch": patch, "population": int(n),
                     "infected": f"{float(res.infections().sel(patch=patch).sum()) / n:.0%}",
                     "admissions": int(round(adm.sum())), "peak admissions/day": round(adm.max(), 1),
                     "peak day": f"{adm.idxmax():%d %b}", "peak inpatients": int(round(inpatients.max()))})
    print(terminal.table(pd.DataFrame(rows)))

    # ---- one stochastic run --------------------------------------------------
    stochastic = SEIREngine.from_config(cfg.updated({"sim.stochastic": True, "sim.seed": 7}))
    sres = stochastic.run(cfg.seeding, cfg.sim.days)
    det, sto = res.series("inpatients"), sres.series("inpatients")
    print(f"\nOne chain-binomial run (whole people, seed 7): peak inpatients {sto.max():,.0f} on "
          f"{sto.idxmax():%d %b}, against {det.max():,.0f} on {det.idxmax():%d %b} deterministic.")
    print(terminal.chart({"deterministic": det, "stochastic": sto}, height=8, width=WIDTH,
                         title="Inpatients, all patches"))
    print("For bands over many runs: python -m cascade.epi ensemble " + str(Path(path).relative_to(ROOT)
                                                                          if Path(path).is_relative_to(ROOT) else path))

    # ---- what a frontend would get --------------------------------------------
    print("\nres.summary() is plain JSON for a dashboard or an API:")
    summary = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.summary().items()}
    print(json.dumps(summary, indent=2))
    table = res.to_frame()
    print(f"\nres.to_frame(): {len(table):,} rows (day x patch) x {table.shape[1]} columns; "
          "res.save('run.nc' or 'run.csv') writes it out.")
    print(f"Columns: {', '.join(table.columns[:12])}, ...")


if __name__ == "__main__":
    main(*sys.argv[1:2])
