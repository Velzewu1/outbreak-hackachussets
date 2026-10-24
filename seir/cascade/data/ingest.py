"""Raw project CSVs -> one validated hospitals table.

Ingestion is the only code that knows raw column names. Everything after it
reads the processed table, so a source can change format without touching
the model.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..network import HospitalSpec

HOSPITAL_COLUMNS = ["id", "ccn", "name", "county", "er", "overall_rating",
                    "icu_beds", "ward_beds", "campuses"]


def load_cms(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"facility_id": str})
    return df.rename(columns={"facility_id": "ccn", "facility_name": "cms_name"})


def load_massgis(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df.rename(columns={"name": "massgis_name", "med_surg_beds": "ward_beds"})


def build_hospitals(cms: pd.DataFrame, massgis: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Join CMS (CCN, ER flag) to MassGIS (beds) through a hand-made crosswalk.

    Several MassGIS campuses can share one CCN (BIDMC East and West); their
    beds are summed.
    """
    xw = crosswalk.astype({"ccn": str})
    missing = set(xw.massgis_name) - set(massgis.massgis_name)
    if missing:
        raise ValueError(f"crosswalk names not in MassGIS: {sorted(missing)}")
    missing = set(xw.ccn) - set(cms.ccn)
    if missing:
        raise ValueError(f"crosswalk CCNs not in CMS: {sorted(missing)}")
    beds = (xw.merge(massgis, on="massgis_name")
              .groupby(["id", "ccn"], as_index=False)
              .agg(icu_beds=("icu_beds", "sum"), ward_beds=("ward_beds", "sum"),
                   campuses=("massgis_name", "count")))
    out = beds.merge(cms[["ccn", "cms_name", "county", "emergency", "overall_rating"]], on="ccn")
    out = out.rename(columns={"cms_name": "name"})
    out["er"] = out.pop("emergency").eq("Yes")
    out = out[HOSPITAL_COLUMNS].sort_values("id", ignore_index=True)
    validate_hospitals(out)
    return out


def validate_hospitals(df: pd.DataFrame) -> None:
    if list(df.columns) != HOSPITAL_COLUMNS:
        raise ValueError(f"hospitals table columns {list(df.columns)} != {HOSPITAL_COLUMNS}")
    if df.id.duplicated().any():
        raise ValueError("duplicate hospital ids")
    if (df[["icu_beds", "ward_beds"]] < 0).any().any():
        raise ValueError("negative bed counts")


def to_specs(df: pd.DataFrame, ids: list[str] | None = None,
             baseline_occupancy: float = 0.75) -> list[HospitalSpec]:
    """Hospitals table -> NetworkConfig.hospitals. Drops sites with no ward beds."""
    rows = df if ids is None else df.set_index("id").loc[ids].reset_index()
    return [HospitalSpec(id=r.id, ccn=r.ccn, name=r.name, ward_beds=r.ward_beds,
                         icu_beds=r.icu_beds, er=bool(r.er), baseline_occupancy=baseline_occupancy)
            for r in rows.itertuples() if r.ward_beds > 0]


def build_from_project(healthcare_dir: str | Path, crosswalk_path: str | Path) -> pd.DataFrame:
    d = Path(healthcare_dir)
    return build_hospitals(load_cms(d / "cms-hospitals" / "data.csv"),
                           load_massgis(d / "hospitals" / "data.csv"),
                           pd.read_csv(crosswalk_path, dtype=str))
