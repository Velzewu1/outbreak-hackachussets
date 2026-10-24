"""Shared golden-fixture builders used by multiple tests.

Builds an Accessibility with EXACTLY the frozen walkthrough shares/distances so
the allocation/FDNA tests reproduce the verified numbers independent of real
geography. Shares come from docs/end-to-end-walkthrough.md section 0.1.
"""

from __future__ import annotations

import math

from pipeline.types import Accessibility

DISTRICTS = ("D1", "D2", "D3")
HOSPITALS = ("H1", "H2", "H3")

# Distances (km) from the frozen walkthrough.
DIST = {
    ("D1", "H1"): 1.0,
    ("D1", "H2"): 4.0,
    ("D1", "H3"): 9.0,
    ("D2", "H1"): 5.0,
    ("D2", "H2"): 2.0,
    ("D2", "H3"): 6.0,
    ("D3", "H1"): 8.0,
    ("D3", "H2"): 7.0,
    ("D3", "H3"): 2.0,
}
D0 = 3.0

BASELINE = {"H1": 60.0, "H2": 75.0, "H3": 40.0}
CEFF = {"H1": 150.0, "H2": 110.0, "H3": 80.0}


def golden_accessibility() -> Accessibility:
    a = {}
    shares = {}
    eligible = {}
    tot = {}
    for j in DISTRICTS:
        avals = {h: math.exp(-DIST[(j, h)] / D0) for h in HOSPITALS}
        s = sum(avals.values())
        tot[j] = s
        for h in HOSPITALS:
            a[(j, h)] = avals[h]
            eligible[(j, h)] = True
            shares[(j, h)] = avals[h] / s
    return Accessibility(
        district_ids=DISTRICTS,
        hospital_ids=HOSPITALS,
        distance_km=DIST,
        eligible=eligible,
        a=a,
        shares=shares,
        total_accessibility=tot,
    )
