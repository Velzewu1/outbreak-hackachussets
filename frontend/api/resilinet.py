"""ResiliNet weekly pipeline over HTTP: the site's top-level pages.

Like main.py, nothing here models anything. It calls ``pipeline.api`` (the same
facade the Streamlit app uses), adds display labels such as tract and
neighborhood names, and packs results into compact JSON for the browser.

    GET  /api/rn/meta              datasets, defaults, slider ranges, event kinds
    GET  /api/rn/geo/{dataset}     district outlines (feature id = district index)
    POST /api/rn/run               scenario + baseline, every week, before and after
    POST /api/rn/export/{file}     hospital_week.csv, district_week.csv, reroute_week.csv, run.json
    GET  /api/rn/evaluation        historical backtest vs persistence (artifacts/evaluation.json)
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from pipeline import api as rn  # noqa: E402

router = APIRouter(prefix="/api/rn")

Dataset = Literal["real", "synthetic", "golden"]

DATASETS = {
    "real": {
        "title": "Suffolk County · census tracts",
        "mode": "Mixed assumptions",
        "label": "Real Suffolk tracts and hospitals, licensed beds as capacity, simulated epidemic",
        "synthetic": False,
    },
    "synthetic": {
        "title": "Synthetic city · 24 districts",
        "mode": "Synthetic",
        "label": "Synthetic, illustrative only. Not observed Boston data",
        "synthetic": True,
    },
    "golden": {
        "title": "Test fixture · 3 districts",
        "mode": "Synthetic",
        "label": "Synthetic 3-by-3 unit-test fixture",
        "synthetic": True,
    },
}

# Streamlit defaults and slider ranges (app/streamlit_app.py), so both front ends agree.
PARAMS = {
    "r0": {"min": 0.5, "max": 5.0, "step": 0.1, "default": 2.6},
    "p_h": {"min": 0.005, "max": 0.1, "step": 0.005, "default": 0.03},
    "seed": {"min": 0.0005, "max": 0.01, "step": 0.0005, "default": 0.003},
    "d0": {"min": 0.5, "max": 15.0, "step": 0.5, "default": 3.0},
    "alpha_d": {"min": 0.0, "max": 1.0, "step": 0.05, "default": 0.9},
    "alpha_h": {"min": 0.0, "max": 1.0, "step": 0.05, "default": 0.1},
    "weeks": {"min": 2, "max": 16, "step": 1, "default": 8},
}

EXPORTS = {
    "hospital_week.csv": "text/csv",
    "district_week.csv": "text/csv",
    "reroute_week.csv": "text/csv",
    "run.json": "application/json",
}

EVALUATION = REPO / "artifacts" / "evaluation.json"


# ---- requests ------------------------------------------------------------------
class RnEvent(BaseModel):
    id: str
    kind: Literal["close_hospital", "set_capacity"]
    hospital_id: str
    start_week: int = Field(ge=0)
    end_week: int | None = None  # exclusive, like the engine
    factor: float | None = Field(default=None, ge=0, le=1)


class RnRun(BaseModel):
    dataset: Dataset = "real"
    r0: float = PARAMS["r0"]["default"]
    p_h: float = PARAMS["p_h"]["default"]
    seed: float = PARAMS["seed"]["default"]
    d0: float = PARAMS["d0"]["default"]
    alpha_d: float = PARAMS["alpha_d"]["default"]
    alpha_h: float = PARAMS["alpha_h"]["default"]
    weeks: int = PARAMS["weeks"]["default"]
    fallback: bool = True
    events: list[RnEvent] = []

    def config_json(self) -> str:
        return json.dumps(
            {
                "disease": {
                    "r0": self.r0,
                    "initial_infectious_fraction": self.seed,
                    "p_h": self.p_h,
                },
                "network": {"d0_km": self.d0, "alpha_d": self.alpha_d, "alpha_h": self.alpha_h},
                "weeks": self.weeks,
                "nearest_outside_radius_fallback": self.fallback,
            },
            sort_keys=True,
        )

    def events_json(self) -> str:
        return json.dumps([e.model_dump() for e in self.events], sort_keys=True)


# ---- helpers -------------------------------------------------------------------
def _f(x, nd: int = 2):
    """Plain rounded float; NaN/inf -> None."""
    x = float(x)
    return round(x, nd) if math.isfinite(x) else None


def _plain(x):
    """numpy scalars and frozen containers -> plain JSON values."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if hasattr(x, "item"):
        x = x.item()
    if isinstance(x, float):
        return _f(x, 4)
    return x


