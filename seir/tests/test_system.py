"""System tests: data ingestion, FDNA maths, the coupled loop, and the module boundaries."""
import ast
from pathlib import Path

import numpy as np
import pytest

from cascade import api
from cascade.data import build_from_project
from cascade.fdna import Edge, Event, FDNAGraph
from cascade.reroute import GreedyAssigner

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "systems" / "boston_demo.yaml"
HEALTHCARE = ROOT.parent / "healthcare"      # the project's dataset folder


@pytest.fixture(scope="module")
def cfg():
    return api.load(DEMO)


@pytest.fixture(scope="module")
def base(cfg):
    return api.run(cfg)


@pytest.mark.skipif(not HEALTHCARE.exists(), reason="project datasets not next to the package")
def test_ingest_joins_project_files():
    df = build_from_project(HEALTHCARE, ROOT / "data" / "crosswalk" / "hospitals.csv")
    row = df.set_index("id")
    assert row.loc["MGH", "icu_beds"] == 101 and row.loc["MGH", "ccn"] == "220071"
    assert row.loc["BIDMC", "campuses"] == 2 and row.loc["BIDMC", "icu_beds"] == 95  # East + West
    assert not row.loc["NEBH", "er"]


def test_fdna_formula_matches_hand_calculation():
    g = FDNAGraph(["a", "b", "h"], [Edge("a", "h", sod=0.8, cod=30), Edge("b", "h", sod=0.5)])
    P = dict(zip(g.nodes, g.evaluate({"a": 50.0, "b": 100.0})))
    sodp = ((0.8 * 50 + 20) + (0.5 * 100 + 50)) / 2          # 80
    assert P["h"] == pytest.approx(min(sodp, 50 + 30))        # COD caps at 80 too
    P = dict(zip(g.nodes, g.evaluate({"a": 10.0, "b": 100.0})))
    assert P["h"] == pytest.approx(40.0)                      # critical feeder caps: 10 + 30


def test_fdna_rejects_cycles():
    with pytest.raises(ValueError, match="acyclic"):
        FDNAGraph(["a", "b"], [Edge("a", "b", 0.5), Edge("b", "a", 0.5)])


def test_every_admission_lands_somewhere(base):
    s = base.system
    np.testing.assert_allclose(s.arrivals.sum("hospital"), s.new_hosp.sum("patch"), rtol=1e-9)


def test_assigner_moves_patients_to_nearest_open_hospital():
    intended = np.array([[10.0, 5.0, 0.0]])
    final, diverted, overflow = GreedyAssigner()(
        intended, closed=np.array([True, False, False]),
        travel=np.array([[5.0, 20.0, 10.0]]), free=np.array([0.0, 100.0, 4.0]))
    assert diverted == 10.0 and final[0, 0] == 0.0
    assert final[0, 2] == 4.0 and final[0, 1] == 11.0 and overflow == 0.0


def test_strain_cascades_through_diversion(base):
    s = base.system
    assert s.on_diversion.any("time").all()          # every hospital diverts at some point
    first = s.on_diversion.argmax("time").values
    assert first.min() < first.max()                  # ...but not all on the same day
    assert float(s.diverted_patients.sum()) > 0
    assert (s.on_diversion.sum("hospital") < s.sizes["hospital"]).all()   # min_open holds


def test_staff_knockout_degrades_hospital_and_loads_neighbours(cfg, base):
    knocked = cfg.model_copy(update={"events": [Event(node="BMC.staff", value=20, start=30)]})
    res = api.run(knocked)
    bmc = list(cfg.network.hospitals).index(next(h for h in cfg.network.hospitals if h.id == "BMC"))
    assert float(res.system.operability.isel(hospital=bmc)[40]) < float(base.system.operability.isel(hospital=bmc)[40])
    others = [i for i in range(len(cfg.network.hospitals)) if i != bmc]
    assert float(res.system.arrivals.isel(hospital=others).sum()) > float(base.system.arrivals.isel(hospital=others).sum())
    assert res.summary()["weighted_access_loss"] > base.summary()["weighted_access_loss"]


def test_fdna_feedback_reaches_seir(cfg, base):
    no_feedback = api.run(cfg.model_copy(update={"feedback_to_seir": False}))
    assert base.summary()["deaths"] > no_feedback.summary()["deaths"]


def test_criticality_ranks_nodes(cfg):
    df = api.criticality(cfg, days=120, nodes=["BMC.staff", "MGH.staff", "TUFTS.ward"])
    assert list(df.columns) == ["node", "loss", "extra_loss"]
    assert df.extra_loss.is_monotonic_decreasing and (df.extra_loss > 0).all()


def test_runs_are_reproducible(cfg, base):
    again = api.run(cfg)
    assert base.system.identical(again.system)


def test_layers_only_import_contracts():
    """FDNA, allocation, rerouting and equity never import the SEIR engine or each other's modules."""
    allowed = {"cascade.core", "cascade.contracts", "cascade.network", "cascade.reroute"}
    for path in [*(ROOT / "cascade" / "fdna").glob("*.py"), ROOT / "cascade" / "allocation.py",
                 ROOT / "cascade" / "reroute.py", ROOT / "cascade" / "equity.py"]:
        pkg = "cascade.fdna" if path.parent.name == "fdna" else "cascade"
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                base_pkg = pkg.rsplit(".", node.level - 1)[0] if node.level > 1 else pkg
                mod = f"{base_pkg}.{node.module}" if node.module else base_pkg
                if mod.startswith("cascade.fdna") and pkg == "cascade.fdna":
                    continue
                assert mod in allowed, f"{path.name} imports {mod}"
