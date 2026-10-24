"""Adding compartments without touching the engine.

    python examples/extend_model.py

A model structure is data: compartments plus transitions, each with a rate
function. Every variant below is built from seir_h() with a few lines, and
the engine, R0, R_eff, growth rates and outputs all follow on their own.

  waning        R -> S at rate "waning" (immunity lasts ~4 months on average)
  vaccination   S -> V at rate "vax_rate"; V is infected at foi * (1 - "vax_efficacy")
  asymptomatic  a share "p_asym" of infections never show symptoms; they
                transmit half as much and never need a hospital
  admission     a custom stage written here: sick at home (P), not
  delay         transmitting, between I and the ward. It lets the infectious
                period follow the measured generation time (5.2 d) while
                admissions keep a realistic delay after infection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cascade.epi import (Constant, ScenarioConfig, SEIREngine, Transition, seir_h, terminal,   # noqa: E402
                         with_asymptomatic, with_vaccination, with_waning)


def with_admission_delay(structure):
    """I -> P (unwell at home) -> H, replacing the direct I -> H admission."""
    return structure.extend(
        compartments=("P",),
        drop_flows=("new_hosp",),
        transitions=(
            Transition("I", "P", lambda r: r["gamma"] * r["p_hosp"], "new_unwell"),
            Transition("P", "H", lambda r: r["admit_rate"], "new_hosp"),
        ),
    )


def main() -> None:
    cfg = ScenarioConfig.from_yaml(ROOT / "scenarios" / "example_3patch.yaml")
    days = 365
    short = cfg.updated({"disease.latent_period": 2.0, "disease.infectious_period": 3.2})
    variants = {
        "seir_h (baseline)": (cfg, seir_h(), {}),
        "waning": (cfg, with_waning(seir_h()), {"waning": Constant(1 / 120)}),
        "vaccination": (cfg, with_vaccination(seir_h()),
                        {"vax_rate": Constant(0.005), "vax_efficacy": Constant(0.7)}),
        "asymptomatic": (cfg, with_asymptomatic(seir_h(), relative_infectiousness=0.5),
                         {"p_asym": Constant(0.3)}),
        "admission delay": (short, with_admission_delay(seir_h()), {"admit_rate": Constant(1 / 3.0)}),
    }
    rows, curves = [], {}
    for name, (c, structure, extra) in variants.items():
        engine = SEIREngine.from_config(c, structure=structure, **extra)
        res = engine.run(c.seeding, days)
        s = res.summary()
        infections = res.series("infections")
        curves[name] = infections
        rows.append({
            "model": name,
            "compartments": "".join(structure.compartments),
            "R0": round(engine.r0(), 2),
            "generation time (d)": round(engine.generation_time(), 1),
            "infections per person": f"{s['attack_rate']:.2f}",
            "admissions": round(s["admissions"]),
            "peak inpatients": round(s["peak_inpatients"]),
            "peak date": s["peak_inpatients_date"],
        })
    print(f"Guide example (3 neighbourhoods, R0 {cfg.disease.r0:g}), {days} days, same engine every time:\n")
    print(terminal.table(pd.DataFrame(rows)))
    print("\nNew infections per day, each scaled to its own peak:")
    for name, s in curves.items():
        print(f"  {name:<18} {terminal.sparkline(s.values, 60)}")
    print("""
R0 is set from the scenario in every case; beta0 is solved for each structure
so the asymptomatic stage (which transmits) and the vaccinated compartment
(which is infected less) are accounted for. Waning brings reinfections (more
infections than people) and a smaller second wave that settles into steady
spread. The admission-delay variant has a shorter generation time (latent 2 +
infectious 3.2 d = 5.2 d, as measured by Ganyani 2020) and so grows faster at
the same R0, while admissions still come about 8 days after infection.

The pattern for your own compartment: a function that calls
structure.extend(compartments=..., transitions=..., drop_flows=...), and any
new rate passed to SEIREngine.from_config by name (admit_rate=Constant(1/3)).""")


if __name__ == "__main__":
    main()
