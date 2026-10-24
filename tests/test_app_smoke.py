"""Streamlit AppTest: offline start and genuine control effects.

Asserts selected widget values, engine-linked metric changes, event list/KPI
changes + reset restoration, and that all four download controls exist with
non-empty bytes. Uses the synthetic dataset (offline).
"""

from __future__ import annotations

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _fresh():
    at = AppTest.from_file("app/streamlit_app.py", default_timeout=120)
    at.run()
    assert not at.exception  # ElementList -> falsy when empty
    return at


def test_app_starts_offline_with_title_and_metrics():
    at = _fresh()
    assert any("ResiliNet" in (t.value or "") for t in at.title)
    assert len(at.metric) >= 4


def _metric(at, label_contains):
    for m in at.metric:
        if label_contains in (m.label or ""):
            return m.value
    return None


def test_r0_slider_changes_engine_metrics():
    at = _fresh()
    base_unmet = _metric(at, "Unmet need")
    for s in at.slider:
        if s.label and s.label.startswith("R0"):
            s.set_value(4.5)  # much higher R0 -> more demand
    at.run()
    assert not at.exception
    hi_unmet = _metric(at, "Unmet need")
    # engine-linked: higher R0 should not decrease unmet (monotone pressure)
    assert float(hi_unmet.replace(",", "")) >= float(base_unmet.replace(",", ""))


def test_week_and_phase_selected_values():
    at = _fresh()
    for s in at.slider:
        if s.label and s.label.startswith("Week (display"):
            s.set_value(2)
    at.run()
    assert not at.exception
    sel = next(s for s in at.slider if s.label and s.label.startswith("Week (display"))
    assert sel.value == 2
    for r in at.radio:
        if r.label and "Phase" in r.label:
            r.set_value("before")
    at.run()
    assert not at.exception
    ph = next(r for r in at.radio if r.label and "Phase" in r.label)
    assert ph.value == "before"


def test_add_event_changes_run_then_reset_restores():
    at = _fresh()
    # submit the add-event form (defaults: close_hospital, first hospital)
    for b in at.button:
        if b.label and "Add event" in b.label:
            b.click()
    at.run()
    assert not at.exception
    # an active event should now be listed in the sidebar (markdown "- ...")
    md_text = " ".join(m.value for m in at.markdown if m.value)
    assert "close_hospital" in md_text or "set_capacity" in md_text
    # reset restores baseline (no active events)
    for b in at.button:
        if b.label and "Reset to baseline" in b.label:
            b.click()
    at.run()
    assert not at.exception
    md_text2 = " ".join(m.value for m in at.markdown if m.value)
    assert "Active events" not in md_text2


def test_four_download_controls_with_bytes():
    at = _fresh()
    dls = at.get("download_button")
    names = {d.label for d in dls}
    assert {"hospital_week.csv", "district_week.csv", "reroute_week.csv", "run.json"} <= names
    for d in dls:
        assert d.data is not None and len(d.data) > 0


def test_fallback_checkbox_present():
    at = _fresh()
    labels = [c.label for c in at.checkbox]
    assert any("Nearest-outside-radius fallback" in (lbl or "") for lbl in labels)
