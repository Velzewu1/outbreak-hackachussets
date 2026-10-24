"""Static description of the hospital network: who exists, how big, how far.

Built once per scenario from processed data and shared read-only by
allocation, FDNA, rerouting and equity.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, Field, model_validator


class HospitalSpec(BaseModel):
    id: str                          # short key used in node names, e.g. "MGH"
    ccn: str | None = None           # CMS certification number, join key to HHS
    name: str = ""
    ward_beds: float = Field(gt=0)
    icu_beds: float = Field(ge=0)
    er: bool = True
    baseline_occupancy: float = Field(default=0.75, ge=0, lt=1)   # non-COVID share of beds in use


class NetworkConfig(BaseModel):
    hospitals: list[HospitalSpec]
    # travel_minutes[patch][hospital], in the patch order of the epi config
    travel_minutes: list[list[float]]

    @model_validator(mode="after")
    def _check(self) -> "NetworkConfig":
        ids = [h.id for h in self.hospitals]
        if len(set(ids)) != len(ids):
            raise ValueError("hospital ids must be unique")
        if any(len(row) != len(ids) for row in self.travel_minutes):
            raise ValueError("each travel_minutes row needs one value per hospital")
        return self


@dataclass(frozen=True)
class Network:
    patches: tuple[str, ...]
    hospitals: tuple[str, ...]
    ward_beds: np.ndarray            # [hospital]
    icu_beds: np.ndarray             # [hospital]
    has_er: np.ndarray               # [hospital] bool
    baseline_occupancy: np.ndarray   # [hospital]
    travel: np.ndarray               # [patch, hospital] minutes

    @classmethod
    def from_config(cls, cfg: NetworkConfig, patches) -> "Network":
        travel = np.asarray(cfg.travel_minutes, dtype=float)
        if travel.shape[0] != len(patches):
            raise ValueError(f"travel_minutes has {travel.shape[0]} rows for {len(patches)} patches")
        hs = cfg.hospitals
        return cls(
            patches=tuple(patches), hospitals=tuple(h.id for h in hs),
            ward_beds=np.array([h.ward_beds for h in hs], float),
            icu_beds=np.array([h.icu_beds for h in hs], float),
            has_er=np.array([h.er for h in hs], bool),
            baseline_occupancy=np.array([h.baseline_occupancy for h in hs], float),
            travel=travel,
        )

    @property
    def n_hospitals(self) -> int:
        return len(self.hospitals)

    def gravity_shares(self, decay: float, open_mask: np.ndarray | None = None) -> np.ndarray:
        """Share of each patch's admissions going to each hospital: beds * exp(-decay * minutes)."""
        mask = self.has_er if open_mask is None else self.has_er & open_mask
        w = (self.ward_beds + self.icu_beds) * np.exp(-decay * self.travel) * mask
        total = w.sum(axis=1, keepdims=True)
        return np.divide(w, total, out=np.zeros_like(w), where=total > 0)
