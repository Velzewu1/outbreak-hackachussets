"""Builds the city's FDNA graph from a per-hospital template plus shared nodes."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..network import Network
from .graph import Edge, FDNAGraph
from .resources import BedBuffer, EMSFleet, Fixed, StaffPool


class EdgeSpec(BaseModel):
    src: str
    dst: str = "hospital"
    sod: float = Field(ge=0, le=1)
    cod: float = Field(default=100.0, ge=0, le=100)


class SharedNode(BaseModel):
    node: str
    kind: str = "fixed"          # "ems" or "fixed"
    value: float = 100.0         # for kind="fixed"
    sod: float = Field(ge=0, le=1)
    cod: float = Field(default=100.0, ge=0, le=100)
    hospitals: list[str] | None = None   # None = feeds every hospital


class FDNAConfig(BaseModel):
    # Edges inside each hospital. Node names are local: "staff", "icu", "ward", "hospital".
    per_hospital: list[EdgeSpec] = [
        EdgeSpec(src="staff", sod=0.8, cod=30),
        EdgeSpec(src="icu", sod=0.6, cod=40),
        EdgeSpec(src="ward", sod=0.5, cod=60),
    ]
    shared: list[SharedNode] = [SharedNode(node="ems", kind="ems", sod=0.3, cod=70)]
    staff_absence_per_prevalence: float = 4.0
    staff_fatigue_per_day: float = 0.004
    bed_buffer: float = 0.10
    # Feedback to SEIR: ICU death multiplier = 1 + icu_strain_mortality * (1 - ICU P / 100)
    icu_strain_mortality: float = 0.5


def build_graph(cfg: FDNAConfig, net: Network, shares) -> tuple[FDNAGraph, dict]:
    nodes, edges, providers = [], [], {}
    for h, hid in enumerate(net.hospitals):
        local = {"staff", "icu", "ward", "hospital"} | {e.src for e in cfg.per_hospital}
        nodes += [f"{hid}.{n}" for n in sorted(local)]
        for e in cfg.per_hospital:
            edges.append(Edge(f"{hid}.{e.src}", f"{hid}.{e.dst}", e.sod, e.cod))
        providers[f"{hid}.staff"] = StaffPool(h, shares, cfg.staff_absence_per_prevalence,
                                              cfg.staff_fatigue_per_day)
        providers[f"{hid}.icu"] = BedBuffer(h, "icu", cfg.bed_buffer)
        providers[f"{hid}.ward"] = BedBuffer(h, "ward", cfg.bed_buffer)
    for s in cfg.shared:
        nodes.append(s.node)
        providers[s.node] = EMSFleet() if s.kind == "ems" else Fixed(s.value)
        for hid in s.hospitals or net.hospitals:
            edges.append(Edge(s.node, f"{hid}.hospital", s.sod, s.cod))
    return FDNAGraph(nodes, edges), providers
