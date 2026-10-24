"""Injection resolution into per-week ScenarioInputs.

Applied from the immutable base config each week (no compounding). Edge changes
produce a fully resolved ``effective_edges`` list (adds/sets applied, removals
omitted). Contradictions on the same property/week are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import InvalidInjection, NetworkConfig
from .types import Edge


@dataclass
class ScenarioInputs:
    week: int
    effective_capacity: dict[str, float]
    closed: set[str]
    score_caps: dict[str, float]  # hospital -> operability cap (<=100)
    shares_override: dict[tuple[str, str], float]
    effective_edges: list[Edge]
    active_injections: tuple = ()


def _base_hospital_edges(hospitals, net: NetworkConfig) -> list[Edge]:
    """Symmetric hospital<->hospital edges within hospital_link_radius_km."""
    from .accessibility import haversine_km

    edges: list[Edge] = []
    hs = sorted(hospitals, key=lambda h: h.hospital_id)
    for i in range(len(hs)):
        for k in range(i + 1, len(hs)):
            a, b = hs[i], hs[k]
            d = haversine_km(a.lat, a.lon, b.lat, b.lon)
            if d <= net.hospital_link_radius_km:
                edges.append(
                    Edge(
                        a.hospital_id,
                        b.hospital_id,
                        "hospital_hospital",
                        net.alpha_h,
                        net.beta_h,
                    )
                )
                edges.append(
                    Edge(
                        b.hospital_id,
                        a.hospital_id,
                        "hospital_hospital",
                        net.alpha_h,
                        net.beta_h,
                    )
                )
    return edges


def resolve_scenario(week, hospitals, net, injections, district_ids=None) -> ScenarioInputs:
    hmap = {h.hospital_id: h for h in hospitals}
    hids = set(hmap)
    dids = set(district_ids) if district_ids is not None else None
    active = tuple(i for i in injections if i.active_at(week))

    def _check_hospital(hid, inj):
        if hid not in hids:
            raise InvalidInjection(f"{inj.injection_id} ({inj.kind}): unknown hospital {hid!r}")

    # Reject contradictions and unknown targets.
    seen_cap: set[str] = set()
    seen_setscore: set[str] = set()
    seen_share: set[tuple[str, str]] = set()
    seen_edge: set[tuple[str, str]] = set()
    for inj in active:
        p = inj.payload
        k = inj.kind
        if k in ("close_hospital", "set_capacity"):
            hid = p["hospital_id"]
            _check_hospital(hid, inj)
            if hid in seen_cap:
                raise InvalidInjection(
                    f"conflicting capacity/closure injections for {hid} in week {week}"
                )
            seen_cap.add(hid)
        elif k == "set_score":
            hid = p["hospital_id"]
            _check_hospital(hid, inj)
            if hid in seen_setscore:
                raise InvalidInjection(f"conflicting set_score injections for {hid} in week {week}")
            seen_setscore.add(hid)
        elif k == "reduce_score":
            _check_hospital(p["hospital_id"], inj)
        elif k in ("add_edge", "set_edge", "remove_edge"):
            a, b = p["hospital_a"], p["hospital_b"]
            _check_hospital(a, inj)
            _check_hospital(b, inj)
            key = tuple(sorted((a, b)))
            if key in seen_edge:
                raise InvalidInjection(f"conflicting edge injections for {key} in week {week}")
            seen_edge.add(key)
        elif k == "set_share":
            hid = p["hospital_id"]
            _check_hospital(hid, inj)
            if dids is not None and p["district_id"] not in dids:
                raise InvalidInjection(f"{inj.injection_id}: unknown district {p['district_id']!r}")
            skey = (p["district_id"], hid)
            if skey in seen_share:
                raise InvalidInjection(
                    f"conflicting set_share injections for {skey} in week {week}"
                )
            seen_share.add(skey)

    effective_capacity = {h.hospital_id: float(h.staffed_beds) for h in hospitals}
    closed: set[str] = set()
    score_caps: dict[str, float] = {}
    shares_override: dict[tuple[str, str], float] = {}

    # Edge state: dict keyed by (feeder, receiver)
    base_edges = _base_hospital_edges(hospitals, net)
    edge_map: dict[tuple[str, str], Edge] = {(e.feeder, e.receiver): e for e in base_edges}

    for inj in sorted(active, key=lambda i: i.injection_id):
        p = inj.payload
        k = inj.kind
        if k == "close_hospital":
            hid = p["hospital_id"]
            if hid not in hmap:
                raise InvalidInjection(f"close_hospital: unknown hospital {hid}")
            effective_capacity[hid] = 0.0
            closed.add(hid)
            score_caps[hid] = 0.0
        elif k == "set_capacity":
            hid = p["hospital_id"]
            if hid not in hmap:
                raise InvalidInjection(f"set_capacity: unknown hospital {hid}")
            effective_capacity[hid] = hmap[hid].staffed_beds * float(p["factor"])
            if p["factor"] == 0:
                closed.add(hid)
                score_caps[hid] = 0.0
        elif k == "set_score":
            score_caps[p["hospital_id"]] = float(p["value"])
        elif k == "reduce_score":
            hid = p["hospital_id"]
            cur = score_caps.get(hid, 100.0)
            score_caps[hid] = max(0.0, cur - float(p["points"]))
        elif k in ("add_edge", "set_edge"):
            a, b = p["hospital_a"], p["hospital_b"]
            for fa, fb in ((a, b), (b, a)):  # symmetric by default
                edge_map[(fa, fb)] = Edge(
                    fa, fb, "hospital_hospital", float(p["alpha"]), float(p["beta"])
                )
        elif k == "remove_edge":
            a, b = p["hospital_a"], p["hospital_b"]
            edge_map.pop((a, b), None)
            edge_map.pop((b, a), None)
        elif k == "set_share":
            shares_override[(p["district_id"], p["hospital_id"])] = float(p["share"])

    return ScenarioInputs(
        week=week,
        effective_capacity=effective_capacity,
        closed=closed,
        score_caps=score_caps,
        shares_override=shares_override,
        effective_edges=list(edge_map.values()),
        active_injections=active,
    )
