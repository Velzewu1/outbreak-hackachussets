"""Rate providers, the default rate set and the standard feedback channels."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from cascade.epi import (FEEDBACK, Clip, Constant, Elastic, Piecewise, Product, RateSet, Seasonal, Signal,
                         TimeSeries, default_rates, with_feedback)
from conftest import make_config


def test_constant_keeps_scalars_and_arrays():
    assert Constant(2)(5, {}) == 2.0 and isinstance(Constant(2)(0, {}), float)
    assert np.array_equal(Constant([1, 2])(0, {}), [1.0, 2.0])


def test_time_series_interpolates_and_holds_its_ends():
    ts = TimeSeries([1.0, 3.0, 5.0], start_day=10)
    assert ts(10.5, {}) == pytest.approx(2.0)
    assert ts(0, {}) == 1.0 and ts(99, {}) == 5.0
    aligned = TimeSeries.from_dates([date(2022, 1, 3), date(2022, 1, 4)], [0.5, 0.7], start=date(2022, 1, 1))
    assert aligned(2, {}) == 0.5 and aligned(3, {}) == 0.7
    with pytest.raises(ValueError):
        TimeSeries([])


def test_piecewise_steps():
    p = Piecewise({20: 0.4, 50: 0.8}, before=1.0)
    assert [p(t, {}) for t in (0, 19.9, 20, 49, 50, 100)] == [1.0, 1.0, 0.4, 0.4, 0.8, 0.8]
    with pytest.raises(ValueError):
        Piecewise({})


def test_seasonal_and_elastic():
    s = Seasonal(0.2, peak_day=10)
    assert s(10, {}) == pytest.approx(1.2) and s(10 + 365.25 / 2, {}) == pytest.approx(0.8)
    with pytest.raises(ValueError):
        Seasonal(1.0, 0)
    e = Elastic(Constant(0.6), elasticity=0.5)
    assert e(0, {}) == pytest.approx(0.8)


def test_signal_defaults_reshapes_and_transforms():
    sig = Signal("strain", default=1.0, per_patch=True)
    assert sig(0, {}) == 1.0
    assert sig(0, {"strain": 2}) == 2.0
    assert sig(0, {"strain": np.array([1.0, 2.0])}).shape == (2, 1)       # broadcasts over ages
    t = Signal("x", transform=lambda v: v * 10)
    assert t(0, {"x": 0.5}) == 5.0


def test_product_and_clip():
    p = Product(Constant(0.5), Signal("m"))
    assert p(0, {"m": 3.0}) == 1.5
    c = Clip(p, 0.0, 1.0)
    assert c(0, {"m": 3.0}) == 1.0 and c(0, {}) == 0.5
    arr = Clip(Constant([0.5, 2.0]), 0, 1)(0, {})
    assert np.array_equal(arr, [0.5, 1.0])


def test_rate_set_evaluates_and_replaces():
    rs = RateSet(a=Constant(1), b=Constant(2))
    assert rs.names == ("a", "b") and rs.evaluate(0, {}) == {"a": 1.0, "b": 2.0}
    rs2 = rs.replace(b=Constant(5), c=Constant(7))
    assert rs2.evaluate(0, {}) == {"a": 1.0, "b": 5.0, "c": 7.0} and rs.evaluate(0, {})["b"] == 2.0


def test_default_rates_follow_the_disease():
    cfg = make_config(ages=("young", "old"), counts=[[50_000, 50_000]], p_hosp=[0.2, 0.6], hosp_scale=2.0)
    r = default_rates(cfg.disease, 2, beta0=0.3, contact_modifier=Constant(0.5)).evaluate(0, {})
    assert r["beta"] == pytest.approx(0.15)
    assert r["sigma"] == pytest.approx(1 / 3) and r["gamma"] == pytest.approx(1 / 5)
    assert np.allclose(r["p_hosp"], [0.4, 1.0])                 # scaled, capped at 1
    assert r["ward_exit"] == pytest.approx(1 / cfg.disease.los_ward)
    assert r["icu_exit"] == pytest.approx(1 / cfg.disease.los_icu)


def test_with_feedback_scales_only_with_a_signal_and_clips():
    cfg = make_config()
    rates = with_feedback(default_rates(cfg.disease, 1, 0.3), ["icu_mortality_multiplier", "contact_multiplier"])
    plain = rates.evaluate(0, {})
    assert plain["p_death_icu"] == pytest.approx(0.3) and plain["beta"] == pytest.approx(0.3)
    pushed = rates.evaluate(0, {"icu_mortality_multiplier": np.array([2.0, 5.0]), "contact_multiplier": 0.5})
    assert np.allclose(pushed["p_death_icu"].ravel(), [0.6, 1.0])     # per patch, capped at 1
    assert pushed["beta"] == pytest.approx(0.15)
    with pytest.raises(ValueError, match="unknown feedback signal"):
        with_feedback(rates, ["staff_shortage"])
    assert set(FEEDBACK.values()) <= {"p_death_icu", "p_hosp", "beta"}
