"""Turns per-patch admissions into per-hospital arrivals and census."""
from __future__ import annotations

import numpy as np

from .contracts import HospitalLoad
from .core import SimState
from .network import Network
from .reroute import Assigner, GreedyAssigner


class Allocation:
    """Gravity model for where patients go, then census bookkeeping per hospital.

    COVID census leaves at 1 / length of stay. Non-COVID patients are held at
    each hospital's baseline occupancy.
    """

    name = "allocation"

    def __init__(self, network: Network, decay: float = 0.08, los_ward: float = 5.0,
                 los_icu: float = 9.0, assigner: Assigner | None = None):
        self.net = network
        self.decay = decay
        self.keep_ward = np.exp(-1.0 / los_ward)
        self.keep_icu = np.exp(-1.0 / los_icu)
        self.assign = assigner or GreedyAssigner()
        self.shares = network.gravity_shares(decay)               # [patch, hospital]
        self.covid_ward = np.zeros(network.n_hospitals)
        self.covid_icu = np.zeros(network.n_hospitals)

    def step(self, state: SimState, t: int) -> SimState:
        epi, net = state.epi, self.net
        closed = np.asarray(state.signals.get(self.name, {}).get(
            "diverted", np.zeros(net.n_hospitals, bool)))
        base_ward = net.baseline_occupancy * net.ward_beds
        base_icu = net.baseline_occupancy * net.icu_beds

        self.covid_ward *= self.keep_ward
        self.covid_icu *= self.keep_icu
        free_ward = net.ward_beds - base_ward - self.covid_ward

        intended = epi.new_hosp[:, None] * self.shares
        ward, diverted, overflow = self.assign(intended, closed, net.travel, free_ward)
        # ICU transfers follow where each patch's ward patients went today.
        row = ward.sum(axis=1, keepdims=True)
        where = np.divide(ward, row, out=self.shares.copy(), where=row > 0)
        icu = epi.new_icu[:, None] * where

        self.covid_ward += ward.sum(axis=0)
        self.covid_icu += icu.sum(axis=0)
        census_ward = base_ward + self.covid_ward
        census_icu = base_icu + self.covid_icu
        state.load = HospitalLoad(
            day=t, arrivals_ward=ward, arrivals_icu=icu,
            census_ward=census_ward, census_icu=census_icu,
            occupancy_ward=census_ward / net.ward_beds,
            occupancy_icu=np.divide(census_icu, net.icu_beds, out=np.zeros_like(census_icu),
                                    where=net.icu_beds > 0),
            diverted=diverted, overflow=overflow,
        )
        return state
