"""Who infects whom across patches (neighborhoods) and age groups.

Force of infection on residents of patch p, age a:

    foi[p, a] = beta * sum_r W[p, r] * sum_b C[a, b] * I_loc[r, b] / N_loc[r, b]

where I_loc and N_loc count infectious and total people present in location r
(residents spread by W). The operator is applied in factored form, so cost
grows with patches * ages, never with (patches * ages) ** 2. W can be a dense
array or a scipy.sparse matrix (thousands of tracts that mostly mix with
their neighbours).

The helpers at the bottom build W from data: an origin-destination table
(MBTA trips, commuting flows) or a distance kernel between patch centroids.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components


class MixingOperator:
    # Blocks of up to this many cells get exact eigenvalues; larger ones use
    # power iteration with a warm start from the previous call.
    DENSE_MAX = 64

    def __init__(self, N: np.ndarray, C: np.ndarray, W):
        self.N = np.asarray(N, dtype=float)   # [P, A] residents
        self.C = np.asarray(C, dtype=float)   # [A, A] age contacts
        self.W = W if sparse.issparse(W) else np.asarray(W, dtype=float)  # [P, R] time shares
        self.shape = self.N.shape
        P, A = self.shape
        if self.C.shape != (A, A) or self.W.shape[0] != P:
            raise ValueError(f"shapes do not match: N {self.N.shape}, C {self.C.shape}, W {self.W.shape}")
        self.N_loc = np.asarray(self.W.T @ self.N)          # [R, A] people present at each location
        # 1 / N_loc, with 0 where nobody of that age is ever present (nothing to infect there)
        self._inv_loc = np.divide(1.0, self.N_loc, out=np.zeros_like(self.N_loc), where=self.N_loc > 0)
        self._blocks = self._find_blocks()
        self._groups = None                                 # exact path: stacked small blocks
        self._v: dict[int, np.ndarray] = {}                 # large block -> warm start

    # ---- the operator ----------------------------------------------------
    def apply(self, x: np.ndarray) -> np.ndarray:
        """M @ x for x shaped [P, A] (e.g. infectious counts). Returns [P, A]."""
        prev_loc = np.asarray(self.W.T @ x) * self._inv_loc   # [R, B] infectious share where people are
        exposure_loc = prev_loc @ self.C.T                    # [R, A] weighted by age contacts
        return np.asarray(self.W @ exposure_loc)              # [P, A] back to residents

    def matrix(self, patches=None) -> np.ndarray:
        """M as a dense [(P A), (P A)] array (cells in patch-major order), for inspection and tests.

        M[(p, a), (q, b)] = C[a, b] * sum_r W[p, r] W[q, r] / N_loc[r, b]. With
        `patches`, only the rows and columns of those patches.
        """
        idx = np.arange(self.shape[0]) if patches is None else np.asarray(patches)
        Wb = self.W[idx]
        Wb = Wb.toarray() if sparse.issparse(Wb) else Wb
        K = np.einsum("pr,rb,qr->bpq", Wb, self._inv_loc, Wb)    # [B, P, Q]
        M = np.einsum("ab,bpq->paqb", self.C, K)
        n = len(idx) * self.shape[1]
        return M.reshape(n, n)

    # ---- dominant eigenvalue, for R0 and R_eff -----------------------------
    def spectral_radius(self, weights: np.ndarray, iters: int = 1000, tol: float = 1e-10) -> float:
        """Dominant eigenvalue of diag(weights) @ M.

        With weights = S * beta * infectious_days this is R_eff. Patches that
        never mix with each other form separate blocks, and the answer is the
        largest block's value: exact for small blocks, shifted power iteration
        with a warm start (which also handles periodic contact structures) for
        large ones.
        """
        w = np.broadcast_to(np.asarray(weights, dtype=float), self.shape)
        if not np.isfinite(w).all() or (w < 0).any():
            raise ValueError("weights must be finite and non-negative")
        rho = self._exact(w)
        for k, b in enumerate(self._blocks):
            if b.size * self.shape[1] > self.DENSE_MAX:
                rho = max(rho, self._power(w, k, iters, tol))
        return float(rho)

    def _find_blocks(self) -> list[np.ndarray]:
        """Groups of patches whose residents share a location, directly or through others."""
        Wp = (sparse.csr_array(self.W) != 0).astype(float)
        n, labels = connected_components(Wp @ Wp.T, directed=False)
        return [np.flatnonzero(labels == k) for k in range(n)]

    def _exact(self, w: np.ndarray) -> float:
        if self._groups is None:
            # Small blocks of equal size are stacked so numpy solves them in one call.
            by_size: dict[int, list[np.ndarray]] = {}
            for b in self._blocks:
                if b.size * self.shape[1] <= self.DENSE_MAX:
                    by_size.setdefault(b.size, []).append(b)
            self._groups = [(np.stack(bs), np.stack([self.matrix(b) for b in bs]))
                            for bs in by_size.values()]
        rho = 0.0
        for idx, mats in self._groups:                      # idx [blocks, patches], mats [blocks, n, n]
            rows = w[idx].reshape(len(idx), -1, 1)
            rho = max(rho, float(np.abs(np.linalg.eigvals(rows * mats)).max()))
        return rho

    def _power(self, w: np.ndarray, k: int, iters: int, tol: float) -> float:
        cells = np.zeros(self.shape, dtype=bool)
        cells[self._blocks[k]] = True
        flat = cells / cells.sum()
        # Warm start from the previous call. Patches in one block all mix, so
        # the dominant eigenvector is positive everywhere and no cell can be
        # stuck at zero; the tiny flat part only guards against round-off.
        v = flat if k not in self._v else (self._v[k] + 1e-12 * flat) / (1 + 1e-12)
        shift, rho = None, 0.0
        for _ in range(iters):
            Av = w * self.apply(v) * cells
            new_rho = float(Av.sum())             # sum(Av) / sum(v), and sum(v) = 1
            if new_rho <= 0.0:
                return 0.0
            if shift is None:
                shift = 0.1 * new_rho             # with s > 0 the Perron root is strictly dominant
            v = (Av + shift * v) / (new_rho + shift)
            done = abs(new_rho - rho) <= tol * new_rho
            rho = new_rho
            if done:
                break
        self._v[k] = v
        return rho


# ---- building the age contact matrix C from data ---------------------------
def _band_shares(group_starts, band_starts, last_width: float) -> np.ndarray:
    """[group, band] share of each fine age group falling in each band (ages spread evenly)."""
    g = np.asarray(group_starts, dtype=float)
    b = np.asarray(band_starts, dtype=float)
    if (np.diff(g) <= 0).any() or (np.diff(b) <= 0).any():
        raise ValueError("age group and band starts must be increasing")
    if b[0] > g[0]:
        raise ValueError(f"the first band must start at or below {g[0]:g}")
    g_hi = np.append(g[1:], g[-1] + last_width)
    b_hi = np.append(b[1:], np.inf)
    overlap = np.clip(np.minimum(g_hi[:, None], b_hi[None, :]) - np.maximum(g[:, None], b[None, :]), 0, None)
    return overlap / (g_hi - g)[:, None]


def aggregate_contacts(matrix, group_population, group_starts, band_starts,
                       last_width: float = 5.0) -> np.ndarray:
    """Collapse a fine age contact matrix (e.g. Prem 2021, 16 five-year groups) to coarser bands.

    matrix[i, j] is daily contacts of a person in group i with people in
    group j. Band a gets the population-weighted mean over its groups of the
    contacts with every group in band b. A group that straddles a band edge
    (15-19 for an 18+ cut) is split in proportion to the years on each side.
    The last group is open-ended and counts as `last_width` years.

        aggregate_contacts(M, pop, [0, 5, ..., 75], [0, 18, 65])
    """
    M = np.asarray(matrix, dtype=float)
    w = np.asarray(group_population, dtype=float)
    if M.ndim != 2 or M.shape[0] != M.shape[1] or M.shape[0] != len(w) or len(w) != len(group_starts):
        raise ValueError("matrix, group_population and group_starts must describe the same age groups")
    if (M < 0).any() or (w <= 0).any():
        raise ValueError("contacts must be non-negative and populations positive")
    B = _band_shares(group_starts, band_starts, last_width)     # [group, band]
    people = B * w[:, None]                                    # people of each group in each band
    if (people.sum(axis=0) <= 0).any():
        raise ValueError("every band needs at least part of one age group")
    return (people.T @ M @ B) / people.sum(axis=0)[:, None]


def reciprocal_contacts(C, N) -> np.ndarray:
    """Make C consistent with a population: N[a] C[a, b] = N[b] C[b, a].

    Contacts counted from both sides must match, but a matrix built from
    surveys or for another population rarely does. This averages the two
    totals (the usual correction) for the population being modelled, e.g.
    the scenario's age totals.
    """
    C = np.asarray(C, dtype=float)
    N = np.asarray(N, dtype=float).reshape(-1)
    if C.ndim != 2 or C.shape != (len(N), len(N)):
        raise ValueError("C must be square with one row per population group")
    if (N <= 0).any():
        raise ValueError("population must be positive")
    total = C * N[:, None]
    return (total + total.T) / 2 / N[:, None]


# ---- building the patch coupling matrix W from data ------------------------
def coupling_from_flows(flows, home_share: float | None = None) -> np.ndarray:
    """W from an origin-destination table, e.g. MBTA trips or commuting flows.

    flows[p, r] counts trips (or hours) of residents of p spent in r. Without
    `home_share`, rows are normalised as they are, so the diagonal must
    already hold time at home. With it, residents spend `home_share` of their
    time in their own patch and split the rest over the other patches in
    proportion to the off-diagonal flows.
    """
    F = np.asarray(flows, dtype=float)
    if F.ndim != 2 or F.shape[0] != F.shape[1] or (F < 0).any():
        raise ValueError("flows must be a square, non-negative matrix")
    n = F.shape[0]
    if home_share is None:
        rows = F.sum(axis=1, keepdims=True)
        W = np.divide(F, rows, out=np.zeros_like(F), where=rows > 0)
        W[rows[:, 0] == 0] = np.eye(n)[rows[:, 0] == 0]
        return W
    if not 0.0 <= home_share <= 1.0:
        raise ValueError("home_share must be between 0 and 1")
    away = F * (1.0 - np.eye(n))
    rows = away.sum(axis=1, keepdims=True)
    share = np.divide(away, rows, out=np.zeros_like(away), where=rows > 0)
    stay = np.where(rows[:, 0] > 0, home_share, 1.0)        # nowhere to go: always home
    return stay[:, None] * np.eye(n) + (1.0 - stay)[:, None] * share


def coupling_from_distance(distance_km, scale_km: float = 2.0, home_share: float = 0.75,
                           population=None) -> np.ndarray:
    """W from a distance kernel: time away from home goes to nearby, populous patches.

    Residents spend `home_share` of their time at home. The rest is split over
    the other patches with weight population[r] * exp(-distance / scale_km)
    (a gravity model; without `population` every patch weighs the same).
    """
    D = np.asarray(distance_km, dtype=float)
    if D.ndim != 2 or D.shape[0] != D.shape[1] or (D < 0).any():
        raise ValueError("distance_km must be a square, non-negative matrix")
    if scale_km <= 0:
        raise ValueError("scale_km must be positive")
    mass = np.ones(D.shape[0]) if population is None else np.asarray(population, dtype=float)
    return coupling_from_flows(mass[None, :] * np.exp(-D / scale_km), home_share=home_share)


def haversine_km(lat, lon) -> np.ndarray:
    """Great-circle distances between points given in degrees, as a [n, n] matrix in km."""
    lat, lon = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lon, dtype=float))
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    h = np.sin(dlat / 2) ** 2 + np.cos(lat)[:, None] * np.cos(lat)[None, :] * np.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))
