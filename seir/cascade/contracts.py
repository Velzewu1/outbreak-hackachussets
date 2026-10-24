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
