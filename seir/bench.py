"""Speed check on a city-sized grid: 200 patches x 9 age groups x 365 days.

    python bench.py

The same set-up as the reference implementation's bench.py, so the two can
be compared directly.
"""
import time
from datetime import date

import numpy as np

from cascade.epi import ScenarioConfig, SEIREngine

rng = np.random.default_rng(0)
P, A = 200, 9
W = rng.random((P, P)) ** 8
np.fill_diagonal(W, 0)
W = W / W.sum(1, keepdims=True) * 0.25 + np.eye(P) * 0.75
cfg = ScenarioConfig.model_validate({
    "disease": {"r0": 2.5, "latent_period": 3, "infectious_period": 5,
                "p_hosp": list(np.linspace(0.001, 0.08, A)), "p_icu": 0.2, "p_death_icu": 0.3},
    "population": {"patches": [f"t{i}" for i in range(P)], "ages": [f"a{i}" for i in range(A)],
                   "counts": rng.integers(200, 900, (P, A)).tolist()},
    "mixing": {"age_contacts": (rng.random((A, A)) + np.eye(A) * 3).tolist(), "patch_coupling": W.tolist()},
    "seeding": {"exposed": {"t0": 20}},
    "sim": {"start": date(2021, 12, 1), "days": 365, "substeps": 4},
})

for label, c in (("deterministic", cfg), ("stochastic", cfg.updated({"sim.stochastic": True, "sim.seed": 1}))):
    t = time.perf_counter()
    eng = SEIREngine.from_config(c)
    built = time.perf_counter() - t
    res = eng.run(c.seeding, 365)
    total = time.perf_counter() - t
    print(f"{label:<13} {P} x {A} cells, 365 days: {total:.2f} s (build {built:.2f} s), "
          f"peak inpatients {res.series('inpatients').max():,.0f}")
