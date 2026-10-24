"""Collects every layer's daily snapshot into one labelled xarray Dataset."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .core import SimState
from .network import Network


class Recorder:
    """Runs last each day. Reads snapshots only, so it doubles as a contract check."""

    name = "recorder"

    def __init__(self, network: Network):
        self.net = network
        self.rows: list[dict] = []
        self.nodes: tuple[str, ...] = ()

    def step(self, state: SimState, t: int) -> SimState:
        e, l, f, d, a = state.epi, state.load, state.fdna, state.diversion, state.access
        self.nodes = f.nodes
        self.rows.append(dict(
            date=e.date, new_hosp=e.new_hosp, prevalence=e.prevalence, r_eff=e.r_eff,
            arrivals=l.arrivals_ward.sum(axis=0), occupancy_ward=l.occupancy_ward,
            occupancy_icu=l.occupancy_icu, diverted_patients=l.diverted, overflow=l.overflow,
            operability=f.hospital_P, node_P=f.P, on_diversion=d.diverted,
            access=a.access, lost_person_days=a.lost_person_days, weighted_loss=a.weighted_loss,
        ))
        return state

    def to_dataset(self) -> xr.Dataset:
        r = self.rows
        stack = lambda k: np.stack([x[k] for x in r])
        coords = {"time": pd.DatetimeIndex([x["date"] for x in r], name="time"),
                  "patch": list(self.net.patches), "hospital": list(self.net.hospitals),
                  "node": list(self.nodes)}
        th, tp = ("time", "hospital"), ("time", "patch")
        return xr.Dataset({
            "new_hosp": (tp, stack("new_hosp")), "prevalence": (tp, stack("prevalence")),
            "r_eff": (("time",), stack("r_eff")),
            "arrivals": (th, stack("arrivals")),
            "occupancy_ward": (th, stack("occupancy_ward")), "occupancy_icu": (th, stack("occupancy_icu")),
            "operability": (th, stack("operability")), "on_diversion": (th, stack("on_diversion")),
            "node_operability": (("time", "node"), stack("node_P")),
            "diverted_patients": (("time",), stack("diverted_patients")),
            "overflow": (("time",), stack("overflow")),
            "access": (tp, stack("access")), "lost_person_days": (tp, stack("lost_person_days")),
            "weighted_loss": (tp, stack("weighted_loss")),
        }, coords=coords)