@lru_cache(maxsize=16)
def _inputs(dataset: str, config_json: str):
    try:
        return rn.load_inputs(dataset, rn.run_config_from_dict(json.loads(config_json)))
    except Exception as e:  # the engine's own message names what is wrong
        raise HTTPException(422, str(e)) from e


@lru_cache(maxsize=1)
def _neighborhoods():
    """Boston neighborhood outlines (seir/systems/boston_districts.geojson), if present."""
    path = REPO / "seir" / "systems" / "boston_districts.geojson"
    if not path.exists():
        return []
    from shapely.geometry import shape

    gj = json.loads(path.read_text())
    return [(f["properties"]["patch"], shape(f["geometry"])) for f in gj["features"]]


@lru_cache(maxsize=1)
def _tract_codes() -> dict[str, str]:
    path = REPO / "data" / "raw" / "massgis-suffolk-tracts-2020.geojson"
    if not path.exists():
        return {}
    gj = json.loads(path.read_text())
    return {f["properties"]["GEOID20"]: f["properties"]["NAME20"] for f in gj["features"]}


# Suffolk County outside Boston, by census tract number.
_TOWNS = {"16": "Chelsea", "17": "Revere", "18": "Winthrop"}


def _place(district_id: str, lat: float, lon: float) -> tuple[str, str]:
    """(name, area) for a district: a census tract and the neighborhood or town it sits in."""
    code = _tract_codes().get(district_id)
    if code is None:
        return district_id, ""
    town = _TOWNS.get(code.split(".")[0].zfill(4)[:2])
    if town:
        return f"Tract {code}", town
    hoods = _neighborhoods()
    if not hoods:
        return f"Tract {code}", "Boston"
    from shapely.geometry import Point

    p = Point(lon, lat)
    for name, poly in hoods:
        if poly.contains(p):
            return f"Tract {code}", name
    # harbor-edge centroids can fall just outside the drawn outlines
    name = min(hoods, key=lambda h: h[1].distance(p))[0]
    return f"Tract {code}", name


def _injections(req: RnRun) -> list:
    out = []
    for e in req.events:
        payload = {"hospital_id": e.hospital_id}
        if e.kind == "set_capacity":
            payload["factor"] = 0.6 if e.factor is None else e.factor
        try:
            out.append(rn.make_injection(e.id, e.kind, e.start_week, payload, e.end_week, _note(e)))
        except Exception as exc:
            raise HTTPException(422, f"Event {e.id}: {exc}") from exc
    return out


def _note(e: RnEvent) -> str:
    end = "end" if e.end_week is None else e.end_week
    what = "close" if e.kind == "close_hospital" else f"capacity x{e.factor}"
    return f"{what} {e.hospital_id} weeks {e.start_week}-{end}"


@lru_cache(maxsize=8)
def _baseline(dataset: str, config_json: str):
    return rn.run_scenario(_inputs(dataset, config_json), [])


@lru_cache(maxsize=16)
def _runs(dataset: str, config_json: str, events_json: str):
    """(inputs, scenario run, baseline run or None) for one request."""
    inputs = _inputs(dataset, config_json)
    req = RnRun(dataset=dataset, events=json.loads(events_json))
    injections = _injections(req)
    try:
        base = _baseline(dataset, config_json)
        run = rn.run_scenario(inputs, injections) if injections else base
    except Exception as e:
        raise HTTPException(422, str(e)) from e
    return inputs, run, (base if injections else None)


