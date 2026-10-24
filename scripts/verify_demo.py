"""Verification: asserts the frozen golden walkthrough numbers and core
invariants through the PUBLIC API and the analysis layer. Exits non-zero on any
failure. Run: .venv/bin/python scripts/verify_demo.py
"""

from __future__ import annotations

import sys

from pipeline import analysis as an
from pipeline import api, il2

# Reuse the golden accessibility fixture from tests for exact-number checks.
sys.path.insert(0, "tests")
from golden import BASELINE, CEFF, golden_accessibility  # noqa: E402


def _scn():
    class S:
        week = 0
        effective_capacity = dict(CEFF)
        closed = set()
        score_caps = {}
        shares_override = {}
        effective_edges = []
        active_injections = ()

    return S()


def check_walkthrough():
    acc = golden_accessibility()
    h_need = {"D1": 40.0, "D2": 120.0, "D3": 48.0}
    scn = _scn()
    reqs = il2.compute_requests(h_need, acc, scn)
    retained = {"H1": 18.0, "H2": 8.0, "H3": 6.0}
    before = an.reserve_direct(reqs, BASELINE, retained, scn, acc, 1e-9)
    after = an.reroute(before, BASELINE, retained, scn, acc, 0, 1e-9)
    assert abs(sum(before.unmet_by_district.values()) - 87.206987775) < 1e-6
    assert abs(sum(after.unmet_by_district.values()) - 75.0) < 1e-6
    assert abs(after.reroute_volume - 12.206987775) < 1e-6
    assert len(after.reroutes) == 1
    r = after.reroutes[0]
    assert (r.district, r.source_hospital, r.destination, r.week) == ("D2", "H2", "H1", 0)
    print("walkthrough OK: before=87.206987775 after=75.0 redirect=12.206987775")


def check_pipeline():
    cfg = api.RunConfig(
        disease=api.DiseaseConfig(r0=2.6, initial_infectious_fraction=0.003), weeks=5
    )
    run = api.run_scenario(api.load_inputs("synthetic", cfg), [])
    # determinism
    run2 = api.run_scenario(api.load_inputs("synthetic", cfg), [])
    assert run.run_id == run2.run_id
    for w in api.list_weeks(run):
        d = run.weeks[w].diagnostics
        assert d["mass"] and d["patient_mass"] and d["capacity_bound"] and d["fdna_convergence"]
    print(f"pipeline OK: deterministic run_id={run.run_id}, all invariants pass")


def main():
    check_walkthrough()
    check_pipeline()
    print("VERIFY OK")


if __name__ == "__main__":
    main()
