"""FDNA as a Module in the daily loop."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..contracts import Operability
from ..core import SimState
from ..network import Network
from .build import FDNAConfig, build_graph


class Event(BaseModel):
    """Scenario knock-out: cap a node's operability at `value` from day `start` to `end`."""
    node: str
    value: float = 0.0
    start: int = 0
    end: int | None = None


class FDNAModule:
    name = "fdna"

    def __init__(self, network: Network, shares: np.ndarray, cfg: FDNAConfig | None = None,
                 events: list[Event] = (), overrides: dict[str, float] | None = None):
        self.net, self.shares = network, shares
        self.cfg = cfg or FDNAConfig()
        self.graph, self.providers = build_graph(self.cfg, network, shares)
        self.events = list(events)
        self.overrides = dict(overrides or {})      # whole-run caps, used by the criticality sweep
        unknown = ({e.node for e in self.events} | set(self.overrides)) - set(self.graph.nodes)
        if unknown:
            raise ValueError(f"events or overrides name unknown FDNA nodes: {sorted(unknown)}")
        self._hosp_idx = np.array([self.graph.index[f"{h}.hospital"] for h in network.hospitals])
        self._icu_idx = np.array([self.graph.index[f"{h}.icu"] for h in network.hospitals])

    def step(self, state: SimState, t: int) -> SimState:
        base = {n: p(state, self.net) for n, p in self.providers.items()}
        for e in self.events:
            if e.start <= t and (e.end is None or t < e.end):
                base[e.node] = min(base.get(e.node, 100.0), e.value)
        for n, v in self.overrides.items():
            base[n] = min(base.get(n, 100.0), v)
        P = self.graph.evaluate(base)
        state.fdna = Operability(day=t, nodes=self.graph.nodes, P=P, hospital_P=P[self._hosp_idx])
        # Feedback for tomorrow's SEIR step: ICU strain in each patch's hospitals.
        icu_P = self.shares @ P[self._icu_idx]                       # [patch]
        mult = 1.0 + self.cfg.icu_strain_mortality * (1.0 - icu_P / 100.0)
        state.signals.setdefault("seir", {})["icu_mortality_multiplier"] = mult
        return state
