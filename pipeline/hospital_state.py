"""Persistent HospitalState transitions: scheduled discharge (before demand) and
commit (AFTER phase only). Occupants survive closure; cohorts are never deleted
here. All state is immutable (frozen Cohort/HospitalState); transitions build new
instances rather than mutating.
"""

from __future__ import annotations

from .contracts import DataValidationError
from .types import (
    Cohort,
    HospitalStateMap,
)


def discharge_due(state: HospitalStateMap, week: int) -> tuple[HospitalStateMap, dict, dict]:
    """Decrement remaining_los; remove cohorts hitting 0. Returns a NEW state map,
    discharged counts, and retained (survivors measured BEFORE commit)."""
    out: HospitalStateMap = {}
    discharged: dict[str, float] = {}
    retained: dict[str, float] = {}
    for h, st in state.items():
        d = 0.0
        survivors = []
        for c in st.cohorts:
            nc = Cohort(c.origin_district_id, c.admit_week, c.remaining_los - 1, c.count)
            if nc.remaining_los <= 0:
                d += c.count
            else:
                survivors.append(nc)
        out[h] = st.with_cohorts(survivors)
        discharged[h] = d
        retained[h] = out[h].retained()
    return out, discharged, retained


def commit_week(state: HospitalStateMap, alloc, week: int, los_weeks: int) -> HospitalStateMap:
    """AFTER phase only: append accepted cohorts (origin preserved). Counts
    accepted exactly once. Returns a NEW state map (immutable states)."""
    if getattr(alloc, "phase", None) != "after":
        raise DataValidationError(
            f"commit_week requires the AFTER allocation phase, got "
            f"{getattr(alloc, 'phase', None)!r}; only AFTER commits (contract)."
        )
    out: HospitalStateMap = {h: st.deep_copy() for h, st in state.items()}
    # group accepted new admissions by hospital
    additions: dict[str, list] = {h: [] for h in out}
    for (district, hospital), amount in alloc.accepted.items():
        if amount <= 0:
            continue
        if hospital not in out:
            raise DataValidationError(f"commit_week: accepted at unknown hospital {hospital}")
        additions[hospital].append(
            Cohort(
                origin_district_id=district, admit_week=week, remaining_los=los_weeks, count=amount
            )
        )
    for h, new_cohorts in additions.items():
        if new_cohorts:
            out[h] = out[h].with_cohorts(list(out[h].cohorts) + new_cohorts)
    return out
