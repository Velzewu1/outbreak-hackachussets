"""Randomized small-network conservation: for many random synthetic inputs and
random closure/capacity injections, all engine invariants hold."""

from __future__ import annotations

import random

from pipeline import api
from pipeline.contracts import DiseaseConfig, Injection, RunConfig
from pipeline.data import synthetic_spatial


def test_random_conservation():
    for trial in range(12):
        rng = random.Random(1000 + trial)
        bundle = synthetic_spatial(
            n_districts=rng.randint(4, 14),
            n_hospitals=rng.randint(2, 5),
            seed=trial,
        )
        cfg = RunConfig(
            disease=DiseaseConfig(
                r0=round(rng.uniform(1.5, 3.2), 2),
                initial_infectious_fraction=round(rng.uniform(0.001, 0.006), 4),
            ),
            weeks=rng.randint(3, 7),
        )
        inp = api.build_inputs(bundle, cfg)
        # maybe inject a random closure
        injections = []
        if rng.random() < 0.5:
            hid = rng.choice([h.hospital_id for h in bundle.hospitals])
            start = rng.randint(0, cfg.weeks - 1)
            injections.append(
                Injection(
                    "c",
                    "close_hospital",
                    start,
                    {"hospital_id": hid},
                    end_week=min(cfg.weeks, start + 2),
                )
            )
        run = api.run_scenario(inp, injections)
        for wk in run.weeks:
            d = wk.diagnostics
            assert d["mass"] is True, (trial, wk.week, "mass")
            assert d["patient_mass"] is True, (trial, wk.week, "patient")
            assert d["capacity_bound"] is True, (trial, wk.week, "capacity")
            assert d["fdna_convergence"] is True, (trial, wk.week, "fdna")
            # committed never negative; redirected subset of accepted
            for occ in wk.after.allocation.projected_occupancy.values():
                assert occ >= -1e-9
            vol = wk.after.allocation.reroute_volume
            total_accepted = sum(wk.after.allocation.accepted.values())
            assert vol <= total_accepted + 1e-6
