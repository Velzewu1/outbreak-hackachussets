"""Mixing operator, spectral radius paths and the builders for C and W."""
from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse

from cascade.epi import MixingOperator, coupling_from_distance, coupling_from_flows, haversine_km
from cascade.epi.data import age_contacts_from_csv
from cascade.epi.mixing import aggregate_contacts, reciprocal_contacts
from conftest import DATA

RNG = np.random.default_rng(1)


def random_case(P=4, A=3, density=1.0):
    N = RNG.uniform(1_000, 50_000, (P, A))
    C = RNG.uniform(0.1, 5.0, (A, A))
    W = RNG.uniform(0, 1, (P, P)) * (RNG.uniform(0, 1, (P, P)) < density) + np.eye(P)
    return N, C, W / W.sum(axis=1, keepdims=True)


def test_one_patch_one_age_reduces_to_prevalence():
    m = MixingOperator(np.array([[1000.0]]), np.array([[1.0]]), np.eye(1))
    assert m.apply(np.array([[50.0]])).item() == pytest.approx(0.05)


def test_apply_matches_the_dense_matrix():
    N, C, W = random_case()
    m = MixingOperator(N, C, W)
    x = RNG.uniform(0, 100, N.shape)
    assert np.allclose(m.apply(x).ravel(), m.matrix() @ x.ravel())


def test_spectral_radius_exact_path_matches_numpy():
    N, C, W = random_case()
    m = MixingOperator(N, C, W)
    w = RNG.uniform(0.5, 2.0, N.shape)
    expected = np.abs(np.linalg.eigvals(w.ravel()[:, None] * m.matrix())).max()
    assert m.spectral_radius(w) == pytest.approx(expected, rel=1e-10)


def test_power_iteration_path_matches_numpy(monkeypatch):
    N, C, W = random_case(P=30, A=3, density=0.2)
    m = MixingOperator(N, C, W)
    monkeypatch.setattr(m, "DENSE_MAX", 0)                     # force the large-block path
    w = RNG.uniform(0.5, 2.0, N.shape)
    expected = np.abs(np.linalg.eigvals(w.ravel()[:, None] * m.matrix())).max()
    assert m.spectral_radius(w) == pytest.approx(expected, rel=1e-6)
    w2 = w * 1.1                                               # warm start from the last answer
    assert m.spectral_radius(w2) == pytest.approx(1.1 * expected, rel=1e-6)


def test_periodic_contacts_still_converge(monkeypatch):
    # Two groups that only meet each other: plain power iteration oscillates.
    N = np.full((40, 2), 1000.0)
    C = np.array([[0.0, 1.0], [1.0, 0.0]])
    m = MixingOperator(N, C, np.eye(40))
    monkeypatch.setattr(m, "DENSE_MAX", 0)
    w = np.tile([1000.0, 4000.0], (40, 1))
    assert m.spectral_radius(w) == pytest.approx(2.0, rel=1e-6)   # sqrt(1 * 4)


def test_disconnected_patches_take_the_largest_block(monkeypatch):
    N = np.full((3, 1), 1000.0)
    m = MixingOperator(N, np.ones((1, 1)), np.eye(3))
    w = np.array([[500.0], [2000.0], [1000.0]])
    assert len(m._blocks) == 3
    assert m.spectral_radius(w) == pytest.approx(2.0)


def test_sparse_coupling_gives_the_same_answers():
    N, C, W = random_case(P=12, density=0.3)
    dense, sp = MixingOperator(N, C, W), MixingOperator(N, C, sparse.csr_array(W))
    x = RNG.uniform(0, 100, N.shape)
    assert np.allclose(dense.apply(x), sp.apply(x))
    w = RNG.uniform(0.5, 2, N.shape)
    assert sp.spectral_radius(w) == pytest.approx(dense.spectral_radius(w), rel=1e-9)


def test_bad_inputs():
    N, C, W = random_case()
    with pytest.raises(ValueError, match="shapes"):
        MixingOperator(N, C[:2, :2], W)
    m = MixingOperator(N, C, W)
    with pytest.raises(ValueError, match="non-negative"):
        m.spectral_radius(-np.ones(N.shape))


