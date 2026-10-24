"""ANALYSIS: direct reservation (provisional BEFORE) and row-preserving global
reroute (final AFTER). New-admission requests only; baseline/retained immovable;
closed hospitals never receive; origin IDs preserved; redirected subset accepted.
Zero moves => AFTER identical to BEFORE.
"""

from __future__ import annotations

from .injections import ScenarioInputs
from .types import Accessibility, AllocationSnapshot, RequestTable, RerouteRecord


def _free_new(ceff, baseline, retained, accepted_so_far, eps):
    v = ceff - baseline - retained - accepted_so_far
    return v if v > eps else 0.0


def _eff_share(shares_by_district, district, hospital, acc):
    """Effective share honoring set_share overrides; falls back to base share."""
    sbd = shares_by_district.get(district, {})
    if hospital in sbd:
        return sbd[hospital]
    return acc.shares.get((district, hospital), 0.0)


def reserve_direct(
    requests: RequestTable,
    baseline: dict[str, float],
    retained: dict[str, float],
    scn: ScenarioInputs,
    acc: Accessibility,
    eps: float,
    shares_by_district: dict | None = None,
) -> AllocationSnapshot:
    """Provisional BEFORE allocation. Direct order: districts ascending id;
    within a district, candidate hospitals by descending EFFECTIVE share, tie
    (distance, id). Effective shares honor set_share overrides."""
    sbd = shares_by_district or {}
    accepted_i: dict[str, float] = {h: 0.0 for h in acc.hospital_ids}
    accepted: dict[tuple[str, str], float] = {}
    residual_rows: dict[tuple[str, str], float] = {}

    for j in sorted(acc.district_ids):
        rows = [(d, h) for (d, h) in requests.rows if d == j]
        # candidate order: descending EFFECTIVE share, tie (distance, hospital_id)
        rows.sort(
            key=lambda key: (
                -_eff_share(sbd, key[0], key[1], acc),
                acc.distance_km[key],
                key[1],
            )
        )
        for d, h in rows:
            row = requests.rows[(d, h)]
            if h in scn.closed:
                residual_rows[(d, h)] = row.requested
                row.direct_accepted = 0.0
                row.residual = row.requested
                continue
            fn = _free_new(
                scn.effective_capacity.get(h, 0.0),
                baseline.get(h, 0.0),
                retained.get(h, 0.0),
                accepted_i[h],
                eps,
            )
            take = min(row.requested, fn)
            take = take if take > eps else 0.0
            row.direct_accepted = take
            row.residual = row.requested - take
            accepted_i[h] += take
            if take > 0:
                accepted[(d, h)] = accepted.get((d, h), 0.0) + take
            residual_rows[(d, h)] = row.residual

    unmet = _unmet_by_district(residual_rows, acc)
    proj = {
        h: baseline.get(h, 0.0) + retained.get(h, 0.0) + accepted_i[h] for h in acc.hospital_ids
    }
    return AllocationSnapshot(
        phase="before",
        accepted=accepted,
        residual_rows=residual_rows,
        unmet_by_district=unmet,
        projected_occupancy=proj,
        reroute_volume=0.0,
        reroutes=[],
    )


def reroute(
    before: AllocationSnapshot,
    baseline: dict[str, float],
    retained: dict[str, float],
    scn: ScenarioInputs,
    acc: Accessibility,
    week: int,
    eps: float,
    shares_by_district: dict | None = None,
) -> AllocationSnapshot:
    """Final AFTER allocation. Consume residual rows (descending residual,
    tie (district, source)) into destinations with spare free_new, ordered by
    descending EFFECTIVE share. Residuals that remain stay on their original
    (district, source) row."""
    sbd = shares_by_district or {}
    accepted = dict(before.accepted)
    residual_rows = dict(before.residual_rows)
    accepted_i: dict[str, float] = {h: 0.0 for h in acc.hospital_ids}
    for (_d, h), v in accepted.items():
        accepted_i[h] += v

    reroutes: list[RerouteRecord] = []
    rows = sorted(
        [(key, residual_rows[key]) for key in residual_rows if residual_rows[key] > eps],
        key=lambda kv: (-kv[1], kv[0][0], kv[0][1]),
    )
    for (district, source), _resid in rows:
        rem = residual_rows[(district, source)]
        # candidate destinations: district's eligible hospitals by descending
        # EFFECTIVE share (honors set_share), tie (distance, id).
        cands = sorted(
            acc.eligible_hospitals(district),
            key=lambda c: (
                -_eff_share(sbd, district, c, acc),
                acc.distance_km[(district, c)],
                c,
            ),
        )
        for c in cands:
            if rem <= eps or c == source or c in scn.closed:
                continue
            fn = _free_new(
                scn.effective_capacity.get(c, 0.0),
                baseline.get(c, 0.0),
                retained.get(c, 0.0),
                accepted_i[c],
                eps,
            )
            if fn <= eps:
                continue
            mv = min(rem, fn)
            if mv <= eps:
                continue
            rem -= mv
            accepted_i[c] += mv
            accepted[(district, c)] = accepted.get((district, c), 0.0) + mv
            reroutes.append(RerouteRecord(week, district, source, c, mv))
        residual_rows[(district, source)] = rem

    unmet = _unmet_by_district(residual_rows, acc)
    proj = {
        h: baseline.get(h, 0.0) + retained.get(h, 0.0) + accepted_i[h] for h in acc.hospital_ids
    }
    vol = sum(r.amount for r in reroutes)
    return AllocationSnapshot(
        phase="after",
        accepted=accepted,
        residual_rows=residual_rows,
        unmet_by_district=unmet,
        projected_occupancy=proj,
        reroute_volume=vol,
        reroutes=reroutes,
    )


def post_request_i(alloc: AllocationSnapshot, hospital_ids) -> dict[str, float]:
    """accepted_final_i + residual rows still intended for i."""
    out = {}
    for h in hospital_ids:
        out[h] = alloc.accepted_i(h) + alloc.residual_intended_for(h)
    return out


def _unmet_by_district(residual_rows, acc: Accessibility) -> dict[str, float]:
    out = {j: 0.0 for j in acc.district_ids}
    for (d, _s), v in residual_rows.items():
        out[d] = out.get(d, 0.0) + max(0.0, v)
    return out
