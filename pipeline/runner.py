"""Composition root: simulate_run wires the nine weekly blocks.

Order per docs/weekly-state-machine.md:
carry/init -> select injections -> discharges -> SEIR need ->
requests + BEFORE loads -> FDNA pass 1 -> direct reserve + reroute ->
AFTER loads + FDNA pass 2 -> commit accepted -> package -> next state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from . import ALGORITHM_VERSION, il2, il3
from . import analysis as an
from . import fdna as fdna_mod
from . import hospital_state as hs
from .contracts import DataValidationError, RunConfig, require_nonneg
from .injections import resolve_scenario
from .seir import init_state
from .types import (
    Accessibility,
    HospitalState,
    HospitalStateMap,
    RunResult,
    SEIRState,
    WeekSnapshot,
    deep_copy_state_map,
)


@dataclass
class ValidatedInputs:
    config: RunConfig
    districts: list
    hospitals: list
    accessibility: Accessibility
    observed: object = None
    manifest: dict = field(default_factory=dict)
    data_mode: str = "synthetic_demo"
    seeded_cohorts: dict = field(default_factory=dict)  # hospital_id -> list[Cohort]


def _resolve_injection_targets(inj, hospital_ids: set, district_ids: set) -> None:
    """Validate an injection's target IDs exist, regardless of its week (future-
    dated events too; a dependency edit never grants a route)."""
    from .contracts import InvalidInjection

    p = inj.payload
    if inj.kind in ("close_hospital", "set_capacity", "set_score", "reduce_score"):
        if p["hospital_id"] not in hospital_ids:
            raise InvalidInjection(f"{inj.injection_id}: unknown hospital {p['hospital_id']!r}")
    elif inj.kind in ("add_edge", "set_edge", "remove_edge"):
        for k in ("hospital_a", "hospital_b"):
            if p[k] not in hospital_ids:
                raise InvalidInjection(f"{inj.injection_id}: unknown hospital {p[k]!r}")
    elif inj.kind == "set_share":
        if p["hospital_id"] not in hospital_ids:
            raise InvalidInjection(f"{inj.injection_id}: unknown hospital {p['hospital_id']!r}")
        if p["district_id"] not in district_ids:
            raise InvalidInjection(f"{inj.injection_id}: unknown district {p['district_id']!r}")


def _baseline_stock(hospitals, cfg: RunConfig) -> dict[str, float]:
    out = {}
    for h in hospitals:
        if cfg.baseline_stock_policy == "fraction_of_C":
            out[h.hospital_id] = cfg.baseline_fraction * h.staffed_beds
        else:
            out[h.hospital_id] = float(h.baseline_occupancy)
    return out


def _init_hospital_state(hospitals, baseline, seeded_cohorts, district_ids) -> HospitalStateMap:
    from .types import Cohort

    hids = {h.hospital_id for h in hospitals}
    dids = set(district_ids)
    sm: HospitalStateMap = {}
    for h in hospitals:
        raw = seeded_cohorts.get(h.hospital_id, [])
        cohorts = []
        for c in raw:
            # known origin district; finite nonneg count; positive-integer LOS;
            # integer admit_week < 0 (seeded occupants are pre-simulation).
            if c.origin_district_id not in dids:
                raise DataValidationError(
                    f"seeded cohort at {h.hospital_id} has unknown origin "
                    f"district {c.origin_district_id!r}"
                )
            require_nonneg(c.count, f"seeded cohort count at {h.hospital_id}")
            if not isinstance(c.remaining_los, int) or isinstance(c.remaining_los, bool):
                raise DataValidationError(
                    f"seeded cohort at {h.hospital_id} non-integer remaining_los "
                    f"{c.remaining_los!r}"
                )
            if c.remaining_los < 1:
                raise DataValidationError(
                    f"seeded cohort at {h.hospital_id} has remaining_los < 1 ({c.remaining_los})"
                )
            if not isinstance(c.admit_week, int) or isinstance(c.admit_week, bool):
                raise DataValidationError(
                    f"seeded cohort at {h.hospital_id} non-integer admit_week {c.admit_week!r}"
                )
            if c.admit_week >= 0:
                raise DataValidationError(
                    f"seeded cohort at {h.hospital_id} admit_week {c.admit_week} >= 0; "
                    f"seeded (pre-simulation) occupants must use admit_week < 0"
                )
            cohorts.append(Cohort(c.origin_district_id, c.admit_week, c.remaining_los, c.count))
        if h.hospital_id not in hids:  # defensive; hospitals come from this set
            raise DataValidationError(f"seeded cohort for unknown hospital {h.hospital_id}")
        sm[h.hospital_id] = HospitalState(
            hospital_id=h.hospital_id, baseline=baseline[h.hospital_id], cohorts=tuple(cohorts)
        )
    # seeded cohorts keyed to a hospital not in the set is an error
    unknown = set(seeded_cohorts) - hids
    if unknown:
        raise DataValidationError(f"seeded cohorts for unknown hospitals: {sorted(unknown)}")
    return sm


def _f(x) -> str:
    """Exact, lossless float repr for hashing (no rounding, no object hiding)."""
    return repr(float(x))


def _canon(obj) -> str:
    """Deterministic canonical string for hashing. Rejects objects that would be
    hidden by default=str: only dict/list/tuple/str/bool/int/float/None allowed."""
    if obj is None or isinstance(obj, (bool, int, str)):
        return json.dumps(obj, sort_keys=True)
    if isinstance(obj, float):
        return _f(obj)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(_canon(v) for v in obj) + "]"
    if isinstance(obj, dict):
        return (
            "{"
            + ",".join(f"{json.dumps(str(k))}:{_canon(v)}" for k, v in sorted(obj.items()))
            + "}"
        )
    raise TypeError(f"non-canonicalizable object in run_id payload: {type(obj)}")


def _checksum(obj) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()[:16]


def compute_run_id_and_provenance(
    cfg: RunConfig, injections, init_seir, init_state_map, districts, hospitals, acc
):
    """Return (run_id, provenance). provenance includes the initial SEIR state,
    seeded cohorts, and per-component content hashes for full reproducibility."""
    parts = {
        "config": _config_dict(cfg),
        "injections": [
            _injection_dict(i) for i in sorted(injections, key=lambda x: x.injection_id)
        ],
        "init_seir": _seir_dict(init_seir),
        "init_state": _statemap_dict(init_state_map),
        "districts": [_district_dict(d) for d in sorted(districts, key=lambda x: x.district_id)],
        "hospitals": [_hospital_dict(h) for h in sorted(hospitals, key=lambda x: x.hospital_id)],
        # full accessibility content (shares AND distances AND eligibility)
        "accessibility": {
            "shares": {f"{k[0]}|{k[1]}": _f(v) for k, v in acc.shares.items()},
            "distance": {f"{k[0]}|{k[1]}": _f(v) for k, v in acc.distance_km.items()},
            "eligible": {f"{k[0]}|{k[1]}": bool(v) for k, v in acc.eligible.items()},
        },
        "algo": ALGORITHM_VERSION,
    }
    run_id = "run-" + _checksum(parts)
    provenance = {
        "run_id": run_id,
        "algorithm_version": ALGORITHM_VERSION,
        "component_hashes": {k: _checksum(v) for k, v in parts.items()},
        "initial_seir": parts["init_seir"],
        "seeded_cohorts": parts["init_state"],
        "config": parts["config"],
        "injections": parts["injections"],
    }
    return run_id, provenance


def _config_dict(cfg: RunConfig) -> dict:
    return {
        "disease": {
            k: (_f(v) if isinstance(v, float) else v) for k, v in vars(cfg.disease).items()
        },
        "network": {
            k: (_f(v) if isinstance(v, float) else v) for k, v in vars(cfg.network).items()
        },
        "geography_unit": cfg.geography_unit,
        "geography_region": cfg.geography_region,
        "weeks": cfg.weeks,
        "seed": cfg.random_seed,
        "baseline_stock_policy": cfg.baseline_stock_policy,
        "baseline_fraction": _f(cfg.baseline_fraction),
        "nearest_outside_radius_fallback": cfg.nearest_outside_radius_fallback,
        "score_threshold": _f(cfg.score_threshold),
        "tolerances": {k: _f(v) for k, v in vars(cfg.tolerances).items()},
        "fdna": {k: (_f(v) if isinstance(v, float) else v) for k, v in vars(cfg.fdna).items()},
    }


def _district_dict(d) -> dict:
    return {
        "id": d.district_id,
        "population": d.population,
        "risk_weight": _f(d.risk_weight),
        "ej_flag": d.ej_flag,
        "lat": _f(d.centroid_lat),
        "lon": _f(d.centroid_lon),
        "geometry": d.geometry,  # full geometry content
    }


def _hospital_dict(h) -> dict:
    return {
        "id": h.hospital_id,
        "name": h.name,
        "lat": _f(h.lat),
        "lon": _f(h.lon),
        "staffed_beds": h.staffed_beds,
        "icu_beds": h.icu_beds,
        "baseline_occupancy": _f(h.baseline_occupancy),
    }


def _injection_dict(i) -> dict:
    return {
        "id": i.injection_id,
        "kind": i.kind,
        "start": i.start_week,
        "end": i.end_week,
        "note": i.note,
        "payload": {
            k: (_f(v) if isinstance(v, float) else v) for k, v in sorted(i.payload.items())
        },
    }


def _seir_dict(s: SEIRState) -> dict:
    return {
        "week": s.week,
        "S": {k: _f(v) for k, v in s.S.items()},
        "E": {k: _f(v) for k, v in s.E.items()},
        "I": {k: _f(v) for k, v in s.I.items()},
        "R": {k: _f(v) for k, v in s.R.items()},
        "N": {k: _f(v) for k, v in s.N.items()},
    }


def _statemap_dict(sm: HospitalStateMap) -> dict:
    return {
        h: {
            "baseline": _f(st.baseline),
            "cohorts": [
                [c.origin_district_id, c.admit_week, c.remaining_los, _f(c.count)]
                for c in st.cohorts
            ],
        }
        for h, st in sm.items()
    }


def simulate_run(config: RunConfig, inputs: ValidatedInputs, injection_list) -> RunResult:
    cfg = config.validate()
    acc = inputs.accessibility
    hospitals = inputs.hospitals
    districts = inputs.districts

    # Boundary validation: validate every entity (risk/beds/coords/units), then
    # reject duplicate district / hospital / injection IDs, BEFORE accessibility.
    for d in districts:
        d.validate()
    for h in hospitals:
        h.validate()
    d_ids = [d.district_id for d in districts]
    if len(set(d_ids)) != len(d_ids):
        raise DataValidationError("duplicate district_id in inputs")
    h_ids = [h.hospital_id for h in hospitals]
    if len(set(h_ids)) != len(h_ids):
        raise DataValidationError("duplicate hospital_id in inputs")
    # Validate injections and resolve EVERY event's target IDs against the known
    # entity sets (even events whose weeks are outside the horizon).
    inj_ids = [i.injection_id for i in injection_list]
    if len(set(inj_ids)) != len(inj_ids):
        raise DataValidationError(f"duplicate injection_id: {inj_ids}")
    h_set, d_set = set(h_ids), set(d_ids)
    for inj in injection_list:
        inj.validate()
        _resolve_injection_targets(inj, h_set, d_set)

    net, fdna = cfg.network, cfg.fdna
    tol = cfg.tolerances
    eps = tol.move_epsilon
    risk_weight = {d.district_id: d.risk_weight for d in districts}
    baseline = _baseline_stock(hospitals, cfg)

    state = init_state(districts, cfg.disease)
    hstate = _init_hospital_state(hospitals, baseline, inputs.seeded_cohorts, d_ids)
    run_id, provenance = compute_run_id_and_provenance(
        cfg, injection_list, state, hstate, districts, hospitals, acc
    )

    # Precompute per-district effective shares cache helper
    from .seir import step_week

    weeks_out = []
    warnings: list[str] = []
    for t in range(cfg.weeks):
        scn = resolve_scenario(t, hospitals, net, injection_list, acc.district_ids)

        # STEP 3: discharges (new state map; retained measured before commit)
        hstate_after_discharge, discharged, retained = hs.discharge_due(hstate, t)

        # STEP 4: SEIR need
        epi = step_week(state, cfg.disease, risk_weight)

        shares_by_district = {j: il2.effective_shares(acc, j, scn) for j in acc.district_ids}

        # STEP 5: requests + BEFORE loads
        requests = il2.compute_requests(epi.h_need, acc, scn)
        request_i = {h: requests.request_i(h) for h in acc.hospital_ids}
        before_loads = il2.compute_loads(acc.hospital_ids, baseline, retained, request_i, scn)
        graph = il2.build_graph(acc, scn)

        # STEP 6: FDNA pass 1
        before_fdna = fdna_mod.solve(before_loads, graph, acc, net, fdna, shares_by_district)
        before_alloc = an.reserve_direct(
            requests, baseline, retained, scn, acc, eps, shares_by_district
        )
        before = WeekSnapshot("before", before_loads, before_fdna, before_alloc.frozen())

        # STEP 7: reroute (AFTER allocation)
        after_alloc = an.reroute(
            before_alloc, baseline, retained, scn, acc, t, eps, shares_by_district
        )

        # STEP 8: AFTER loads + FDNA pass 2
        post_req = an.post_request_i(after_alloc, acc.hospital_ids)
        after_loads = il2.compute_loads(acc.hospital_ids, baseline, retained, post_req, scn)
        after_fdna = fdna_mod.solve(after_loads, graph, acc, net, fdna, shares_by_district)
        after = WeekSnapshot("after", after_loads, after_fdna, after_alloc.frozen())

        # STEP 9: commit (AFTER only)
        hstate_committed = hs.commit_week(
            hstate_after_discharge, after_alloc, t, cfg.disease.los_weeks
        )

        deficit = il3.inherited_deficit(
            baseline, retained, scn.effective_capacity, acc.hospital_ids
        )

        diagnostics = _week_diagnostics(
            epi,
            acc,
            before_loads,
            after_loads,
            before_fdna,
            after_fdna,
            after_alloc,
            baseline,
            retained,
            scn,
            tol,
        )
        # Hard invariants must RAISE, never render a result with a false check.
        for key in ("mass", "patient_mass", "capacity_bound", "fdna_convergence"):
            if diagnostics.get(key) is False:
                raise DataValidationError(
                    f"week {t}: invariant {key!r} failed; refusing to return a result"
                )
        if diagnostics.get("zero_move_identity") is False:
            raise DataValidationError(
                f"week {t}: zero-move identity violated (before != after with no reroutes)"
            )

        week_result = il3.package_results(
            epi,
            before,
            after,
            deep_copy_state_map(hstate_committed),  # isolated snapshot for history
            scn.active_injections,
            deficit,
            diagnostics,
        )
        weeks_out.append(week_result)

        # advance (carry a separate deep copy forward so history can't be mutated)
        hstate = deep_copy_state_map(hstate_committed)
        state = il3.next_state(epi)

    return RunResult(
        run_id=run_id,
        data_mode=inputs.data_mode,
        config=cfg,
        weeks=tuple(weeks_out),
        validation=inputs.manifest.get("validation"),
        data_manifest=dict(inputs.manifest),
        warnings=tuple(warnings),
        provenance=provenance,
    )


def _week_diagnostics(
    epi,
    acc,
    before_loads,
    after_loads,
    before_fdna,
    after_fdna,
    after_alloc,
    baseline,
    retained,
    scn,
    tol,
) -> dict:
    checks = {}

    # SEIR mass: S+E+I+R == N
    mass_ok = True
    s = epi.state_end
    for j in acc.district_ids:
        total = s.S[j] + s.E[j] + s.I[j] + s.R[j]
        if abs(total - s.N[j]) > tol.mass_tol * max(1.0, s.N[j]):
            mass_ok = False
    checks["mass"] = mass_ok

    # accepted + unmet == h_need per district (after)
    patient_ok = True
    for j in acc.district_ids:
        acc_j = sum(v for (d, h), v in after_alloc.accepted.items() if d == j)
        unmet_j = after_alloc.unmet_by_district.get(j, 0.0)
        target = epi.h_need.get(j, 0.0)
        if abs(acc_j + unmet_j - target) > tol.patient_tol * max(1.0, target) + tol.patient_tol:
            patient_ok = False
    checks["patient_mass"] = patient_ok

    # committed <= max(Ceff, baseline+retained)
    cap_ok = True
    for h in acc.hospital_ids:
        committed = after_alloc.projected_occupancy[h]
        bound = max(
            scn.effective_capacity.get(h, 0.0),
            baseline.get(h, 0.0) + retained.get(h, 0.0),
        )
        if committed > bound + tol.patient_tol:
            cap_ok = False
    checks["capacity_bound"] = cap_ok

    checks["fdna_convergence"] = bool(before_fdna.converged and after_fdna.converged)

    # zero-move => before == after loads and scores
    if not after_alloc.reroutes:
        loads_same = all(
            abs(after_loads[h].requested_load - before_loads[h].requested_load) < 1e-9
            for h in acc.hospital_ids
        )
        scores_same = all(
            abs(after_fdna.hospital_scores[h] - before_fdna.hospital_scores[h]) < 1e-9
            for h in acc.hospital_ids
        )
        checks["zero_move_identity"] = bool(loads_same and scores_same)
    else:
        checks["zero_move_identity"] = None

    return checks