def _view(run, week: int, phase: str) -> dict:
    """One week and phase, with district values as arrays in district-id order."""
    v = rn.get_week(run, week, phase)
    return {
        "metrics": {k: (int(x) if isinstance(x, int) else _f(x)) for k, x in v["metrics"].items()},
        "hospitals": [
            {
                "id": h["hospital_id"],
                "baseline": _f(h["baseline_beds"], 1),
                "retained": _f(h["retained_beds"], 1),
                "request": _f(h["request_people"], 2),
                "load": _f(h["requested_load"], 1),
                "capacity": _f(h["effective_capacity_beds"], 1),
                "committed": _f(h["committed_beds"], 1),
                "accepted": _f(h["accepted_new_beds"], 2),
                "deficit": _f(h["inherited_deficit_beds"], 1),
                "own": _f(h["own_score"], 1),
                "score": _f(h["fdna_final_score"], 1),
                "excess": _f(h["excess"], 1),
                "closed": bool(h["closed"]),
            }
            for h in v["hospitals"]
        ],
        "access": [_f(d["access_score"], 1) for d in v["districts"]],
        "need": [_f(d["new_admission_need_people"], 3) for d in v["districts"]],
        "unmet": [_f(d["unmet_need_people"], 3) for d in v["districts"]],
        "reroutes": [
            {
                "district": r["district"],
                "from": r["source_hospital"],
                "to": r["destination"],
                "amount": _f(r["amount"], 3),
            }
            for r in v["reroutes"]
        ],
        "events": [i["id"] for i in v["active_injections"]],
        "checks": {k: bool(x) for k, x in v["diagnostics"].items() if isinstance(x, bool)},
    }


def _views(run) -> list[dict]:
    return [
        {"before": _view(run, w, "before"), "after": _view(run, w, "after")}
        for w in rn.list_weeks(run)
    ]


def _manifest(inputs) -> dict:
    """The data manifest, minus raw geometries (they are on the map already)."""
    m = _plain(dict(inputs.manifest))
    pop = m.get("population")
    if isinstance(pop, dict) and "zero_pop_geometries" in pop:
        pop = dict(pop)
        pop["zero_pop_geometries"] = sorted(pop["zero_pop_geometries"])
        m["population"] = pop
    return m


# ---- endpoints -----------------------------------------------------------------
@router.get("/meta")
def meta():
    available = {d.name for d in rn.available_datasets()}
    return {
        "datasets": [
            {"id": k, **v, "available": k in available}
            for k, v in DATASETS.items()
            if k in available
        ],
        "params": PARAMS,
        "threshold": rn.RunConfig().score_threshold,
        "radius_km": rn.NetworkConfig().radius_km,
        "events": [
            {"kind": "close_hospital", "label": "Close a hospital"},
            {"kind": "set_capacity", "label": "Cut a hospital's beds", "factor": 0.6},
        ],
    }


@lru_cache(maxsize=4)
def _geo(dataset: str) -> dict:
    inputs = _inputs(dataset, RnRun(dataset=dataset).config_json())
    gj = rn.district_geojson(inputs)
    order = {
        d: i for i, d in enumerate(sorted(f["properties"]["district_id"] for f in gj["features"]))
    }

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 5), round(c[1], 5)]

    feats = []
    for f in gj["features"]:
        did = f["properties"]["district_id"]
        g = f["geometry"]
        feats.append(
            {
                "type": "Feature",
                "id": order[did],
                "properties": {"district_id": did},
                "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])},
            }
        )
    feats.sort(key=lambda f: f["id"])
    return {"type": "FeatureCollection", "features": feats}


@router.get("/geo/{dataset}")
def geo(dataset: Dataset):
    return _geo(dataset)


