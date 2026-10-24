"""FDNA tests: golden 0/50/75, cyclic convergence, alpha_h=0 (beta caveat),
closed node stays 0, ID-order independence, non-convergence is impossible under
the monotone map (we assert convergence)."""

from __future__ import annotations

import pytest

from pipeline.contracts import FDNASettings, NetworkConfig
from pipeline.fdna import solve_districts, solve_hospitals
from pipeline.types import Accessibility, Edge, FDNAGraph, HospitalLoad


def _load(hid, own):
    return HospitalLoad(hid, 0, 0, 0, 0, 100, own, 0, False)


def _graph(hids, edges=()):
    return FDNAGraph(tuple(hids), (), tuple(edges))


FS = FDNASettings()


def test_district_golden_0_50_75():
    net = NetworkConfig(alpha_d=0.9)

    # Build a minimal accessibility with equal shares for n hospitals.
    def district_score(n):
        hids = [f"H{i}" for i in range(n)]
        shares = {("J", h): 1.0 / n for h in hids}
        # one failed hospital (H0 -> 0), rest 100
        scores = {h: (0.0 if h == "H0" else 100.0) for h in hids}
        acc = Accessibility(("J",), tuple(hids), {}, {}, {}, shares, {"J": 1.0})
        sbd = {"J": {h: shares[("J", h)] for h in hids}}
        return solve_districts(scores, acc, net, sbd)["J"]

    assert abs(district_score(1) - 0.0) < 1e-9
    assert abs(district_score(2) - 50.0) < 1e-9
    assert abs(district_score(4) - 75.0) < 1e-9


def test_cyclic_hospital_converges():
    # H1 closed (own 0), H2 healthy (own 100), symmetric edge alpha 0.1 beta 100
    loads = {"H1": _load("H1", 0.0), "H2": _load("H2", 100.0)}
    edges = [
        Edge("H1", "H2", "hospital_hospital", 0.1, 100.0),
        Edge("H2", "H1", "hospital_hospital", 0.1, 100.0),
    ]
    g = _graph(["H1", "H2"], edges)
    scores, iters, conv, delta = solve_hospitals(loads, g, FS)
    assert conv
    assert scores["H1"] == 0.0  # closed node stays 0
    assert scores["H2"] < 100.0  # healthy neighbor degraded by shared-resource link
    assert scores["H2"] >= 90.0  # alpha 0.1 => small degradation


def test_alpha_h_zero_no_spillover_with_beta_100():
    loads = {"H1": _load("H1", 0.0), "H2": _load("H2", 100.0)}
    edges = [
        Edge("H1", "H2", "hospital_hospital", 0.0, 100.0),
        Edge("H2", "H1", "hospital_hospital", 0.0, 100.0),
    ]
    g = _graph(["H1", "H2"], edges)
    scores, *_ = solve_hospitals(loads, g, FS)
    assert scores["H2"] == 100.0  # no spillover when alpha_h=0 and beta_h=100


def test_small_beta_still_caps_even_with_alpha_zero():
    # beta_h < 100 means criticality can cap a neighbor regardless of alpha
    loads = {"H1": _load("H1", 0.0), "H2": _load("H2", 100.0)}
    edges = [
        Edge("H1", "H2", "hospital_hospital", 0.0, 30.0),
        Edge("H2", "H1", "hospital_hospital", 0.0, 30.0),
    ]
    g = _graph(["H1", "H2"], edges)
    scores, *_ = solve_hospitals(loads, g, FS)
    assert scores["H2"] == pytest.approx(30.0)  # capped at P(H1)+beta = 0+30


def test_id_order_independence():
    loads = {"H2": _load("H2", 40.0), "H1": _load("H1", 80.0)}
    edges = [
        Edge("H1", "H2", "hospital_hospital", 0.1, 100.0),
        Edge("H2", "H1", "hospital_hospital", 0.1, 100.0),
    ]
    g1 = _graph(["H1", "H2"], edges)
    g2 = _graph(["H2", "H1"], edges)
    s1, *_ = solve_hospitals(loads, g1, FS)
    s2, *_ = solve_hospitals(loads, g2, FS)
    assert abs(s1["H1"] - s2["H1"]) < 1e-9
    assert abs(s1["H2"] - s2["H2"]) < 1e-9
