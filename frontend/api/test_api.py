"""Smoke tests for the HTTP layer: every endpoint answers with the shapes the site reads.

    pytest frontend/api
"""
import pytest
from fastapi.testclient import TestClient

from main import SCENARIOS, app

client = TestClient(app)


def post(path, body):
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_scenarios_and_details():
    ids = {s["id"] for s in client.get("/api/scenarios").json()}
    assert ids == set(SCENARIOS)
    for sid in ids:
        r = client.get(f"/api/scenario/{sid}")
        assert r.status_code == 200, r.text
        assert r.json()["describe"]["r0"] > 0
    assert client.get("/api/scenario/nope").status_code == 404


def test_presets():
    p = client.get("/api/presets").json()
    assert "covid_omicron" in p["diseases"] and p["sources"]


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_every_scenario_runs(sid):
    r = post("/api/run", {"scenario": sid})
    days = len(r["epi"]["dates"])
    assert days > 0 and len(r["epi"]["citywide"]["S"]) == days
    assert len(r["epi"]["rates"]["r_eff"]) == days
    if SCENARIOS[sid]["kind"] == "system":
        s = r["system"]
        assert len(s["occupancy_ward"]) == days and len(s["occupancy_ward"][0]) == len(s["hospitals"])
        assert len(s["access"][0]) == len(r["geo"]["patches"])
        assert r["geo"]["mappable"]
    else:
        assert r["system"] is None


def test_changes_apply():
    base = post("/api/run", {"scenario": "boston_city"})
    hot = post("/api/run", {"scenario": "boston_city", "epi": {"disease.r0": 2.6, "sim.days": 90},
                            "system": {"rerouting.occ_on": 0.9},
                            "events": [{"node": "MGH.staff", "value": 20, "start": 10, "end": 50}]})
    assert len(hot["epi"]["dates"]) == 90
    assert hot["epi"]["summary"]["attack_rate"] > base["epi"]["summary"]["attack_rate"]
    assert hot["system"]["summary"]["hospital_days_on_diversion"] > base["system"]["summary"]["hospital_days_on_diversion"]


def test_bad_changes_are_422():
    assert client.post("/api/run", json={"scenario": "boston_city", "epi": {"disease.r0": -1}}).status_code == 422
    assert client.post("/api/run", json={"scenario": "boston_city",
                                         "events": [{"node": "nowhere", "value": 0}]}).status_code == 422


def test_ensemble_sensitivity_criticality_validation():
    e = post("/api/ensemble", {"scenario": "example_3patch", "runs": 4})
    assert len(e["bands"]["inpatients"]) == 5 and 0 <= e["takeoff_share"] <= 1
    s = post("/api/sensitivity", {"scenario": "example_3patch", "params": ["disease.r0"]})
    assert s["rows"][0]["metric_high"] > s["rows"][0]["metric_low"]
    c = post("/api/criticality", {"scenario": "boston_demo"})
    assert c["rows"] and "extra_loss" in c["rows"][0]
    v = post("/api/validation", {})
    assert v["omicron"]["passed"] and v["winter_icu"]["passed"]
