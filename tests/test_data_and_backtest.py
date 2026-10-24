"""Real-data loader and backtest tests (use committed data/raw files)."""

from __future__ import annotations

import pytest

from pipeline import api
from pipeline.contracts import RunConfig
from pipeline.data_real import _load_hhs_observed, _load_tracts, real_available
from validation.backtest import (
    HOLDOUT_WEEKS,
    _observed_by_ccn_week,
    run_backtest,
)

pytestmark = pytest.mark.skipif(not real_available(), reason="real data not present")


def test_tracts_exclude_zero_pop_no_invented_population():
    districts, meta = _load_tracts()
    assert meta["n_tracts_modeled"] == len(districts)
    assert len(meta["zero_pop_excluded"]) == 4  # known: 4 zero-pop tracts
    for d in districts:
        assert d.population > 0  # never invented


def test_hhs_no_duplicate_keys_and_masks_suppressed():
    obs = _load_hhs_observed()
    assert obs["status"] == "available"
    keys = {(r["ccn"], r["week"]) for r in obs["rows"]}
    assert len(keys) == len(obs["rows"])  # unique
    assert any(r["suppressed"] for r in obs["rows"])  # some suppressed exist


def test_real_mode_builds_with_fallback_disclosed():
    inp = api.load_inputs("real", RunConfig(weeks=2, nearest_outside_radius_fallback=True))
    assert len(inp.districts) == 230
    assert len(inp.hospitals) == 9
    assert inp.manifest["nearest_fallback_districts"] == ["25025170502"]


def test_real_mode_rejects_uncovered_tract_without_fallback():
    # With the fallback policy OFF, the one NE-Suffolk peninsula tract has no
    # catchment and the build must raise an actionable error (no silent drop).
    from pipeline.contracts import DataValidationError

    with pytest.raises(DataValidationError):
        api.load_inputs("real", RunConfig(weeks=2, nearest_outside_radius_fallback=False))


def test_backtest_split_before_masking_and_identical_keys():
    obs = _load_hhs_observed()
    valid, cal, _excl = _observed_by_ccn_week(obs)
    assert len(cal) == 35  # full calendar preserved, not compressed
    # persistence-only run (no model) => status incomplete but pairs computed
    res = run_backtest(obs, None)
    assert res.calendar_weeks == 35
    assert res.train_weeks == 35 - HOLDOUT_WEEKS
    assert res.holdout_weeks == HOLDOUT_WEEKS
    assert res.persistence_mae_beds is not None
    assert res.status == "incomplete"  # no model series supplied


def test_backtest_unavailable_when_no_observed():
    res = run_backtest({"status": "unavailable", "rows": []}, None)
    assert res.status == "unavailable"
