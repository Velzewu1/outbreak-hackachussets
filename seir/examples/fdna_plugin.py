"""How the SEIR layer plugs into the daily loop, with feedback from FDNA.

    python examples/fdna_plugin.py

The real FDNA layer is someone else's module. This one is a stand-in with the
same shape: it reads the epidemic snapshot (state.epi) every day and writes a
feedback signal for SEIR (state.signals["seir"]). SEIR reads that signal the
next morning, so the loop has no cycle within a day, as the writeup's
"Handling loops" section asks.

The stand-in: ICU strain per neighbourhood is ICU census / ICU beds; above
100%, ICU mortality rises in proportion to the overflow. Bed counts and the
effect size are illustrative, not data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cascade.core import SimState, Simulation                       # noqa: E402
from cascade.epi import EpiSnapshot, ScenarioConfig, SEIRModule, terminal   # noqa: E402

ICU_BEDS = {"Dorchester": 40, "Roxbury": 20, "Back Bay": 30}   # illustrative


class ToyFDNA:
    """Reads EpiSnapshot, writes icu_mortality_multiplier for tomorrow's SEIR step."""

    name = "fdna"

    def __init__(self, patches, beds: dict[str, float], excess_mortality: float = 0.5):
        self.beds = np.array([beds[p] for p in patches], dtype=float)
        self.excess = excess_mortality
        self.log: list[dict] = []

    def step(self, state: SimState, t: int) -> SimState:
        epi: EpiSnapshot = state.epi                    # written by "seir" earlier today
        strain = epi.icu_census / self.beds             # [patch]
        multiplier = 1.0 + self.excess * np.clip(strain - 1.0, 0.0, None)
        state.signals.setdefault("seir", {})["icu_mortality_multiplier"] = multiplier
        self.log.append({"day": t, "date": epi.date, "max_strain": float(strain.max()),
                         "multiplier": float(multiplier.max())})
        return state


def run(cfg: ScenarioConfig, feedback: bool):
    seir = SEIRModule.from_config(cfg, feedback=("icu_mortality_multiplier",) if feedback else ())
    fdna = ToyFDNA(cfg.population.patches, ICU_BEDS)
    state = Simulation([seir, fdna]).run(cfg.sim.days)
    return seir, fdna, state


def main() -> None:
    cfg = ScenarioConfig.from_yaml(ROOT / "scenarios" / "example_3patch.yaml")
    seir_off, _, _ = run(cfg, feedback=False)
    seir_on, fdna, state = run(cfg, feedback=True)

    snap = state.epi
    print("What FDNA reads every day: state.epi, a frozen EpiSnapshot. Last day:")
    for field in ("date", "patches", "prevalence", "new_hosp", "new_icu", "ward_census", "icu_census",
                  "transmission_rate", "incubation_rate", "recovery_rate", "r_eff"):
        value = getattr(snap, field)
        if isinstance(value, np.ndarray):
            value = "[" + ", ".join(f"{v:,.4g}" for v in value) + "]"
        elif isinstance(value, float):
            value = f"{value:.4g}"
        print(f"  {field:<18} {value}")

    log = pd.DataFrame(fdna.log).set_index("day")
    first = log.index[log["multiplier"] > 1.0]
    print("\nWhat FDNA writes back: state.signals['seir']['icu_mortality_multiplier'], one per patch.")
    if len(first):
        d = int(first[0])
        deaths_off = seir_off.result().series("new_deaths")
        deaths_on = seir_on.result().series("new_deaths")
        diverge = int(np.argmax(~np.isclose(deaths_on.values, deaths_off.values)))
        print(f"  ICU strain first passes 100% on day {d} ({log.loc[d, 'date']:%d %b}); SEIR uses the higher")
        print(f"  mortality from day {diverge}, the next day, because signals are read the morning after.")
        print()
        print(terminal.chart({"ICU strain (max patch) x 100": 100 * log["max_strain"]}, height=8, width=60,
                             title="Strongest ICU strain across neighbourhoods, % of beds"))
        res_off, res_on = seir_off.result(), seir_on.result()
        rows = []
        for patch in cfg.population.patches:
            off = float(res_off.ds["new_deaths"].sel(patch=patch).sum())
            on = float(res_on.ds["new_deaths"].sel(patch=patch).sum())
            icu_peak = float(res_on.ds["C"].sel(patch=patch).sum("age").max())
            rows.append({"patch": patch, "ICU beds": ICU_BEDS[patch], "peak ICU census": round(icu_peak),
                         "deaths, no feedback": round(off, 1), "deaths, feedback": round(on, 1),
                         "extra": f"{on - off:+.1f}"})
        print("\nSame epidemic, with and without the feedback wired in:")
        print(terminal.table(pd.DataFrame(rows)))
        print("\nOnly ICU deaths change: the multiplier scales p_death_icu, nothing else. Wire other")
        print("channels the same way: SEIRModule.from_config(cfg, feedback=('hosp_multiplier',")
        print("'contact_multiplier')), or pass any rate as a Signal-based provider.")
    else:
        print("  ICU strain never passed 100% in this scenario, so the feedback never changed anything.")


if __name__ == "__main__":
    main()
