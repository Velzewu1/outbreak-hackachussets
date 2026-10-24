"""Offline smoke demo: runs the engine on synthetic and golden data with no
network. Prints a compact summary. Run: .venv/bin/python scripts/smoke_demo.py
"""

from __future__ import annotations

from pipeline import api


def main():
    for mode in ("golden", "synthetic"):
        cfg = api.RunConfig(
            disease=api.DiseaseConfig(r0=2.6, initial_infectious_fraction=0.003),
            weeks=6,
        )
        inp = api.load_inputs(mode, cfg)
        close = api.make_injection(
            "c",
            "close_hospital",
            2,
            {"hospital_id": api.list_hospitals(inp)[0]["hospital_id"]},
            end_week=6,
        )
        run = api.run_scenario(inp, [close])
        print(
            f"[{mode}] run_id={run.run_id} weeks={len(run.weeks)} "
            f"districts={len(inp.districts)} hospitals={len(inp.hospitals)}"
        )
        for w in api.list_weeks(run):
            v = api.get_week(run, w, "after")
            mx = v["metrics"]
            assert all(x in (True, None) for x in run.weeks[w].diagnostics.values())
            print(
                f"   wk{w}: overloaded={mx['overloaded_hospitals']} "
                f"unmet={mx['unmet_need_people']:.1f} rerouted={mx['rerouted_people']:.1f}"
            )
    print("SMOKE OK (offline, conservation diagnostics pass)")


if __name__ == "__main__":
    main()
