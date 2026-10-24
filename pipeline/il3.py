"""IL3: package immutable weekly results and compute the next SEIR state.

Rerouting/injections never change the SEIR state (no feedback). The next state
is a deep, isolated copy of the SEIR end state.
"""

from __future__ import annotations

from .seir import carry_state
from .types import (
    SEIRState,
    SEIRWeekOutput,
    WeekResult,
    WeekSnapshot,
    freeze,
)


def inherited_deficit(baseline, retained, effective_capacity, hospital_ids) -> dict:
    return {
        h: max(
            0.0,
            baseline.get(h, 0.0) + retained.get(h, 0.0) - effective_capacity.get(h, 0.0),
        )
        for h in hospital_ids
    }


def package_results(
    epi: SEIRWeekOutput,
    before: WeekSnapshot,
    after: WeekSnapshot,
    end_hospital_state,
    active_injections,
    deficit: dict,
    diagnostics: dict,
) -> WeekResult:
    # Freeze all mapping fields so returned history cannot be mutated in place.
    return WeekResult(
        week=epi.week,
        state=epi.state_end,  # SEIRState freezes its own maps
        before=before,
        after=after,
        end_hospital_state=end_hospital_state,
        h_need=freeze(dict(epi.h_need)),
        new_infections=freeze(dict(epi.new_infections)),
        active_injections=tuple(active_injections),
        inherited_deficit=freeze(dict(deficit)),
        diagnostics=freeze(dict(diagnostics)),
    )


def next_state(epi: SEIRWeekOutput) -> SEIRState:
    """Carry SEIR compartments forward; unchanged by reroute/injection."""
    return carry_state(epi.state_end)
