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
