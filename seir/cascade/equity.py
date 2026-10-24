"""Access to care per patch, weighted by social vulnerability."""
from __future__ import annotations

import numpy as np

from .contracts import AccessSnapshot
from .core import SimState
from .network import Network


class Equity:
    """access[p] = sum_h usual_share[p, h] * P_h / 100, counting diverted hospitals as 0.

    usual_share is the no-diversion gravity split, so access measures how much
    of a neighborhood's usual hospital care is still open and operable today.
    """

    name = "equity"

    def __init__(self, network: Network, shares: np.ndarray, population: np.ndarray,
                 vulnerability: np.ndarray | None = None):
        self.shares, self.pop = shares, population
        self.vuln = np.ones(len(network.patches)) if vulnerability is None else vulnerability

    def step(self, state: SimState, t: int) -> SimState:
        open_P = state.fdna.hospital_P * ~state.diversion.diverted
        access = self.shares @ (open_P / 100.0)
        lost = self.pop * (1.0 - access)
        state.access = AccessSnapshot(day=t, access=access, lost_person_days=lost,
                                      weighted_loss=lost * self.vuln)
        return state
