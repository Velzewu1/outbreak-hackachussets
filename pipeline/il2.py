"""IL2: new-admission requests, requested-load hospital scores, FDNA graph.

Allocation operates on NEW-ADMISSION requests only. Own scores use the
requested-load (need) view. Graph carries ONLY FDNA dependency edges.
"""

from __future__ import annotations

from .contracts import DataValidationError
from .injections import ScenarioInputs
from .types import (
    Accessibility,
    Edge,
    FDNAGraph,
    HospitalLoad,
    RequestRow,
    RequestTable,
)


def effective_shares(acc: Accessibility, district_id: str, scn: ScenarioInputs) -> dict[str, float]:
    """Base shares with set_share overrides, renormalized to keep sum == 1."""
    elig = acc.eligible_hospitals(district_id)
    base = {h: acc.shares[(district_id, h)] for h in elig}
    # Reject a set_share whose target hospital is NOT in the district's eligible
    # catchment: a share edit never grants a route to an ineligible hospital.
    for (d, h), _v in scn.shares_override.items():
        if d == district_id and h not in base:
            raise DataValidationError(
                f"set_share targets hospital {h!r} which is not in district "
                f"{district_id!r}'s eligible catchment; a share edit cannot grant "
                f"a route to an ineligible hospital"
            )
    overrides = {
        h: v for (d, h), v in scn.shares_override.items() if d == district_id and h in base
    }
    if not overrides:
        return base
    # Pin overridden shares; distribute remaining mass proportionally to the rest.
    pinned_total = sum(overrides.values())
    if pinned_total > 1.0 + 1e-9:
        raise DataValidationError(
            f"set_share overrides for {district_id} sum to {pinned_total} > 1"
        )
    others = [h for h in base if h not in overrides]
    remaining = 1.0 - pinned_total
    if not others:
        # All eligible candidates pinned: they must sum to 1 exactly.
        if abs(pinned_total - 1.0) > 1e-9:
            raise DataValidationError(
                f"set_share overrides for {district_id} pin all eligible hospitals "
                f"but sum to {pinned_total} != 1"
            )
        return dict(overrides)
    others_base = sum(base[h] for h in others)
    out = dict(overrides)
    for h in others:
        if others_base > 0:
            out[h] = base[h] / others_base * remaining
        else:
            # Others had zero base share (degenerate): split remaining evenly.
            out[h] = remaining / len(others)
    # Numerical safety: shares must sum to 1 within tolerance.
    total = sum(out.values())
    if abs(total - 1.0) > 1e-9:
        raise DataValidationError(f"renormalized shares for {district_id} sum to {total} != 1")
    return out


def compute_requests(
    epi_h_need: dict[str, float], acc: Accessibility, scn: ScenarioInputs
) -> RequestTable:
    table = RequestTable()
    for j in acc.district_ids:
        shares = effective_shares(acc, j, scn)
        for h, s in shares.items():
            req = s * epi_h_need.get(j, 0.0)
            if req <= 0:
                continue
            table.rows[(j, h)] = RequestRow(
                district_id=j, hospital_id=h, requested=req, residual=req
            )
    return table


def _own_score(ceff: float, requested_load: float, closed: bool) -> float:
    if closed or ceff <= 0.0:
        return 0.0
    if requested_load <= 0.0:
        return 100.0
    return 100.0 * min(1.0, ceff / requested_load)


def compute_loads(
    hospital_ids,
    baseline: dict[str, float],
    retained: dict[str, float],
    load_request: dict[str, float],  # request_i (before) or post_request_i (after)
    scn: ScenarioInputs,
) -> dict[str, HospitalLoad]:
    loads: dict[str, HospitalLoad] = {}
    for h in hospital_ids:
        ceff = scn.effective_capacity.get(h, 0.0)
        closed = h in scn.closed
        rl = baseline.get(h, 0.0) + retained.get(h, 0.0) + load_request.get(h, 0.0)
        own = _own_score(ceff, rl, closed)
        # Apply operability cap from set_score/reduce_score (cannot create beds).
        if h in scn.score_caps:
            own = min(own, scn.score_caps[h])
        loads[h] = HospitalLoad(
            hospital_id=h,
            baseline=baseline.get(h, 0.0),
            retained=retained.get(h, 0.0),
            request_i=load_request.get(h, 0.0),
            requested_load=rl,
            effective_capacity=ceff,
            own_score=own,
            excess=max(0.0, rl - ceff),
            closed=closed,
        )
    return loads


def build_graph(acc: Accessibility, scn: ScenarioInputs) -> FDNAGraph:
    """Dependency edges only: hospital<->hospital (from scenario) and
    hospital->district (one per eligible share>0, share-weighted criticality)."""
    hospital_nodes = acc.hospital_ids
    district_nodes = acc.district_ids
    edges: list[Edge] = list(scn.effective_edges)  # hospital_hospital
    for j in district_nodes:
        shares = effective_shares(acc, j, scn)
        for h, s in shares.items():
            if s <= 0:
                continue
            edges.append(
                Edge(
                    feeder=h,
                    receiver=j,
                    kind="hospital_district",
                    alpha=0.0,
                    beta=100.0 * (1.0 - s),
                )  # alpha unused for district rule
            )
    return FDNAGraph(
        hospital_nodes=hospital_nodes, district_nodes=district_nodes, edges=tuple(edges)
    )