# ---- age contacts -------------------------------------------------------------
def test_aggregate_contacts_is_identity_on_the_same_groups():
    M = RNG.uniform(0, 3, (4, 4))
    out = aggregate_contacts(M, [1, 2, 3, 4], [0, 5, 10, 15], [0, 5, 10, 15])
    assert np.allclose(out, M)


def test_aggregate_contacts_weights_and_splits_groups():
    M = np.array([[2.0, 1.0], [1.0, 4.0]])           # groups 0-9 and 10+ (counted as 10 years)
    out = aggregate_contacts(M, [100.0, 300.0], [0, 10], [0, 5], last_width=10)
    # Band 0-4 holds half of group 0-9 (50 people); band 5+ the other half and all of 10+ (350).
    # A band-b contact count takes the share of each fine group's years that fall in b.
    expected = [[2.0 * 0.5, 2.0 * 0.5 + 1.0],
                [(50 * 2.0 * 0.5 + 300 * 1.0 * 0.5) / 350, (50 * (2.0 * 0.5 + 1.0) + 300 * (0.5 + 4.0)) / 350]]
    assert np.allclose(out, expected)


def test_aggregate_contacts_keeps_total_contacts():
    M = RNG.uniform(0, 3, (16, 16))
    pop = RNG.uniform(1e5, 1e6, 16)
    out = aggregate_contacts(M, pop, np.arange(16) * 5, [0, 18, 65])
    bands_pop = np.array([pop[:3].sum() + 0.6 * pop[3], 0.4 * pop[3] + pop[4:13].sum(), pop[13:].sum()])
    assert (out.sum(axis=1) * bands_pop).sum() == pytest.approx((M.sum(axis=1) * pop).sum())


def test_reciprocal_contacts_balances_totals():
    C = RNG.uniform(0, 5, (3, 3))
    N = np.array([1e5, 5e5, 2e5])
    R = reciprocal_contacts(C, N)
    totals = R * N[:, None]
    assert np.allclose(totals, totals.T)
    assert np.allclose(R, reciprocal_contacts(R, N))           # already reciprocal: unchanged
    with pytest.raises(ValueError):
        reciprocal_contacts(C, [1, 2])


def test_prem_matrix_gives_the_scenario_contacts():
    N = [1378000, 4457000, 1195000]
    C = age_contacts_from_csv(DATA / "prem2021_usa_contacts_all.csv", [0, 18, 65], N)
    assert np.allclose(C.round(2), [[9.00, 8.09, 0.96], [2.50, 10.47, 1.18], [1.11, 4.40, 1.80]])


# ---- patch coupling --------------------------------------------------------------
def test_coupling_from_flows():
    F = np.array([[80, 20, 0], [10, 0, 0], [0, 0, 0]], dtype=float)
    W = coupling_from_flows(F)
    assert np.allclose(W.sum(axis=1), 1)
    assert np.allclose(W[0], [0.8, 0.2, 0]) and np.allclose(W[1], [1, 0, 0]) and np.allclose(W[2], [0, 0, 1])
    W2 = coupling_from_flows(F, home_share=0.7)
    assert np.allclose(W2[0], [0.7, 0.3, 0]) and np.allclose(W2[1], [0.3, 0.7, 0])
    assert np.allclose(W2[2], [0, 0, 1])                       # nowhere to go: always home
    with pytest.raises(ValueError):
        coupling_from_flows(-F)


def test_coupling_from_distance_prefers_near_and_populous():
    D = np.array([[0, 1, 5], [1, 0, 4], [5, 4, 0]], dtype=float)
    W = coupling_from_distance(D, scale_km=2.0, home_share=0.6)
    assert np.allclose(W.sum(axis=1), 1) and np.allclose(np.diag(W), 0.6)
    assert W[0, 1] > W[0, 2]
    Wp = coupling_from_distance(D, scale_km=2.0, home_share=0.6, population=[1, 1, 100])
    assert Wp[0, 2] > W[0, 2]


def test_haversine_boston_to_new_york():
    D = haversine_km([42.3601, 40.7128], [-71.0589, -74.0060])
    assert D[0, 1] == pytest.approx(306, abs=3) and D[0, 0] == 0 and np.allclose(D, D.T)
