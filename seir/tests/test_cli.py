"""The terminal interface: every command, --set, --json and clean errors."""
from __future__ import annotations

import json
import subprocess
import sys

import pandas as pd
import pytest

from cascade.epi import ScenarioConfig, simulate
from cascade.epi.cli import main
from conftest import DATA, ROOT, SCENARIOS

EXAMPLE = str(SCENARIOS / "example_3patch.yaml")


def run_json(capsys, *argv):
    main([*argv, "--json"])
    return json.loads(capsys.readouterr().out)


def test_presets(capsys):
    main(["presets"])
    out = capsys.readouterr().out
    assert "covid_omicron" in out and "doi.org" in out
    d = run_json(capsys, "presets")
    assert set(d) == {"presets", "sources"} and "measles" in d["presets"]


def test_info(capsys):
    main(["info", EXAMPLE])
    out = capsys.readouterr().out
    assert "R0 2.80" in out and "doubling every" in out and "E -> I" in out
    d = run_json(capsys, "info", EXAMPLE, "--set", "disease.r0=1.5")
    assert d["engine"]["r0"] == pytest.approx(1.5) and d["beta0"] > 0


def test_run_text_and_files(capsys, tmp_path):
    out_csv = tmp_path / "run.csv"
    main(["run", EXAMPLE, "--days", "60", "--weekly", "--out", str(out_csv)])
    out = capsys.readouterr().out
    for text in ("new infections", "inpatients", "By patch", "Dorchester", "By week", "Saved"):
        assert text in out
    assert len(pd.read_csv(out_csv)) == 60 * 3


def test_run_json_matches_the_library(capsys):
    d = run_json(capsys, "run", EXAMPLE, "--set", "disease.r0=2.0", "--set", "sim.days=90")
    cfg = ScenarioConfig.from_yaml(EXAMPLE).updated({"disease.r0": 2.0, "sim.days": 90})
    assert d["summary"]["admissions"] == pytest.approx(simulate(cfg).summary()["admissions"])
    assert [r["patch"] for r in d["by_patch"]] == ["Dorchester", "Roxbury", "Back Bay"]
    stoch = run_json(capsys, "run", EXAMPLE, "--stochastic", "--seed", "3", "--days", "30")
    assert stoch["engine"]["stochastic"] is True


def test_run_with_feedback_and_structure(capsys):
    d = run_json(capsys, "run", EXAMPLE, "--days", "20", "--feedback", "icu_mortality_multiplier")
    assert "p_death_icu" in d["engine"]["rates"]
    d = run_json(capsys, "run", EXAMPLE, "--days", "20", "--structure", "seir")
    assert d["engine"]["compartments"] == ["S", "E", "I", "R"] and "admissions" not in d["summary"]


def test_ensemble(capsys):
    d = run_json(capsys, "ensemble", EXAMPLE, "--runs", "3", "--days", "40")
    assert d["runs"] == 3 and 0 <= d["takeoff_share"] <= 1 and d["weekly"]["new_hosp"]
    main(["ensemble", EXAMPLE, "--runs", "3", "--days", "40"])
    assert "Weekly admissions" in capsys.readouterr().out


def test_sensitivity(capsys):
    rows = run_json(capsys, "sensitivity", EXAMPLE, "--params", "disease.r0", "disease.los_ward",
                    "--days", "60", "--metric", "admissions")
    assert {r["parameter"] for r in rows} == {"disease.r0", "disease.los_ward"}
    main(["sensitivity", EXAMPLE, "--params", "disease.r0", "--days", "30"])
    assert "#" in capsys.readouterr().out


@pytest.fixture(scope="module")
def observed_csv(tmp_path_factory):
    cfg = ScenarioConfig.from_yaml(EXAMPLE).updated({"disease.r0": 2.2})
    weekly = simulate(cfg).weekly("new_hosp")
    path = tmp_path_factory.mktemp("obs") / "weekly.csv"
    pd.DataFrame({"date": weekly.index.date, "value": weekly.to_numpy()}).to_csv(path, index=False)
    return path


def test_calibrate_fits_and_writes(capsys, observed_csv, tmp_path):
    out_yaml = tmp_path / "fitted.yaml"
    d = run_json(capsys, "calibrate", EXAMPLE, "--observed", str(observed_csv),
                 "--fit", "disease.r0=3:1.2:5", "--write", str(out_yaml))
    assert d["params"]["disease.r0"] == pytest.approx(2.2, rel=1e-3) and d["validation"]["passed"]
    assert ScenarioConfig.from_yaml(out_yaml).disease.r0 == pytest.approx(2.2, rel=1e-3)
    main(["calibrate", EXAMPLE, "--observed", str(observed_csv), "--fit", "disease.r0=3:1.2:5",
          "--split", "2022-01-15"])
    out = capsys.readouterr().out
    assert "fit up to 2022-01-15" in out and "PASS  overall" in out


def test_calibrate_reads_daily_files_by_location(capsys):
    d = run_json(capsys, "calibrate", str(SCENARIOS / "omicron_2021.yaml"), "--observed",
                 str(DATA / "hhs_ma_daily_admissions.csv"), "--filter", "location=25", "--weekly",
                 "--start", "2021-12-19", "--end", "2022-03-05", "--fit", "disease.r0=1.95:1.2:4")
    assert len(d["series"]) == 11 and d["validation"]["passed"]
    assert d["params"]["disease.r0"] == pytest.approx(1.95, abs=0.03)


def test_errors_exit_cleanly(capsys):
    with pytest.raises(SystemExit) as e:
        main(["run", "missing.yaml"])
    assert e.value.code == 2 and "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        main(["run", EXAMPLE, "--set", "disease.r0=-1"])
    assert e.value.code == 2
    assert capsys.readouterr().err.strip() == "error: disease.r0: Input should be greater than 0"
    with pytest.raises(SystemExit, match="path=value"):
        main(["run", EXAMPLE, "--set", "disease.r0"])
    with pytest.raises(SystemExit, match="initial:low:high"):
        main(["calibrate", EXAMPLE, "--observed", "x.csv", "--fit", "disease.r0=2"])


def test_module_entry_point():
    out = subprocess.run([sys.executable, "-m", "cascade.epi", "info", EXAMPLE, "--json"],
                         capture_output=True, text=True, cwd=ROOT, check=True).stdout
    assert json.loads(out)["engine"]["r0"] == pytest.approx(2.8)
