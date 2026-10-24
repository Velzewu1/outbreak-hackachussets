"""FDNA-based operability propagation (two passes per week).

Hospital synchronous (Jacobi) fixed point over symmetric cycles with an
own-score cap; share-weighted district SOD/COD. Non-convergence is an error.
Scores never change physical beds.
"""

from __future__ import annotations

from .contracts import FDNAConvergenceError, FDNASettings, NetworkConfig
from .types import Accessibility, FDNAGraph, FDNAResult, HospitalLoad


def solve_hospitals(
    loads: dict[str, HospitalLoad], graph: FDNAGraph, fdna: FDNASettings
) -> tuple[dict[str, float], int, bool, float]:
    own = {h: loads[h].own_score for h in graph.hospital_nodes}
    # neighbors: hospital_hospital edges, receiver <- feeder
    nbrs: dict[str, list[tuple[str, float, float]]] = {h: [] for h in graph.hospital_nodes}
    for e in graph.edges:
        if e.kind == "hospital_hospital":
            nbrs[e.receiver].append((e.feeder, e.alpha, e.beta))

    P = dict(own)
    delta = 0.0
    for it in range(1, fdna.max_iterations + 1):
        newP = {}
        for h in graph.hospital_nodes:
            ns = nbrs[h]
            if not ns:
                newP[h] = own[h]
                continue
            strengths = [al * P[m] + (1.0 - al) * own[h] for (m, al, be) in ns]
            crits = [P[m] + be for (m, al, be) in ns]
            val = min(own[h], sum(strengths) / len(strengths), min(crits))
            newP[h] = max(0.0, min(100.0, val))
        delta = max(abs(newP[h] - P[h]) for h in graph.hospital_nodes)
        P = newP
        if delta <= fdna.convergence_tol_points:
            return P, it, True, delta
    raise FDNAConvergenceError(
        f"FDNA hospital solve did not converge in {fdna.max_iterations} iterations "
        f"(max_delta={delta})"
    )


def solve_districts(
    hospital_scores: dict[str, float], acc: Accessibility, net: NetworkConfig, shares_by_district
) -> dict[str, float]:
    out: dict[str, float] = {}
    ad = net.alpha_d
    for j in acc.district_ids:
        shares = shares_by_district[j]
        if not shares:
            out[j] = 100.0
            continue
        sod = ad * sum(s * hospital_scores[h] for h, s in shares.items()) + (1.0 - ad) * 100.0
        cod = min(hospital_scores[h] + 100.0 * (1.0 - s) for h, s in shares.items())
        out[j] = max(0.0, min(100.0, min(sod, cod)))
    return out


def solve(
    loads: dict[str, HospitalLoad],
    graph: FDNAGraph,
    acc: Accessibility,
    net: NetworkConfig,
    fdna: FDNASettings,
    shares_by_district,
) -> FDNAResult:
    hscores, iters, conv, delta = solve_hospitals(loads, graph, fdna)
    dscores = solve_districts(hscores, acc, net, shares_by_district)
    return FDNAResult(
        hospital_scores=hscores,
        district_scores=dscores,
        iterations=iters,
        converged=conv,
        max_delta=delta,
    )
