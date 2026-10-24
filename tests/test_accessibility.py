"""Accessibility tests: haversine, radius/k eligibility, share sums,
no-catchment rejection."""

from __future__ import annotations

import pytest

from pipeline.accessibility import build_accessibility, haversine_km
from pipeline.contracts import DataValidationError, District, Hospital, NetworkConfig


def test_haversine_zero_and_known():
    assert haversine_km(42.0, -71.0, 42.0, -71.0) == pytest.approx(0.0, abs=1e-9)
    # ~1 degree latitude ~= 111 km
    d = haversine_km(42.0, -71.0, 43.0, -71.0)
    assert 110.0 < d < 112.0


def test_shares_sum_to_one():
    districts = [District("D1", 1000, 1.0, None, 42.30, -71.08)]
    hospitals = [
        Hospital("H1", "h1", 42.30, -71.081, 100, 10, 60),
        Hospital("H2", "h2", 42.33, -71.10, 100, 10, 60),
        Hospital("H3", "h3", 42.31, -71.06, 100, 10, 60),
    ]
    acc = build_accessibility(districts, hospitals, NetworkConfig())
    s = sum(acc.shares[("D1", h.hospital_id)] for h in hospitals)
    assert abs(s - 1.0) < 1e-9


def test_two_equal_distance_half_shares():
    # Two hospitals symmetric about the district longitude at equal distance.
    districts = [District("D1", 1000, 1.0, None, 42.30, -71.08)]
    hospitals = [
        Hospital("H1", "h1", 42.30, -71.07, 100, 10, 60),
        Hospital("H2", "h2", 42.30, -71.09, 100, 10, 60),
    ]
    acc = build_accessibility(districts, hospitals, NetworkConfig())
    assert acc.shares[("D1", "H1")] == pytest.approx(0.5, abs=1e-6)
    assert acc.shares[("D1", "H2")] == pytest.approx(0.5, abs=1e-6)


def test_radius_excludes_far_hospital():
    districts = [District("D1", 1000, 1.0, None, 42.30, -71.08)]
    hospitals = [
        Hospital("H1", "h1", 42.30, -71.081, 100, 10, 60),
        Hospital("FAR", "far", 43.50, -71.08, 100, 10, 60),  # ~130 km away
    ]
    acc = build_accessibility(districts, hospitals, NetworkConfig(radius_km=10.0))
    assert acc.eligible[("D1", "H1")] is True
    assert acc.eligible[("D1", "FAR")] is False
    assert acc.shares[("D1", "FAR")] == 0.0
    assert acc.shares[("D1", "H1")] == pytest.approx(1.0, abs=1e-9)


def test_no_catchment_rejected():
    districts = [District("D1", 1000, 1.0, None, 10.0, 10.0)]  # far from Boston
    hospitals = [Hospital("H1", "h1", 42.30, -71.08, 100, 10, 60)]
    with pytest.raises(DataValidationError):
        build_accessibility(districts, hospitals, NetworkConfig(radius_km=10.0))
