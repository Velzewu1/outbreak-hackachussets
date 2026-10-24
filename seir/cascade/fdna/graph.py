"""FDNA dependency graph and the operability calculation (Garvey and Pinto).

For a receiver j with feeders i:
    SODP_j = (1/n) * sum_i [ alpha_ij * P_i + 100 * (1 - alpha_ij) ]
    CODP_j = min_i ( P_i + beta_ij )
    P_j    = min( SODP_j, CODP_j )
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    sod: float          # strength of dependency, alpha in [0, 1]
    cod: float = 100.0  # criticality of dependency, beta in [0, 100]; 100 = no cap

    def __post_init__(self):
        if not 0.0 <= self.sod <= 1.0:
            raise ValueError(f"SOD for {self.src}->{self.dst} must be in [0, 1]")
        if not 0.0 <= self.cod <= 100.0:
            raise ValueError(f"COD for {self.src}->{self.dst} must be in [0, 100]")


class FDNAGraph:
    """Compiled once per scenario: topological order plus feeder index arrays."""

    def __init__(self, nodes: list[str], edges: list[Edge]):
        g = nx.DiGraph()
        g.add_nodes_from(nodes)
        for e in edges:
            if e.src not in g or e.dst not in g:
                raise ValueError(f"edge {e.src}->{e.dst} names an unknown node")
            g.add_edge(e.src, e.dst, sod=e.sod, cod=e.cod)
        if not nx.is_directed_acyclic_graph(g):
            cycle = nx.find_cycle(g)
            raise ValueError(f"FDNA graph must be acyclic within a day; found cycle {cycle}")
        self.graph = g
        self.nodes = tuple(nx.lexicographical_topological_sort(g))
        self.index = {n: k for k, n in enumerate(self.nodes)}
        self.sources = tuple(n for n in self.nodes if g.in_degree(n) == 0)
        # For each receiver: feeder indices and their alpha / beta arrays.
        self._plan = []
        for n in self.nodes:
            preds = list(g.predecessors(n))
            if preds:
                self._plan.append((self.index[n],
                                   np.array([self.index[p] for p in preds]),
                                   np.array([g[p][n]["sod"] for p in preds]),
                                   np.array([g[p][n]["cod"] for p in preds])))

    def evaluate(self, base: dict[str, float]) -> np.ndarray:
        """Operability of every node, in self.nodes order.

        base gives P for source nodes (required) and an optional self-effectiveness
        cap for receivers (e.g. a scenario that knocks a hospital out directly).
        """
        missing = [n for n in self.sources if n not in base]
        if missing:
            raise KeyError(f"no operability given for source nodes {missing}")
        P = np.full(len(self.nodes), 100.0)
        for n, v in base.items():
            P[self.index[n]] = v
        for j, feeders, alpha, beta in self._plan:
            Pi = P[feeders]
            sodp = np.mean(alpha * Pi + 100.0 * (1.0 - alpha))
            codp = np.min(Pi + beta)
            cap = base.get(self.nodes[j], 100.0)
            P[j] = min(sodp, codp, cap)
        return np.clip(P, 0.0, 100.0)
