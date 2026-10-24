"""Shared helpers for the test suite (the guide's own tests live in test_guide.py)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cascade.epi import ScenarioConfig

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SCENARIOS = ROOT / "scenarios"


def make_config(patches=("A",), ages=("all",), counts=None, r0=2.5, latent=3.0, infectious=5.0,
                days=60, seeds=None, **disease) -> ScenarioConfig:
    """A small scenario built in code: one patch and one age group unless told otherwise."""
    counts = counts or [[100_000.0] * len(ages) for _ in patches]
    return ScenarioConfig.model_validate({
        "disease": {"r0": r0, "latent_period": latent, "infectious_period": infectious,
                    "p_hosp": 0.05, "p_icu": 0.2, "p_death_icu": 0.3, **disease},
        "population": {"patches": list(patches), "ages": list(ages), "counts": counts},
        "seeding": {"exposed": seeds or {patches[0]: 20}},
        "sim": {"start": date(2022, 1, 2), "days": days},
    })


@pytest.fixture
def example() -> ScenarioConfig:
    """The guide's three-neighbourhood example scenario."""
    return ScenarioConfig.from_yaml(SCENARIOS / "example_3patch.yaml")
