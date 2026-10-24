"""Canonical validated types and errors — the single definition of every
cross-module object (see ``contracts/``).

Design notes:
- IDs are stable strings; arrays/maps are ordered by sorted IDs.
- Units never mixed: bed counts are people/beds; scores 0-100; ``H_need`` and
  ``unmet`` are people/week (never beds); shares are fractions summing to 1.
- ``NaN``/``Infinity`` are rejected. Tuple-keyed maps serialize as sorted record
  arrays (see ``to_records``).
- These are lightweight dataclasses with explicit validation helpers. No module
  here imports Streamlit or any pipeline stage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class DataValidationError(ValueError):
    """Raised when input data violates a contract."""


class InvalidInjection(ValueError):
    """Raised when an injection is malformed or contradictory."""


class FDNAConvergenceError(RuntimeError):
    """Raised when the FDNA hospital fixed point does not converge."""


class ScenarioCompatibilityError(ValueError):
    """Raised when two runs cannot be compared (different geography/dates)."""


class MissingObservedData(RuntimeError):
    """Raised when a validation backtest is requested without observed data."""


# --------------------------------------------------------------------------- #
# Numeric guards
# --------------------------------------------------------------------------- #


def require_finite(value: float, name: str) -> float:
    """Reject NaN/Infinity; return the value unchanged if finite."""
    if value is None or not math.isfinite(float(value)):
        raise DataValidationError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def require_nonneg(value: float, name: str) -> float:
    require_finite(value, name)
    if value < 0:
        raise DataValidationError(f"{name} must be >= 0, got {value}")
    return float(value)


def require_prob(value: float, name: str) -> float:
    require_finite(value, name)
    if not (0.0 <= value <= 1.0):
        raise DataValidationError(f"{name} must be in [0, 1], got {value}")
    return float(value)


def require_score(value: float, name: str) -> float:
    require_finite(value, name)
    if not (-1e-9 <= value <= 100.0 + 1e-9):
        raise DataValidationError(f"{name} must be in [0, 100], got {value}")
    return float(min(100.0, max(0.0, value)))


def _require_latlon(lat: float, lon: float, owner: str) -> None:
    require_finite(lat, f"{owner}.lat")
    require_finite(lon, f"{owner}.lon")
    if not (-90.0 <= lat <= 90.0):
        raise DataValidationError(f"{owner}.lat out of range [-90,90]: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise DataValidationError(f"{owner}.lon out of range [-180,180]: {lon}")


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class District:
    district_id: str
    population: int
    risk_weight: float
    ej_flag: bool | None  # None == unknown (never false-by-default)
    centroid_lat: float
    centroid_lon: float
    # GeoJSON-like geometry dict; optional for non-spatial fixtures.
    geometry: dict | None = None

    def validate(self) -> District:
        if not self.district_id:
            raise DataValidationError("district_id must be a non-empty string")
        require_finite(self.population, f"{self.district_id}.population")
        if int(self.population) != self.population:
            raise DataValidationError(f"{self.district_id}.population must be integer")
        if self.population <= 0:
            raise DataValidationError(f"{self.district_id}.population must be > 0")
        require_nonneg(self.risk_weight, f"{self.district_id}.risk_weight")
        _require_latlon(self.centroid_lat, self.centroid_lon, self.district_id)
        if self.ej_flag not in (True, False, None):
            raise DataValidationError(f"{self.district_id}.ej_flag must be bool|None")
        return self


@dataclass(frozen=True)
class Hospital:
    hospital_id: str
    name: str
    lat: float
    lon: float
    staffed_beds: int  # C
    icu_beds: int
    baseline_occupancy: float  # baseline occupied BED COUNT

    def validate(self) -> Hospital:
        if not self.hospital_id:
            raise DataValidationError("hospital_id must be a non-empty string")
        _require_latlon(self.lat, self.lon, self.hospital_id)
        require_finite(self.staffed_beds, f"{self.hospital_id}.staffed_beds")
        if int(self.staffed_beds) != self.staffed_beds:
            raise DataValidationError(f"{self.hospital_id}.staffed_beds must be integer")
        if self.staffed_beds <= 0:
            raise DataValidationError(f"{self.hospital_id}.staffed_beds must be > 0")
        require_nonneg(self.icu_beds, f"{self.hospital_id}.icu_beds")
        require_nonneg(self.baseline_occupancy, f"{self.hospital_id}.baseline_occupancy")
        if self.baseline_occupancy > self.staffed_beds + 1e-9:
            raise DataValidationError(
                f"{self.hospital_id}.baseline_occupancy "
                f"({self.baseline_occupancy}) exceeds staffed_beds ({self.staffed_beds})"
            )
        return self


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DiseaseConfig:
    r0: float = 2.5
    latent_days: float = 5.0
    infectious_days: float = 7.0
    p_h: float = 0.03
    los_days: float = 7.0
    initial_infectious_fraction: float = 0.001
    seir_mode: Literal["A", "B"] = "A"

    def validate(self) -> DiseaseConfig:
        require_finite(self.r0, "disease.r0")
        if self.r0 <= 0:
            raise DataValidationError("disease.r0 must be > 0")
        for name in ("latent_days", "infectious_days", "los_days"):
            v = getattr(self, name)
            require_finite(v, f"disease.{name}")
            if v <= 0:
                raise DataValidationError(f"disease.{name} must be > 0")
        require_prob(self.p_h, "disease.p_h")
        require_prob(self.initial_infectious_fraction, "disease.initial_infectious_fraction")
        if self.seir_mode not in ("A", "B"):
            raise DataValidationError("disease.seir_mode must be 'A' or 'B'")
        if self.seir_mode == "B":
            raise DataValidationError("Option B (metapopulation) is deferred; not in MVP")
        return self

    @property
    def los_weeks(self) -> int:
        """Derived ONLY from los_days (no second source). ceil(los_days/7)."""
        return max(1, math.ceil(self.los_days / 7.0))


@dataclass(frozen=True)
class NetworkConfig:
    d0_km: float = 3.0
    k_nearest: int = 5
    radius_km: float = 10.0
    hospital_link_radius_km: float = 5.0
    alpha_d: float = 0.9
    alpha_h: float = 0.1
    beta_h: float = 100.0
    distance_shape: Literal["exponential", "inverse_square"] = "exponential"

    def validate(self) -> NetworkConfig:
        for name in ("d0_km", "radius_km", "hospital_link_radius_km"):
            v = getattr(self, name)
            require_finite(v, f"network.{name}")
            if v <= 0:
                raise DataValidationError(f"network.{name} must be > 0")
        if not isinstance(self.k_nearest, int) or isinstance(self.k_nearest, bool):
            raise DataValidationError("network.k_nearest must be an int")
        if self.k_nearest < 1:
            raise DataValidationError("network.k_nearest must be >= 1")
        require_prob(self.alpha_d, "network.alpha_d")
        require_prob(self.alpha_h, "network.alpha_h")
        require_score(self.beta_h, "network.beta_h")
        if self.distance_shape not in ("exponential", "inverse_square"):
            raise DataValidationError("network.distance_shape invalid")
        return self


@dataclass(frozen=True)
class Tolerances:
    mass_tol: float = 1e-6
    share_tol: float = 1e-9
    patient_tol: float = 1e-6
    move_epsilon: float = 1e-9


@dataclass(frozen=True)
class FDNASettings:
    convergence_tol_points: float = 0.1
    max_iterations: int = 500


@dataclass(frozen=True)
class RunConfig:
    disease: DiseaseConfig = field(default_factory=DiseaseConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    geography_unit: str = "census_tract"
    geography_region: str = "Suffolk County, MA"
    weeks: int = 8
    random_seed: int = 1234
    baseline_stock_policy: Literal["fixed_count", "fraction_of_C"] = "fixed_count"
    baseline_fraction: float = 0.75
    score_threshold: float = 70.0
    # Explicit, disclosed policy: when a populated district has no hospital within
    # radius_km, assign its single nearest hospital (share 1.0) instead of failing.
    # Off by default; the real Suffolk dataset enables it for one NE peninsula tract.
    nearest_outside_radius_fallback: bool = False
    tolerances: Tolerances = field(default_factory=Tolerances)
    fdna: FDNASettings = field(default_factory=FDNASettings)

    def validate(self) -> RunConfig:
        self.disease.validate()
        self.network.validate()
        if not isinstance(self.weeks, int) or isinstance(self.weeks, bool):
            raise DataValidationError("weeks must be an int")
        if self.weeks < 1:
            raise DataValidationError("weeks must be >= 1")
        if not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool):
            raise DataValidationError("random_seed must be an int")
        require_prob(self.baseline_fraction, "baseline_fraction")
        require_score(self.score_threshold, "score_threshold")
        if self.baseline_stock_policy not in ("fixed_count", "fraction_of_C"):
            raise DataValidationError("baseline_stock_policy invalid")
        if not isinstance(self.nearest_outside_radius_fallback, bool):
            raise DataValidationError("nearest_outside_radius_fallback must be bool")
        for name in ("mass_tol", "share_tol", "patient_tol", "move_epsilon"):
            v = getattr(self.tolerances, name)
            require_finite(v, f"tolerances.{name}")
            if v <= 0:
                raise DataValidationError(f"tolerances.{name} must be > 0")
        require_finite(self.fdna.convergence_tol_points, "fdna.convergence_tol_points")
        if self.fdna.convergence_tol_points <= 0:
            raise DataValidationError("fdna.convergence_tol_points must be > 0")
        if (
            not isinstance(self.fdna.max_iterations, int)
            or isinstance(self.fdna.max_iterations, bool)
            or self.fdna.max_iterations < 1
        ):
            raise DataValidationError("fdna.max_iterations must be a positive int")
        return self


# --------------------------------------------------------------------------- #
# Injections (discriminated union by kind)
# --------------------------------------------------------------------------- #

InjectionKind = Literal[
    "close_hospital",
    "set_capacity",
    "set_score",
    "reduce_score",
    "add_edge",
    "remove_edge",
    "set_edge",
    "set_share",
]


@dataclass(frozen=True)
class Injection:
    injection_id: str
    kind: InjectionKind
    start_week: int
    payload: dict
    end_week: int | None = None  # exclusive; None == open-ended
    note: str = ""

    def validate(self) -> Injection:
        if not isinstance(self.injection_id, str) or not self.injection_id:
            raise InvalidInjection("injection_id must be a non-empty string")
        if not isinstance(self.start_week, int) or isinstance(self.start_week, bool):
            raise InvalidInjection(
                f"{self.injection_id}: start_week must be an int, got {self.start_week!r}"
            )
        if self.start_week < 0:
            raise InvalidInjection(f"{self.injection_id}: start_week must be >= 0")
        if self.end_week is not None:
            if not isinstance(self.end_week, int) or isinstance(self.end_week, bool):
                raise InvalidInjection(
                    f"{self.injection_id}: end_week must be an int or None, got {self.end_week!r}"
                )
            if self.end_week <= self.start_week:
                raise InvalidInjection(
                    f"{self.injection_id}: end_week must be > start_week (exclusive)"
                )
        p = self.payload
        k = self.kind
        if k == "close_hospital":
            _require_keys(self, {"hospital_id"})
        elif k == "set_capacity":
            _require_keys(self, {"hospital_id", "factor"})
            require_nonneg(p["factor"], f"{self.injection_id}.factor")
        elif k == "set_score":
            _require_keys(self, {"hospital_id", "value"})
            require_score(p["value"], f"{self.injection_id}.value")
        elif k == "reduce_score":
            _require_keys(self, {"hospital_id", "points"})
            require_score(p["points"], f"{self.injection_id}.points")
        elif k in ("add_edge", "set_edge"):
            _require_keys(self, {"hospital_a", "hospital_b", "alpha", "beta"})
            require_prob(p["alpha"], f"{self.injection_id}.alpha")
            require_score(p["beta"], f"{self.injection_id}.beta")
        elif k == "remove_edge":
            _require_keys(self, {"hospital_a", "hospital_b"})
        elif k == "set_share":
            _require_keys(self, {"district_id", "hospital_id", "share"})
            require_prob(p["share"], f"{self.injection_id}.share")
        else:
            raise InvalidInjection(f"{self.injection_id}: unknown kind {k!r}")
        return self

    def active_at(self, week: int) -> bool:
        """start inclusive; end exclusive; end_week None => open-ended."""
        return self.start_week <= week and (self.end_week is None or week < self.end_week)


def _require_keys(inj: Injection, keys: set[str]) -> None:
    missing = keys - set(inj.payload)
    if missing:
        raise InvalidInjection(
            f"{inj.injection_id} ({inj.kind}): payload missing {sorted(missing)}"
        )


# --------------------------------------------------------------------------- #
# Record-array serialization for tuple-keyed maps
# --------------------------------------------------------------------------- #


def pair_map_to_records(
    m: dict[tuple[str, str], float],
    key_a: str = "district_id",
    key_b: str = "hospital_id",
) -> list[dict]:
    """Serialize a tuple-keyed map as a sorted array of explicit records."""
    out = []
    for a, b in sorted(m):
        out.append({key_a: a, key_b: b, "value": require_finite(m[(a, b)], f"{a},{b}")})
    return out


def single_map_to_records(m: dict[str, float], key: str = "id") -> list[dict]:
    return [{key: k, "value": require_finite(m[k], k)} for k in sorted(m)]