@router.post("/run")
def run(req: RnRun):
    if req.dataset not in {d.name for d in rn.available_datasets()}:
        raise HTTPException(422, f"Dataset {req.dataset!r} is not available here.")
    inputs, scen, base = _runs(req.dataset, req.config_json(), req.events_json())
    acc = inputs.accessibility
    districts = []
    for d in sorted(inputs.districts, key=lambda d: d.district_id):
        name, area = _place(d.district_id, d.centroid_lat, d.centroid_lon)
        catchment = sorted(
            (
                {
                    "id": h,
                    "km": _f(acc.distance_km[(d.district_id, h)], 2),
                    "share": _f(acc.shares[(d.district_id, h)], 4),
                }
                for h in acc.hospital_ids
                if acc.shares.get((d.district_id, h), 0.0) > 0
            ),
            key=lambda c: -c["share"],
        )
        districts.append(
            {
                "id": d.district_id,
                "name": name,
                "area": area,
                "population": int(d.population),
                "risk": _f(d.risk_weight, 3),
                "ej": d.ej_flag,
                "lat": _f(d.centroid_lat, 5),
                "lon": _f(d.centroid_lon, 5),
                "access_index": _f(acc.total_accessibility[d.district_id], 3),
                "catchment": catchment,
            }
        )
    ids = [d["id"] for d in districts]
    epi = {"new_infections": [], "need": [], "infectious": [], "susceptible": []}
    for w in scen.weeks:
        pop = sum(w.state.N[j] for j in ids)
        epi["new_infections"].append(_f(sum(w.new_infections.get(j, 0.0) for j in ids), 1))
        epi["need"].append(_f(sum(w.h_need.get(j, 0.0) for j in ids), 2))
        epi["infectious"].append(_f(sum(w.state.I[j] for j in ids), 1))
        epi["susceptible"].append(_f(sum(w.state.S[j] for j in ids) / pop, 4))
    meta_ = DATASETS[req.dataset]
    manifest = _manifest(inputs)
    return {
        "run_id": scen.run_id,
        "base_run_id": base.run_id if base else scen.run_id,
        "dataset": req.dataset,
        "data_mode": scen.data_mode,
        "mode": meta_["mode"],
        "mode_label": meta_["label"],
        "synthetic": meta_["synthetic"],
        "threshold": scen.config.score_threshold,
        "weeks": len(scen.weeks),
        "warnings": list(scen.warnings),
        "fallback_districts": list(manifest.get("nearest_fallback_districts", [])),
        "manifest": manifest,
        "hospitals": [
            {
                "id": h["hospital_id"],
                "name": h["name"],
                "lat": _f(h["lat"], 5),
                "lon": _f(h["lon"], 5),
                "beds": int(h["staffed_beds"]),
                "icu": int(h["icu_beds"]),
            }
            for h in rn.list_hospitals(inputs)
        ],
        "districts": districts,
        "epi": epi,
        "scenario": _views(scen),
        "baseline": _views(base) if base else None,
    }


@router.post("/export/{name}")
def export(name: str, req: RnRun):
    if name not in EXPORTS:
        raise HTTPException(404, f"unknown export {name!r}")
    _inputs_, scen, _base = _runs(req.dataset, req.config_json(), req.events_json())
    body = rn.export_json(scen) if name == "run.json" else rn.export_csv(scen, name[:-4])
    return Response(
        body,
        media_type=EXPORTS[name],
        headers={"content-disposition": f'attachment; filename="{name}"'},
    )


_eval_lock = threading.Lock()


def _evaluation() -> dict:
    """artifacts/evaluation.json, computed once with scripts/run_backtest.py if missing."""
    with _eval_lock:
        if not EVALUATION.exists():
            env = {**os.environ, "PYTHONPATH": str(REPO)}
            subprocess.run(
                [sys.executable, "scripts/run_backtest.py"],
                cwd=REPO,
                env=env,
                check=False,
                capture_output=True,
                timeout=600,
            )
        if not EVALUATION.exists():
            return {"status": "unavailable", "reason": "the backtest could not be computed"}
        return json.loads(EVALUATION.read_text())


@router.get("/evaluation")
def evaluation():
    report = _evaluation()
    if report.get("status") == "unavailable":
        return report
    from validation.backtest import MODEL_TO_CCN

    names = {h.hospital_id: h.name for h in _inputs("real", RnRun().config_json()).hospitals}
    facilities: dict[str, dict] = {}
    for hid, ccn in sorted(MODEL_TO_CCN.items()):
        f = facilities.setdefault(ccn, {"hospitals": [], "names": []})
        f["hospitals"].append(hid)
        f["names"].append(names.get(hid, hid))
    for f in facilities.values():
        n = f["names"]
        f["name"] = n[0] if len(n) == 1 else f"{os.path.commonprefix(n).rstrip(' -')} (combined)"
    return _plain({**report, "facilities": facilities})
