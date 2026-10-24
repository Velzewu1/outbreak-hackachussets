"""Real-data loaders: MassGIS Suffolk 2020 tracts + hospitals, HHS historical.

All inputs were downloaded from public/authorized sources and copied into
``data/raw/`` with checksums (see ``data/raw/MANIFEST.json``). Capacity is a
MIXED-ASSUMPTION proxy: MassGIS licensed ``TOTAL_BEDS`` are NOT staffed beds.

Scope decisions (documented, fixed before any scoring):
- Districts: 234 Suffolk 2020 census tracts (POP20, decennial 2020 vintage, NOT
  ACS). 4 zero-population tracts are EXCLUDED from disease modeling (geography may
  still be shown).
- Hospitals: general acute-care ADULT hospitals in Suffolk. Excluded with reason:
  pediatric-only (Boston Children's, Shriners', Franciscan), specialty (Mass Eye
  & Ear), cancer specialty (Dana-Farber + its inpatient unit), non-acute/rehab/
  psych (Hebrew Rehab, Spaulding, Lemuel Shattuck), zero-bed satellite ED
  (Neighborhealth), and historically-closed facilities absent from current
  geography (Carney).
- CCN crosswalk (HHS -> current facility): 220086 BIDMC aggregates East+West;
  220036 St Elizabeth's == current BMC Brighton (736 Cambridge St campus);
  220031 BMC; 220071 MGH; 220110 Brigham; 220116 Tufts; 220119 Faulkner;
  220088 New England Baptist.
"""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import DataValidationError, District, Hospital
from .data import DataBundle

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
TRACTS_FILE = RAW / "massgis-suffolk-tracts-2020.geojson"
HOSP_FILE = RAW / "massgis-suffolk-hospitals.json"
HHS_FILE = RAW / "hhs-suffolk-historical-2020-2021.json"

# MassGIS DPH_FACILITY_ID -> canonical model hospital, with HHS CCN crosswalk.
# Only INCLUDED facilities appear here. ICU/MED_SURG from MassGIS; TOTAL_BEDS is
# a licensed-bed proxy (mixed assumption).
INCLUDED_HOSPITALS = {
    "2168": {"id": "MGH", "ccn": "220071"},
    "2341": {"id": "BWH", "ccn": "220110"},
    "2092": {"id": "BIDMC_W", "ccn": "220086"},
    "2069": {"id": "BIDMC_E", "ccn": "220086"},
    "2307": {"id": "BMC_MENINO", "ccn": "220031"},
    "2085": {"id": "BMC_BRIGHTON", "ccn": "220036"},
    "2299": {"id": "TUFTS", "ccn": "220116"},
    "2048": {"id": "FAULKNER", "ccn": "220119"},
    "2059": {"id": "NEBAPTIST", "ccn": "220088"},
}

# Documented exclusions (DPH_FACILITY_ID -> reason).
EXCLUDED_HOSPITALS = {
    "2139": "pediatric-only (Boston Children's)",
    "2316": "pediatric-only (Shriners')",
    "2221": "pediatric-only (Franciscan)",
    "2167": "specialty eye/ear (Mass Eye & Ear)",
    "2335": "cancer specialty (Dana-Farber)",
    "2PW6": "cancer specialty inpatient unit (Dana-Farber) - avoids duplicate DFCI",
    "2290": "non-acute (Hebrew Rehabilitation Center)",
    "2321": "non-acute rehab (Spaulding)",
    "2821": "non-acute (Lemuel Shattuck)",
    "21PE": "zero-bed satellite ED (Neighborhealth)",
}


def real_available() -> bool:
    return TRACTS_FILE.exists() and HOSP_FILE.exists()


def _load_hospitals(baseline_fraction: float) -> tuple[list[Hospital], dict]:
    """baseline_fraction comes from RunConfig (no hidden second default)."""
    data = json.loads(HOSP_FILE.read_text())
    feats = data["features"]
    hospitals = []
    crosswalk = []
    for f in feats:
        a = f["attributes"]
        g = f["geometry"]
        fid = str(a.get("DPH_FACILITY_ID"))
        if fid not in INCLUDED_HOSPITALS:
            continue
        meta = INCLUDED_HOSPITALS[fid]
        total = int(a.get("TOTAL_BEDS") or 0)
        icu = int(a.get("ICU") or 0)
        if total <= 0:
            raise DataValidationError(f"included hospital {fid} has non-positive TOTAL_BEDS")
        # baseline occupancy proxy = baseline_fraction * licensed beds, as a COUNT.
        # The fraction is a single sourced assumption from RunConfig.
        baseline = round(baseline_fraction * total, 1)
        hospitals.append(
            Hospital(
                hospital_id=meta["id"],
                name=str(a.get("FACILITY_NAME")),
                lat=float(g["y"]),
                lon=float(g["x"]),
                staffed_beds=total,  # licensed proxy; mixed assumption
                icu_beds=icu,
                baseline_occupancy=baseline,
            ).validate()
        )
        crosswalk.append(
            {
                "dph_facility_id": fid,
                "model_id": meta["id"],
                "ccn": meta["ccn"],
                "massgis_name": a.get("FACILITY_NAME"),
                "licensed_total_beds": total,
                "icu_beds": icu,
                "baseline_fraction": baseline_fraction,
                "review_status": "reviewed",
            }
        )
    hospitals.sort(key=lambda h: h.hospital_id)
    return hospitals, {
        "crosswalk": crosswalk,
        "excluded": EXCLUDED_HOSPITALS,
        "baseline_fraction_source": "RunConfig.baseline_fraction",
    }


