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
