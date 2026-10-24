"""Loaders: shipped public data and small synthetic files in each source's format."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from cascade.epi import data
from conftest import DATA


def test_daily_series_combines_rows_and_fills_gaps(tmp_path):
    path = tmp_path / "entries.csv"
    path.write_text("date,station,entries\n2022-01-01,A,10\n2022-01-01,B,5\n2022-01-03,A,30\n")
    s = data.read_daily_series(path, "entries")
    assert s.to_dict() == {pd.Timestamp("2022-01-01"): 15.0, pd.Timestamp("2022-01-02"): 22.5,
                           pd.Timestamp("2022-01-03"): 30.0}
    assert data.read_daily_series(path, "entries", how="mean").iloc[0] == 7.5
    with pytest.raises(KeyError, match="no column"):
        data.read_daily_series(path, "riders")


def test_normalize_mobility():
    days = pd.date_range("2022-01-03", periods=14)               # two full weeks, Monday first
    raw = pd.Series(np.tile([100.0, 100, 100, 100, 100, 50, 50], 2), index=days)
    s = data.normalize_mobility(raw, baseline_dates=(days[0], days[6]))
    assert np.allclose(s, 1.0)                                    # each weekday against its own median
    assert np.allclose(data.normalize_mobility(raw, baseline=50.0)[:2], 2.0)
    pct = data.normalize_mobility(pd.Series([-50.0, 0.0, 20.0], index=days[:3]), percent_change=True)
    assert np.allclose(pct, [0.5, 1.0, 1.2])
    smooth = data.normalize_mobility(pd.Series([1.0, 3.0, 5.0], index=days[:3]), smooth_days=2)
    assert np.allclose(smooth, [1.0, 2.0, 4.0])
    with pytest.raises(ValueError, match="at most one"):
        data.normalize_mobility(raw, baseline=1.0, baseline_dates=(days[0], days[6]))
    with pytest.raises(ValueError, match="every day of the week"):
        data.normalize_mobility(raw, baseline_dates=(days[0], days[3]))


def test_shipped_google_mobility_drops_in_spring_2020():
    s = data.read_daily_series(DATA / "google_mobility_massachusetts.csv", "transit_stations")
    m = data.normalize_mobility(s, percent_change=True)
    assert m.loc["2020-04-15"] < 0.4 and m.loc["2020-02-20"] == pytest.approx(1.0, abs=0.15)


def test_nyt_county_daily_counts():
    df = data.nyt_county(DATA / "nyt_suffolk_county.csv")
    assert list(df.columns) == ["new_cases", "new_deaths"]
    assert (df >= 0).all().all() and df.index.is_monotonic_increasing
    assert (np.diff(df.index) == pd.Timedelta(days=1)).all()
    raw = pd.read_csv(DATA / "nyt_suffolk_county.csv")
    final = raw["cases"].iloc[-1]
    assert final <= df["new_cases"].sum() <= 1.01 * final       # downward corrections dropped, not negative
    with pytest.raises(ValueError, match="no rows"):
        data.nyt_county(DATA / "nyt_suffolk_county.csv", county="Nowhere")


def test_hhs_state_admissions_and_weeks():
    s = data.hhs_state_admissions(DATA / "hhs_ma_daily_admissions.csv")
    assert s.name == "new_hosp" and (np.diff(s.index) == pd.Timedelta(days=1)).all()
    wk = data.weekly(s)
    assert (wk.index.day_of_week == 5).all()                       # MMWR weeks end on Saturday
    assert wk.loc["2022-01-15"] == pytest.approx(s.loc["2022-01-09":"2022-01-15"].sum())
    assert 2500 < wk.loc["2022-01-15"] < 3500                   # the Omicron peak week
    with pytest.raises(ValueError, match="no rows"):
        data.hhs_state_admissions(DATA / "hhs_ma_daily_admissions.csv", location="99")


def test_ctp_census():
    df = data.ctp_state(DATA / "ctp_ma_hospital_census.csv")
    assert list(df.columns) == ["hospitalizedCurrently", "inIcuCurrently"]
    assert df.loc["2020-09-13", "hospitalizedCurrently"] == 313 and df.loc["2020-09-13", "inIcuCurrently"] == 61
    assert df.index[-1] == pd.Timestamp("2021-03-07")


def test_hhs_facility_weekly(tmp_path):
    cols = data.HHS_ADMISSIONS
    rows = [
        ("2022-01-07", "220071", 50, 2),
        ("2022-01-07", "220077", -999999, 0),        # suppressed (1-3 patients)
        ("2022-01-14", "220071", 40, 1),
        ("2022-01-14", "220077", None, None),        # did not report
    ]
    df = pd.DataFrame(rows, columns=["collection_week", "ccn", *cols])
    path = tmp_path / "facility.csv"
    df.to_csv(path, index=False)
    out = data.hhs_facility_weekly(path)
    assert out.loc["2022-01-07"] == 52 and out.loc["2022-01-14"] == 41
    assert data.hhs_facility_weekly(path, suppressed=2.0).loc["2022-01-07"] == 54
    assert data.hhs_facility_weekly(path, ccns=["220077"], suppressed=2.0).loc["2022-01-07"] == 2
    gaps = data.hhs_facility_weekly(path, min_reporting=0.75)
    assert gaps.loc["2022-01-07"] == 52 and np.isnan(gaps.loc["2022-01-14"])
    with pytest.raises(ValueError, match="none of the requested"):
        data.hhs_facility_weekly(path, ccns=["000000"])
    with pytest.raises(KeyError, match="missing columns"):
        data.hhs_facility_weekly(path, columns=("no_such_column",))


def test_places_multiplier():
    m = data.places_comorbidity_multiplier(DATA / "places_ma_counties_2023.csv", "Suffolk")
    assert 0.8 < m < 1.2
    assert data.places_comorbidity_multiplier(DATA / "places_ma_counties_2023.csv", "Suffolk",
                                              elasticity=0.0) == 1.0
    with pytest.raises(ValueError, match="not in"):
        data.places_comorbidity_multiplier(DATA / "places_ma_counties_2023.csv", "Atlantis")


def test_population_from_csv(tmp_path):
    path = tmp_path / "pop.csv"
    path.write_text("patch,0-17,18-64,65+\nDorchester,28000,80000,15000\nRoxbury,12000,36000,6000\n")
    pop = data.population_from_csv(path)
    assert pop.patches == ["Dorchester", "Roxbury"] and pop.ages == ["0-17", "18-64", "65+"]
    assert pop.N.shape == (2, 3) and pop.N[1, 1] == 36000
    with pytest.raises(KeyError):
        data.population_from_csv(path, patch_column="neighbourhood")


def test_contact_csv_errors(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("age,population,young,old\nyoung,10,1,2\nold,10,2,1\n")
    with pytest.raises(ValueError, match="cannot read an age"):
        data.age_contacts_from_csv(bad, [0, 18])
    C = data.age_contacts_from_csv(DATA / "prem2021_usa_contacts_all.csv", [0, 18, 65])
    assert C.shape == (3, 3) and (C > 0).all()


def test_contact_multiplier_from_config_values_and_csv():
    from cascade.epi.config import ContactMultiplier

    vals = data.contact_multiplier_series(ContactMultiplier(values=[1.0, 0.8, 0.6], smooth_days=1))
    assert isinstance(vals, np.ndarray) and np.allclose(vals, [1.0, 0.8, 0.6])
    dated = data.contact_multiplier_series(ContactMultiplier(
        csv=str(DATA / "google_mobility_massachusetts.csv"), column="transit_stations", percent_change=True,
        baseline_dates=[date(2021, 11, 14), date(2021, 11, 27)]))
    assert isinstance(dated, pd.Series)
    assert dated.loc["2021-11-14":"2021-11-27"].median() == pytest.approx(1.0, abs=0.02)
