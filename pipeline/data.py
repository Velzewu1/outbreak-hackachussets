"""DATA / SEPARATE: fixtures and loaders.

Provides:
- ``golden_fixture()``: the exact frozen 3-district/3-hospital golden inputs with
  seeded prior cohorts and a hand-chosen SEIR fixture (TESTS ONLY).
- ``synthetic_spatial()``: a larger explicitly SYNTHETIC spatial demo for the app.
- real loaders live in ``pipeline.data_real`` (MassGIS tracts/hospitals + HHS).

Hand-chosen SEIR outputs are used ONLY by the golden walkthrough test; they never
substitute for the production SciPy solver in ``pipeline.seir``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .contracts import District, Hospital
from .types import Cohort


@dataclass
class DataBundle:
    districts: list
    hospitals: list
    seeded_cohorts: dict  # hospital_id -> list[Cohort]
    data_mode: str
    manifest: dict


# --------------------------------------------------------------------------- #
# Frozen golden fixture (matches docs/end-to-end-walkthrough.md)
# --------------------------------------------------------------------------- #

# Districts carry a centroid; the golden walkthrough uses prescribed distances,
# so we place hospitals/districts to REPRODUCE those distances where it matters
# for tests that call the full pipeline. The pure-arithmetic golden values are
# checked directly in tests against the equations, independent of geography.

GOLDEN_DISTRICTS = [
    District("D1", 10000, 1.0, None, 42.3300, -71.0800),
    District("D2", 20000, 1.5, None, 42.3400, -71.1000),
    District("D3", 15000, 0.8, None, 42.3000, -71.0600),
]

GOLDEN_HOSPITALS = [
    Hospital("H1", "Golden H1", 42.3300, -71.0810, 150, 20, 60.0),
    Hospital("H2", "Golden H2", 42.3405, -71.1000, 110, 14, 75.0),
    Hospital("H3", "Golden H3", 42.3000, -71.0590, 80, 10, 40.0),
]

# Seeded prior cohorts (admit_week = -1 sentinel): LOS 1 discharges in interval 0,
# LOS 2 retained through interval 0 and discharged in interval 1.
GOLDEN_SEEDED = {
    "H1": [Cohort("D1", -1, 1, 12.0), Cohort("D2", -1, 2, 18.0)],
    "H2": [Cohort("D2", -1, 1, 20.0), Cohort("D1", -1, 2, 8.0)],
    "H3": [Cohort("D3", -1, 1, 10.0), Cohort("D3", -1, 2, 6.0)],
}


def golden_fixture() -> DataBundle:
    return DataBundle(
        districts=[d.validate() for d in GOLDEN_DISTRICTS],
        hospitals=[h.validate() for h in GOLDEN_HOSPITALS],
        seeded_cohorts={k: list(v) for k, v in GOLDEN_SEEDED.items()},
        data_mode="synthetic_demo",
        manifest={"source": "golden_fixture", "label": "SYNTHETIC / ILLUSTRATIVE"},
    )


# --------------------------------------------------------------------------- #
# Synthetic spatial demo (for the app when real data is not loaded)
# --------------------------------------------------------------------------- #


def synthetic_spatial(n_districts: int = 24, n_hospitals: int = 6, seed: int = 7) -> DataBundle:
    """Deterministic SYNTHETIC districts/hospitals on a small grid around Boston.

    Explicitly synthetic coordinates; never presented as real facilities.
    """
    rng = random.Random(seed)
    # Boston-ish bounding box (synthetic placements)
    lat0, lon0 = 42.28, -71.12
    lat1, lon1 = 42.40, -71.00

    districts = []
    cols = int(math.ceil(math.sqrt(n_districts)))
    for i in range(n_districts):
        r, c = divmod(i, cols)
        lat = lat0 + (lat1 - lat0) * (r + 0.5) / cols
        lon = lon0 + (lon1 - lon0) * (c + 0.5) / cols
        pop = 4000 + rng.randint(0, 16) * 500
        rw = round(0.8 + rng.random() * 0.7, 3)
        ej = bool(rng.random() < 0.4)
        districts.append(District(f"SD{i:02d}", pop, rw, ej, round(lat, 5), round(lon, 5)))

    hospitals = []
    for k in range(n_hospitals):
        lat = lat0 + (lat1 - lat0) * (0.2 + 0.6 * rng.random())
        lon = lon0 + (lon1 - lon0) * (0.2 + 0.6 * rng.random())
        c = 90 + rng.randint(0, 20) * 10
        icu = int(c * 0.1)
        base = round(c * (0.6 + rng.random() * 0.2), 1)
        hospitals.append(
            Hospital(
                f"SH{k}", f"Synthetic Hospital {k}", round(lat, 5), round(lon, 5), c, icu, base
            )
        )

    return DataBundle(
        districts=[d.validate() for d in districts],
        hospitals=[h.validate() for h in hospitals],
        seeded_cohorts={},
        data_mode="synthetic_demo",
        manifest={
            "source": "synthetic_spatial",
            "label": "SYNTHETIC / ILLUSTRATIVE",
            "seed": seed,
        },
    )
