"""The writeup's pass bars, error scores and the backtest."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from cascade.epi import SEIREngine
from cascade.epi.calibrate import Param
from cascade.epi.validation import (backtest, peak_height_error, peak_offset, score, share_within,
                                    validate_ranking, validate_series)

WEEKS = pd.date_range("2022-01-01", periods=6, freq="7D")
OBS = pd.Series([100.0, 200.0, 400.0, 300.0, 150.0, 80.0], index=WEEKS)


def test_metrics_on_hand_made_series():
    model = pd.Series([140.0, 150.0, 300.0, 430.0, 140.0, 0.0], index=WEEKS)
    assert share_within(model, OBS) == pytest.approx(4 / 6)         # weeks 4 (+43%) and 6 (-100%) miss
    assert share_within(model.where(model != 430.0, 420.0), OBS) == pytest.approx(5 / 6)   # +40% counts
    assert peak_offset(model, OBS) == 1
    assert peak_height_error(model, OBS) == pytest.approx(0.075)
    s = score(model, OBS)
    assert s["n"] == 6 and s["bias"] == pytest.approx((40 - 50 - 100 + 130 - 10 - 80) / 6)
    assert s["share_within"] == pytest.approx(4 / 6)


def test_only_shared_dates_count():
    model = pd.Series([100.0, 200.0], index=WEEKS[:2])
    assert share_within(model, OBS) == 1.0
    with pytest.raises(ValueError, match="share no dates"):
        share_within(pd.Series([1.0], index=[pd.Timestamp("1999-01-01")]), OBS)


def test_validate_series_reports_each_bar():
    good = validate_series(OBS * 1.1, OBS, title="good")
    assert good.passed and [c.passed for c in good.checks] == [True, True, True]
    late = validate_series(OBS.shift(2).fillna(50.0), OBS)
    assert not late.passed and not late.checks[1].passed
    text = str(late)
    assert "FAIL  peak week offset" in text and "FAIL  overall" in text
    d = good.to_dict()
    json.dumps(d)
    assert d["passed"] and d["title"] == "good" and len(d["checks"]) == 3
    assert len(good.to_frame()) == 3


def test_validate_ranking():
    observed = {"MGH": 120, "BMC": 90, "BIDMC": 80, "Tufts": 40, "BWH": 100}
    same_order = {"MGH": 60, "BMC": 45, "BIDMC": 40, "Tufts": 20, "BWH": 50}
    r = validate_ranking(same_order, observed)
    assert r.passed and r.checks[0].value == pytest.approx(1.0) and r.checks[1].value == 3
    flipped = {k: -v for k, v in observed.items()}
    assert not validate_ranking(flipped, observed).passed


@pytest.fixture(scope="module")
def setting():
    from cascade.epi import ScenarioConfig
    from conftest import SCENARIOS

    cfg = ScenarioConfig.from_yaml(SCENARIOS / "example_3patch.yaml")
    res = SEIREngine.from_config(cfg).run(cfg.seeding, 120)
    return cfg, res.weekly("new_hosp")


def test_backtest_scores_only_the_unseen_weeks(setting):
    cfg, observed = setting
    split = observed.index[6]
    bt = backtest(cfg, observed, {"disease.r0": Param(2.0, 1.2, 5.0)}, split)
    assert (bt.train.index <= split).all() and (bt.test.index > split).all()
    assert len(bt.train) + len(bt.test) == len(observed)
    assert bt.fit.params["disease.r0"] == pytest.approx(cfg.disease.r0, rel=1e-3)   # truth is in the model
    assert bt.report.passed and bt.metrics["mape"] < 1e-2


def test_backtest_needs_both_sides(setting):
    cfg, observed = setting
    with pytest.raises(ValueError, match="both sides"):
        backtest(cfg, observed, {"disease.r0": Param(2.0, 1.2, 5.0)}, observed.index[-1])
