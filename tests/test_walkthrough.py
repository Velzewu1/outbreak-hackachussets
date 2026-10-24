"""Reproduces the frozen two-week walkthrough numbers exactly.

Verifies: week-1 BEFORE total unmet 87.206987775, AFTER 75.0, redirected
12.206987775 (one record D2 H2->H1); per-district and source-row ledgers;
committed bound; week-2 retained blocks admissions and zero-move identity.
"""

from __future__ import annotations

from pipeline import analysis as an
from pipeline import il2

from .golden import BASELINE, CEFF, golden_accessibility

TOL = 1e-6
ACC = golden_accessibility()

# Frozen H_need for both weeks.
H_NEED = {"D1": 40.0, "D2": 120.0, "D3": 48.0}


class _Scn:
    """Minimal ScenarioInputs with no injections (full capacity)."""

    def __init__(self):
        self.week = 0
        self.effective_capacity = dict(CEFF)
        self.closed = set()
        self.score_caps = {}
        self.shares_override = {}
        self.effective_edges = []
        self.active_injections = ()


def _requests(h_need):
    scn = _Scn()
    return il2.compute_requests(h_need, ACC, scn), scn


def test_week1_before_after_totals():
    requests, scn = _requests(H_NEED)
    retained = {"H1": 18.0, "H2": 8.0, "H3": 6.0}  # after discharge of seeded LOS-1
    before = an.reserve_direct(requests, BASELINE, retained, scn, ACC, 1e-9)
    after = an.reroute(before, BASELINE, retained, scn, ACC, 0, 1e-9)

    assert abs(sum(before.unmet_by_district.values()) - 87.206987775) < 1e-6
    assert abs(sum(after.unmet_by_district.values()) - 75.0) < 1e-6
    assert before.reroute_volume == 0.0
    assert abs(after.reroute_volume - 12.206987775) < 1e-6
    assert len(after.reroutes) == 1
    r = after.reroutes[0]
    assert (r.district, r.source_hospital, r.destination) == ("D2", "H2", "H1")
    assert r.week == 0
    assert abs(r.amount - 12.206987775) < 1e-6

    # per-district conservation: accepted + unmet == H_need
    for j in H_NEED:
        acc_j = sum(v for (d, h), v in after.accepted.items() if d == j)
        assert abs(acc_j + after.unmet_by_district[j] - H_NEED[j]) < TOL

    # committed bound: <= max(Ceff, baseline+retained)
    for h in CEFF:
        committed = after.projected_occupancy[h]
        bound = max(CEFF[h], BASELINE[h] + retained[h])
        assert committed <= bound + TOL
    # H1 fills exactly to 150
    assert abs(after.projected_occupancy["H1"] - 150.0) < 1e-6


def test_week1_d2_residual_row():
    requests, scn = _requests(H_NEED)
    retained = {"H1": 18.0, "H2": 8.0, "H3": 6.0}
    before = an.reserve_direct(requests, BASELINE, retained, scn, ACC, 1e-9)
    # D2's residual sits entirely on its intended primary row D2->H2 ~ 56.79
    assert abs(before.residual_rows[("D2", "H2")] - 56.790623715) < 1e-6
    after = an.reroute(before, BASELINE, retained, scn, ACC, 0, 1e-9)
    # after reroute that row drops to ~44.58 (12.207 moved out to H1)
    assert abs(after.residual_rows[("D2", "H2")] - 44.583635940) < 1e-6


def test_week2_retained_blocks_and_zero_move():
    # Week 2: retained = week-1 accepted (LOS 2). Reconstruct retained from the
    # week-1 AFTER accepted-at-destination totals.
    requests1, scn1 = _requests(H_NEED)
    ret1 = {"H1": 18.0, "H2": 8.0, "H3": 6.0}
    before1 = an.reserve_direct(requests1, BASELINE, ret1, scn1, ACC, 1e-9)
    after1 = an.reroute(before1, BASELINE, ret1, scn1, ACC, 0, 1e-9)
    # retained into week 2 (after week-2 discharge) == week-1 accepted (LOS 2):
    retained2 = {h: after1.accepted_i(h) for h in CEFF}  # H1 72, H2 27, H3 34
    assert abs(retained2["H1"] - 72.0) < 1e-6
    assert abs(retained2["H2"] - 27.0) < 1e-6
    assert abs(retained2["H3"] - 34.0) < 1e-6

    requests2, scn2 = _requests(H_NEED)
    before2 = an.reserve_direct(requests2, BASELINE, retained2, scn2, ACC, 1e-9)
    # free_new is small (18/8/6) so most new need cannot be accepted
    after2 = an.reroute(before2, BASELINE, retained2, scn2, ACC, 1, 1e-9)
    # every hospital's spare exhausted by direct reservation => no moves
    assert after2.reroute_volume == 0.0
    assert len(after2.reroutes) == 0
    # accepted = free_new sum (32) ; unmet = 208 - 32 = 176
    assert abs(sum(after2.unmet_by_district.values()) - 176.0) < 1e-6
    # zero-move => residual rows identical before and after
    assert before2.residual_rows == after2.residual_rows
