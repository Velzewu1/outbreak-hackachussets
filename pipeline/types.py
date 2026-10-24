"""Per-week pipeline flow types and persistent HospitalState.

These mirror ``contracts/pipeline-types.md`` and
``contracts/stage-io-and-signatures.md``. Arrays are keyed by stable sorted IDs.
``NaN``/``Infinity`` rejected via ``contracts.require_*``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .contracts import DataValidationError, require_nonneg

Phase = Literal["before", "after"]


class FrozenDict(dict):
    """Immutable, picklable, JSON-serializable dict for result snapshots.

    Blocks in-place mutation (__setitem__, update, etc.) so returned history
    cannot be corrupted. Still a ``dict`` subclass so json.dumps and pandas work.
    """

    __slots__ = ()

    def _ro(self, *a, **k):  # pragma: no cover - trivial
        raise TypeError("FrozenDict is immutable")

    __setitem__ = _ro
    __delitem__ = _ro
    clear = _ro
    pop = _ro
    popitem = _ro
    setdefault = _ro
    update = _ro
    __ior__ = _ro  # block |=

    def __reduce__(self):
        return (FrozenDict, (dict(self),))


def freeze(obj):
    """Recursively wrap dicts in FrozenDict and lists/tuples in tuples."""
    if isinstance(obj, dict):
        return FrozenDict({k: freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(freeze(v) for v in obj)
    return obj


# --------------------------------------------------------------------------- #
# SEIR
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SEIRState:
    """``week`` is a BOUNDARY index. S+E+I+R = N per district."""

    week: int
    district_ids: tuple[str, ...]
    S: dict[str, float]
    E: dict[str, float]
    I: dict[str, float]
    R: dict[str, float]
    N: dict[str, float]

    def __post_init__(self):
        for f in ("S", "E", "I", "R", "N"):
            object.__setattr__(self, f, FrozenDict(getattr(self, f)))

    def validate(self, mass_tol: float = 1e-6) -> SEIRState:
        for j in self.district_ids:
            for comp, name in (
                (self.S, "S"),
                (self.E, "E"),
                (self.I, "I"),
                (self.R, "R"),
            ):
                require_nonneg(comp[j], f"{name}[{j}]")
            total = self.S[j] + self.E[j] + self.I[j] + self.R[j]
            if abs(total - self.N[j]) > mass_tol * max(1.0, self.N[j]):
                raise DataValidationError(
                    f"SEIR mass conservation failed for {j}: S+E+I+R={total} vs N={self.N[j]}"
                )
        return self


@dataclass(frozen=True)
class SEIRWeekOutput:
    """``week`` is an INTERVAL index. Weekly quantities are integrated PEOPLE."""

    week: int
    state_end: SEIRState
    i_exit: dict[str, float]  # people leaving I during the week
    e_to_i: dict[str, float]  # people E->I during the week
    new_infections: dict[str, float]  # people S->E during the week
    h_need: dict[str, float]  # new-admission need (people/week), NOT beds


# --------------------------------------------------------------------------- #
# Accessibility
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Accessibility:
    district_ids: tuple[str, ...]
    hospital_ids: tuple[str, ...]
    distance_km: dict[tuple[str, str], float]
    eligible: dict[tuple[str, str], bool]
    a: dict[tuple[str, str], float]
    shares: dict[tuple[str, str], float]  # s_ji; sum over i == 1 per district
    total_accessibility: dict[str, float]  # A_j (index)
    # Districts that used the documented nearest-outside-radius fallback (disclosed).
    fallback_districts: tuple[str, ...] = ()

    def eligible_hospitals(self, district_id: str) -> list[str]:
        return [
            h
            for h in self.hospital_ids
            if self.eligible.get((district_id, h), False)
            and self.shares.get((district_id, h), 0.0) > 0.0
        ]


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


@dataclass
class RequestRow:
    district_id: str
    hospital_id: str  # intended (source) hospital
    requested: float
    direct_accepted: float = 0.0
    rerouted_out: float = 0.0
    residual: float = 0.0

    def check(self, tol: float = 1e-6) -> None:
        lhs = self.direct_accepted + self.rerouted_out + self.residual
        if abs(lhs - self.requested) > tol:
            raise DataValidationError(
                f"request-row conservation failed {self.district_id}->{self.hospital_id}: "
                f"{lhs} != requested {self.requested}"
            )


@dataclass
class RequestTable:
    rows: dict[tuple[str, str], RequestRow] = field(default_factory=dict)

    def request_i(self, hospital_id: str) -> float:
        return sum(r.requested for (d, h), r in self.rows.items() if h == hospital_id)


# --------------------------------------------------------------------------- #
# Hospital load (requested-load / need view)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HospitalLoad:
    hospital_id: str
    baseline: float
    retained: float
    request_i: float  # before: full requested; after: post_request_i
    requested_load: float
    effective_capacity: float  # Ceff
    own_score: float
    excess: float
    closed: bool


# --------------------------------------------------------------------------- #
# Persistent HospitalState  (per hospital; HospitalStateMap = dict[id -> ...])
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cohort:
    origin_district_id: str
    admit_week: int  # -1 allowed for pre-simulation seeded cohorts
    remaining_los: int
    count: float


@dataclass(frozen=True)
class HospitalState:
    """Immutable per-hospital state; cohorts is a tuple of frozen Cohorts.

    The engine never mutates a HospitalState in place (discharge_due / commit_week
    build new instances), so result history is non-mutable.
    """

    hospital_id: str
    baseline: float
    cohorts: tuple = ()

    def retained(self) -> float:
        return sum(c.count for c in self.cohorts)

    def deep_copy(self) -> HospitalState:
        # Cohorts are frozen; a tuple copy is already a deep copy.
        return HospitalState(self.hospital_id, self.baseline, tuple(self.cohorts))

    def with_cohorts(self, cohorts) -> HospitalState:
        return HospitalState(self.hospital_id, self.baseline, tuple(cohorts))


HospitalStateMap = dict[str, HospitalState]


def deep_copy_state_map(sm: HospitalStateMap) -> HospitalStateMap:
    return {h: st.deep_copy() for h, st in sm.items()}


def freeze_state_map(sm: HospitalStateMap) -> FrozenDict:
    """Immutable mapping of immutable HospitalStates for result history."""
    return FrozenDict({h: st.deep_copy() for h, st in sm.items()})


# --------------------------------------------------------------------------- #
# FDNA
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Edge:
    feeder: str
    receiver: str
    kind: Literal["hospital_hospital", "hospital_district"]
    alpha: float
    beta: float


@dataclass(frozen=True)
class FDNAGraph:
    hospital_nodes: tuple[str, ...]
    district_nodes: tuple[str, ...]
    edges: tuple[Edge, ...]  # dependency edges ONLY


@dataclass(frozen=True)
class FDNAResult:
    hospital_scores: dict[str, float]
    district_scores: dict[str, float]
    iterations: int
    converged: bool
    max_delta: float

    def __post_init__(self):
        object.__setattr__(self, "hospital_scores", FrozenDict(self.hospital_scores))
        object.__setattr__(self, "district_scores", FrozenDict(self.district_scores))


# --------------------------------------------------------------------------- #
# Rerouting / allocation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RerouteRecord:
    week: int  # INTERVAL index (display "Week 1" == 0)
    district: str
    source_hospital: str
    destination: str
    amount: float


@dataclass
class AllocationSnapshot:
    phase: Phase
    accepted: dict[tuple[str, str], float]  # (district, hospital_landed) -> people
    residual_rows: dict[tuple[str, str], float]  # (district, source) -> residual
    unmet_by_district: dict[str, float]
    projected_occupancy: dict[str, float]  # baseline + retained + accepted at h
    reroute_volume: float
    reroutes: list[RerouteRecord] = field(default_factory=list)

    def accepted_i(self, hospital_id: str) -> float:
        return sum(v for (d, h), v in self.accepted.items() if h == hospital_id)

    def residual_intended_for(self, hospital_id: str) -> float:
        return sum(v for (d, s), v in self.residual_rows.items() if s == hospital_id)

    def frozen(self) -> FrozenAllocation:
        """Deep-frozen, immutable snapshot for results history."""
        return FrozenAllocation(
            phase=self.phase,
            accepted=FrozenDict(dict(self.accepted)),
            residual_rows=FrozenDict(dict(self.residual_rows)),
            unmet_by_district=FrozenDict(dict(self.unmet_by_district)),
            projected_occupancy=FrozenDict(dict(self.projected_occupancy)),
            reroute_volume=self.reroute_volume,
            reroutes=tuple(self.reroutes),
        )


@dataclass(frozen=True)
class FrozenAllocation:
    """Immutable allocation snapshot stored in results. Attribute assignment and
    nested dict/list mutation both raise."""

    phase: Phase
    accepted: dict
    residual_rows: dict
    unmet_by_district: dict
    projected_occupancy: dict
    reroute_volume: float
    reroutes: tuple = ()

    def accepted_i(self, hospital_id: str) -> float:
        return sum(v for (d, h), v in self.accepted.items() if h == hospital_id)

    def residual_intended_for(self, hospital_id: str) -> float:
        return sum(v for (d, s), v in self.residual_rows.items() if s == hospital_id)


# --------------------------------------------------------------------------- #
# Week / run results
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class WeekSnapshot:
    phase: Phase
    hospital_loads: dict[str, HospitalLoad]
    fdna: FDNAResult
    allocation: AllocationSnapshot

    def __post_init__(self):
        object.__setattr__(self, "hospital_loads", FrozenDict(self.hospital_loads))


@dataclass(frozen=True)
class WeekResult:
    week: int
    state: SEIRState
    before: WeekSnapshot
    after: WeekSnapshot
    end_hospital_state: HospitalStateMap  # physical committed result (after AFTER)
    h_need: dict[str, float]
    new_infections: dict[str, float]
    active_injections: tuple
    inherited_deficit: dict[str, float]
    diagnostics: dict

    def __post_init__(self):
        # Freeze all remaining mutable containers so result history is immutable.
        object.__setattr__(self, "end_hospital_state", freeze_state_map(self.end_hospital_state))
        object.__setattr__(self, "h_need", freeze(self.h_need))
        object.__setattr__(self, "new_infections", freeze(self.new_infections))
        object.__setattr__(self, "inherited_deficit", freeze(self.inherited_deficit))
        object.__setattr__(self, "diagnostics", freeze(self.diagnostics))
        # active_injections: freeze each injection's payload (frozen Injection
        # wrappers so payload dict is immutable in history).
        object.__setattr__(
            self,
            "active_injections",
            tuple(_FrozenInjectionView(i) for i in self.active_injections),
        )


@dataclass(frozen=True)
class _FrozenInjectionView:
    """Immutable read-only view of an Injection for result history (payload frozen)."""

    injection_id: str
    kind: str
    start_week: int
    end_week: object
    note: str
    payload: dict

    def __init__(self, inj):
        object.__setattr__(self, "injection_id", inj.injection_id)
        object.__setattr__(self, "kind", inj.kind)
        object.__setattr__(self, "start_week", inj.start_week)
        object.__setattr__(self, "end_week", inj.end_week)
        object.__setattr__(self, "note", inj.note)
        object.__setattr__(self, "payload", freeze(dict(inj.payload)))


@dataclass(frozen=True)
class ValidationReport:
    status: Literal["verified", "unavailable", "incomplete"]
    target_variable: str | None = None
    source_url: str | None = None
    source_last_data_date: str | None = None
    training_start: str | None = None
    training_end: str | None = None
    test_start: str | None = None
    test_end: str | None = None
    matched_hospitals: int = 0
    forecast_pairs: int = 0
    fitted_r0: float | None = None
    fitted_p_h: float | None = None
    model_mae_beds: float | None = None
    persistence_mae_beds: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunResult:
    run_id: str
    data_mode: Literal["historical_data", "mixed_assumptions", "synthetic_demo"]
    config: object
    weeks: tuple[WeekResult, ...]
    validation: ValidationReport | None
    data_manifest: dict
    warnings: tuple[str, ...]
    # Full reproducibility provenance: initial SEIR state, seeded cohorts, and the
    # per-component content hashes that compose run_id.
    provenance: dict = field(default_factory=dict)
