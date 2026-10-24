"""The terminal demos run end to end."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import ROOT


def run(script, *args):
    done = subprocess.run([sys.executable, str(ROOT / "examples" / script), *args],
                          capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_quickstart():
    out = run("quickstart.py")
    assert "R0                       2.8" in out and "res.summary() is plain JSON" in out


def test_fdna_plugin():
    out = run("fdna_plugin.py")
    assert "icu_mortality_multiplier" in out and "the next day" in out


def test_extend_model():
    out = run("extend_model.py")
    for model in ("seir_h (baseline)", "waning", "vaccination", "asymptomatic", "admission delay"):
        assert model in out


def test_calibrate_massachusetts_quick():
    d = json.loads(run("calibrate_massachusetts.py", "--quick", "--json"))
    fit = d["omicron_fit"]
    assert fit["validation"]["passed"]
    assert fit["params"]["disease.r0"] == pytest.approx(1.95, abs=0.02)
    assert fit["params"]["disease.hosp_scale"] == pytest.approx(1.08, abs=0.02)
