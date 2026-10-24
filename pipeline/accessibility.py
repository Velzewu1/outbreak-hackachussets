"""ACCESS stage: haversine distances, accessibility kernel, catchment shares.

``build_accessibility`` reused by patient placement (IL2) and district FDNA.
"""

from __future__ import annotations

import math

from .contracts import DataValidationError, District, Hospital, NetworkConfig  # noqa: F401
from .types import Accessibility

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km from WGS84 degrees (converted to radians)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _kernel(d_km: float, cfg: NetworkConfig) -> float:
    if cfg.distance_shape == "inverse_square":
        return 1.0 / (1.0 + (d_km / cfg.d0_km) ** 2)
    return math.exp(-d_km / cfg.d0_km)


def build_accessibility(
    districts, hospitals, net: NetworkConfig, nearest_fallback: bool = False
) -> Accessibility:
    """districts: list[District]; hospitals: list[Hospital].

    If ``nearest_fallback`` is True, a district with no hospital within
    ``radius_km`` is assigned its single NEAREST hospital (share 1.0), with the
    fact recorded. This is an explicit, documented fallback (never silent); it
    discloses that the district's nearest care is beyond the normal radius. When
    False (default), an uncovered district raises.
    """
    net.validate()
    fallback_districts: list[str] = []
    district_ids = tuple(sorted(d.district_id for d in districts))
    hospital_ids = tuple(sorted(h.hospital_id for h in hospitals))
    dmap = {d.district_id: d for d in districts}
    hmap = {h.hospital_id: h for h in hospitals}

    distance_km: dict[tuple[str, str], float] = {}
    eligible: dict[tuple[str, str], bool] = {}
    a: dict[tuple[str, str], float] = {}
    shares: dict[tuple[str, str], float] = {}
    total_accessibility: dict[str, float] = {}

    for j in district_ids:
        d = dmap[j]
        # distances to all hospitals
        dists = []
        for h in hospital_ids:
            hh = hmap[h]
            dk = haversine_km(d.centroid_lat, d.centroid_lon, hh.lat, hh.lon)
            distance_km[(j, h)] = dk
            dists.append((dk, h))
        # eligibility: within radius, then nearest k
        within = sorted(
            ((dk, h) for dk, h in dists if dk <= net.radius_km),
            key=lambda t: (t[0], t[1]),
        )
        kept = {h for _, h in within[: net.k_nearest]}
        if not kept and nearest_fallback:
            # Documented fallback: assign the single nearest hospital.
            nearest = min(dists, key=lambda t: (t[0], t[1]))
            kept = {nearest[1]}
            fallback_districts.append(j)
        # kernel + shares over kept
        a_vals = {}
        for h in hospital_ids:
            is_elig = h in kept
            eligible[(j, h)] = is_elig
            av = _kernel(distance_km[(j, h)], net) if is_elig else 0.0
            a[(j, h)] = av
            if is_elig:
                a_vals[h] = av
        denom = sum(a_vals.values())
        total_accessibility[j] = denom
        for h in hospital_ids:
            shares[(j, h)] = (a[(j, h)] / denom) if (denom > 0 and eligible[(j, h)]) else 0.0

    no_catchment = [j for j in district_ids if total_accessibility[j] <= 0.0]
    if no_catchment:
        raise DataValidationError(
            "districts have no eligible hospital within radius_km="
            f"{net.radius_km} / k_nearest={net.k_nearest}: {no_catchment}. "
            "Widen radius/k, add hospitals, or enable nearest_fallback."
        )
    return Accessibility(
        district_ids=district_ids,
        hospital_ids=hospital_ids,
        distance_km=distance_km,
        eligible=eligible,
        a=a,
        shares=shares,
        total_accessibility=total_accessibility,
        fallback_districts=tuple(sorted(fallback_districts)),
    )