def _load_tracts() -> tuple[list[District], dict]:
    """Model districts = POSITIVE-population Suffolk 2020 tracts only. Zero-pop
    tract polygons are preserved separately (geometry kept for mapping) and
    EXCLUDED from disease modeling with a diagnostic. No invented population."""
    data = json.loads(TRACTS_FILE.read_text())
    feats = data["features"]
    districts = []
    zero_pop_geoms = {}
    seen = set()
    for f in feats:
        p = f["properties"]
        gid = str(p["GEOID20"])
        if gid in seen:
            raise DataValidationError(f"duplicate tract GEOID20 {gid}")
        seen.add(gid)
        pop = int(p["POP20"])
        lat = float(p["INTPTLAT20"])
        lon = float(p["INTPTLON20"])
        if pop <= 0:
            zero_pop_geoms[gid] = f.get("geometry")  # preserved, not modeled
            continue
        districts.append(
            District(
                district_id=gid,
                population=pop,
                risk_weight=1.0,  # no sourced risk weight; labeled assumption
                ej_flag=None,  # EJ not joined in this pass -> unknown
                centroid_lat=lat,
                centroid_lon=lon,
                geometry=f.get("geometry"),
            ).validate()
        )
    districts.sort(key=lambda d: d.district_id)
    return districts, {
        "population_vintage": "Census 2020 decennial (POP20), NOT ACS",
        "zero_pop_excluded": sorted(zero_pop_geoms),
        "zero_pop_geometries": zero_pop_geoms,
        "n_tracts_total": len(feats),
        "n_tracts_modeled": len(districts),
    }


def load_real_bundle(baseline_fraction: float = 0.75) -> tuple[DataBundle, dict]:
    """Returns (DataBundle, observed_hhs). ``baseline_fraction`` is sourced from
    RunConfig by the caller. Radius coverage is checked by build_accessibility,
    which raises on uncovered tracts (verified: all 230 positive-pop tracts are
    covered at the default 10 km)."""
    hospitals, hmeta = _load_hospitals(baseline_fraction)
    districts, tmeta = _load_tracts()
    observed = _load_hhs_observed()
    manifest = {
        "source": "massgis+hhs",
        "label": "Real geography + licensed-bed proxy + simulated epidemic",
        "population": tmeta,
        "hospitals": hmeta,
        "capacity_note": "staffed_beds uses MassGIS licensed TOTAL_BEDS (proxy); "
        "NOT verified staffed beds -> mixed_assumptions",
        "observed_note": "HHS inpatient_beds_used_covid_7_day_avg is a weekly MEAN; "
        "the backtest declares a weekly-batch observation operator (limitation).",
    }
    bundle = DataBundle(
        districts=districts,
        hospitals=hospitals,
        seeded_cohorts={},
        data_mode="mixed_assumptions",
        manifest=manifest,
    )
    return bundle, observed


def _load_hhs_observed() -> dict:
    """Observed COVID-occupied-bed weekly means keyed by (ccn, week).

    Detects duplicate (ccn, week) keys (records them, never silently overwrites),
    marks suppressed/missing/nonfinite per record, and keeps coverage."""
    import math

    if not HHS_FILE.exists():
        return {"status": "unavailable", "rows": []}
    data = json.loads(HHS_FILE.read_text())
    rows = []
    seen: set[tuple] = set()
    duplicates = []
    for x in data:
        wk = x.get("collection_week", "")[:10]
        ccn = x.get("ccn")
        key = (ccn, wk)
        if key in seen:
            duplicates.append(key)
            continue
        seen.add(key)
        covid = x.get("inpatient_beds_used_covid_7_day_avg")
        used = x.get("inpatient_beds_used_7_day_avg")
        try:
            covid = float(covid)
        except (TypeError, ValueError):
            covid = None
        suppressed = covid is None or not math.isfinite(covid) or covid < 0
        try:
            coverage = int(x.get("inpatient_beds_used_covid_7_day_coverage"))
        except (TypeError, ValueError):
            coverage = None
        rows.append(
            {
                "ccn": ccn,
                "week": wk,
                "covid_mean": None if suppressed else covid,
                "used_mean": _safe_float(used),
                "coverage": coverage,
                "suppressed": suppressed,
            }
        )
    if duplicates:
        raise DataValidationError(f"duplicate HHS (ccn, week) keys: {duplicates}")
    return {
        "status": "available",
        "rows": rows,
        "period": ["2020-10-04", "2021-05-30"],
        "source_url": "https://healthdata.gov/resource/anag-cw7u.json",
    }


def _safe_float(v):
    try:
        f = float(v)
        return f if f >= 0 else None
    except (TypeError, ValueError):
        return None
