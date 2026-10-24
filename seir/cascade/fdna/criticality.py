"""Knock out each node in turn and rank nodes by the citywide loss it causes."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Iterable

import pandas as pd


def criticality(run: Callable[[dict[str, float]], float], nodes: Iterable[str],
                level: float = 0.0, workers: int = 1) -> pd.DataFrame:
    """run(overrides) -> scalar loss. Must be a top-level function if workers > 1."""
    nodes = list(nodes)
    baseline = run({})
    jobs = [{n: level} for n in nodes]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            losses = list(ex.map(run, jobs))
    else:
        losses = [run(j) for j in jobs]
    df = pd.DataFrame({"node": nodes, "loss": losses})
    df["extra_loss"] = df["loss"] - baseline
    return df.sort_values("extra_loss", ascending=False, ignore_index=True)
