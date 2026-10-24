"""Loaders that turn public datasets into the series and inputs the SEIR layer uses.

This is the only module that knows raw column names. Each loader returns a
plain pandas object indexed by date (or a number), so a source can change
format without touching the model.

  read_daily_series      any dated CSV -> complete daily series (MBTA, mobility)
  normalize_mobility     raw mobility -> contact multiplier around 1.0
  nyt_county             NYT us-counties cumulative counts -> daily cases, deaths
  hhs_state_admissions   HHS daily COVID admissions per state (Forecast Hub truth format)
  hhs_facility_weekly    HHS facility-level weekly file -> sum over chosen hospitals
  ctp_state              COVID Tracking Project daily state file (census to Mar 2021)
  places_comorbidity_multiplier   CDC PLACES county risk factors -> hosp_scale
  population_from_csv    a patch x age table -> Population
  age_contacts_from_csv  a fine age contact matrix (Prem 2021) -> your age bands
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .config import ContactMultiplier, Population
from .mixing import aggregate_contacts, reciprocal_contacts

PathLike = str | Path


# ---- generic daily series ----------------------------------------------------
def read_daily_series(path: PathLike, column: str, date_column: str = "date",
                      how: str = "sum") -> pd.Series:
    """One value per calendar day from a dated CSV.

    Rows that share a date (e.g. one row per MBTA station) are combined with
    `how` ("sum" or "mean"). Missing days inside the range are filled by
    linear interpolation, so the result has no gaps.
    """
    df = pd.read_csv(path)
    for col in (date_column, column):
        if col not in df.columns:
            raise KeyError(f"{path}: no column {col!r}; columns are {list(df.columns)}")
    dates = pd.to_datetime(df[date_column], format="mixed")
    values = pd.to_numeric(df[column], errors="coerce")
    s = values.groupby(dates.dt.normalize()).agg(how).sort_index()
    if s.empty:
        raise ValueError(f"{path}: no rows with a date and a value in {column!r}")
    full = pd.date_range(s.index[0], s.index[-1], freq="D")
    s = s.reindex(full).interpolate(method="time", limit_area="inside")
    s.index.name = "date"
    return s.rename(column)


def normalize_mobility(raw: pd.Series, baseline: float | None = None,
                       baseline_dates: tuple[date, date] | None = None,
                       percent_change: bool = False, smooth_days: int = 1) -> pd.Series:
    """Raw mobility -> multiplier where 1.0 means normal contacts.

    percent_change: raw values are % change from normal (Google mobility
                    reports); they become 1 + raw / 100 before anything else
    baseline:       divide by this number
    baseline_dates: divide each day by the median of the same weekday within
                    [start, end] (Google's method; good for MBTA entries, or to
                    rebase a percent-change series to the weeks before a fit)
    smooth_days:    trailing mean over this many days, applied last
    """
    if baseline is not None and baseline_dates is not None:
        raise ValueError("give at most one of baseline and baseline_dates")
    s = raw.astype(float)
    if percent_change:
        s = 1.0 + s / 100.0
    if baseline is not None:
        s = s / baseline
    elif baseline_dates is not None:
        start, end = pd.Timestamp(baseline_dates[0]), pd.Timestamp(baseline_dates[1])
        window = s[(s.index >= start) & (s.index <= end)]
        ref = window.groupby(window.index.day_of_week).median()
        if len(ref) < 7:
            raise ValueError("baseline_dates must cover every day of the week")
        if (ref <= 0).any():
            raise ValueError("baseline window has zero or negative values")
        s = s / ref.reindex(s.index.day_of_week).to_numpy()
    if smooth_days > 1:
        s = s.rolling(smooth_days, min_periods=1).mean()
    return s.rename("contact_multiplier")


def contact_multiplier_series(cm: ContactMultiplier) -> pd.Series | np.ndarray:
    """The contact multiplier a ContactMultiplier config describes, before elasticity.

    A dated pd.Series for a csv source; a plain array (day 0 = sim.start) for
    a values source. Step sources are handled by rates.Piecewise directly.
    """
    if cm.steps is not None:
        raise ValueError("steps are not a daily series")
    if cm.csv is not None:
        raw = read_daily_series(cm.csv, cm.column, cm.date_column)
    else:
        raw = pd.Series(np.asarray(cm.values, dtype=float))
    out = normalize_mobility(raw, cm.baseline, cm.baseline_dates, cm.percent_change, cm.smooth_days)
    if out.isna().any():
        raise ValueError("contact multiplier has missing values after normalising")
    return out if cm.csv is not None else out.to_numpy()


# ---- epidemic and hospital data ------------------------------------------------
def nyt_county(paths: PathLike | Iterable[PathLike], county: str = "Suffolk",
               state: str = "Massachusetts") -> pd.DataFrame:
    """Daily new cases and deaths for one county from NYT us-counties CSVs.

    NYT publishes cumulative counts (one file per year in their repository).
    Daily counts are the day-to-day differences; downward corrections are set
    to 0 rather than kept as negative days. Data: The New York Times,
    github.com/nytimes/covid-19-data, CC BY-NC 4.0.
    """
    paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
    df = pd.concat([pd.read_csv(p, dtype={"fips": str}) for p in paths], ignore_index=True)
    df = df[(df["county"] == county) & (df["state"] == state)]
    if df.empty:
        raise ValueError(f"no rows for {county}, {state}")
    df = df.assign(date=pd.to_datetime(df["date"])).drop_duplicates("date", keep="last")
    cum = df.set_index("date").sort_index()[["cases", "deaths"]].astype(float)
    cum = cum.reindex(pd.date_range(cum.index[0], cum.index[-1], freq="D")).ffill()
    daily = cum.diff().fillna(cum.iloc[[0]]).clip(lower=0)
    daily.index.name = "date"
    return daily.rename(columns={"cases": "new_cases", "deaths": "new_deaths"})


def hhs_state_admissions(path: PathLike, location: str = "25") -> pd.Series:
    """Daily new COVID hospital admissions (confirmed) for one state.

    Reads the COVID-19 Forecast Hub truth file built from HHS Protect
    ("date,location,location_name,value"); location is the state FIPS code
    ("25" is Massachusetts).
    """
    df = pd.read_csv(path, dtype={"location": str})
    df = df[df["location"] == str(location)]
    if df.empty:
        raise ValueError(f"no rows for location {location}")
    s = df.assign(date=pd.to_datetime(df["date"])).groupby("date")["value"].sum().sort_index()
    s = s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D"))
    s.index.name = "date"
    return s.astype(float).rename("new_hosp")


# Columns of the HHS "COVID-19 Reported Patient Impact and Hospital Capacity by
# Facility" file (healthdata.gov anag-cw7u) that the calibration uses.
HHS_ADMISSIONS = ("previous_day_admission_adult_covid_confirmed_7_day_sum",
                  "previous_day_admission_pediatric_covid_confirmed_7_day_sum")
HHS_INPATIENTS = ("total_adult_patients_hospitalized_confirmed_and_suspected_covid_7_day_avg",
                  "total_pediatric_patients_hospitalized_confirmed_and_suspected_covid_7_day_avg")
HHS_ICU = ("staffed_icu_adult_patients_confirmed_and_suspected_covid_7_day_avg",)


def hhs_facility_weekly(path: PathLike, columns: Sequence[str] = HHS_ADMISSIONS,
                        ccns: Iterable[str] | None = None, suppressed: float = np.nan,
                        min_reporting: float = 0.0) -> pd.Series:
    """Weekly totals over a set of hospitals from the HHS facility-level file.

    Values 1-3 are suppressed in the file as -999999; `suppressed` says what
    to use instead (NaN drops them; 2.0 is the midpoint). Selected columns are
    added per facility, then facilities are added per collection week
    (labelled by its first day, a Friday). Weeks where fewer than
    `min_reporting` of the chosen hospitals reported anything become NaN.
    """
    df = pd.read_csv(path, dtype={"ccn": str, "hospital_pk": str}, low_memory=False)
    missing = [c for c in ("collection_week", *columns) if c not in df.columns]
    if missing:
        raise KeyError(f"{path}: missing columns {missing}")
    if ccns is not None:
        key = "ccn" if "ccn" in df.columns else "hospital_pk"
        wanted = {str(c) for c in ccns}
        df = df[df[key].astype(str).isin(wanted)]
        if df.empty:
            raise ValueError("none of the requested hospitals are in the file")
    vals = df[list(columns)].apply(pd.to_numeric, errors="coerce")
    vals = vals.mask(vals == -999999, suppressed)
    week = pd.to_datetime(df["collection_week"], format="mixed").dt.normalize()
    per_row = vals.sum(axis=1, min_count=1)
    weekly = per_row.groupby(week).sum(min_count=1).sort_index()
    if min_reporting > 0:
        reporting = per_row.notna().groupby(week).sum() / df.groupby(week).size()
        weekly = weekly.where(reporting >= min_reporting)
    weekly.index.name = "week_start"
    return weekly.astype(float).rename("+".join(columns) if len(columns) > 1 else columns[0])


def ctp_state(path: PathLike, state: str = "MA",
              columns: Sequence[str] = ("hospitalizedCurrently", "inIcuCurrently")) -> pd.DataFrame:
    """Daily state series from the COVID Tracking Project (ends 7 March 2021).

    hospitalizedCurrently and inIcuCurrently are COVID inpatients and ICU
    patients on each day: the census that SEIR's H + C and C compartments
    model. Data: The COVID Tracking Project at The Atlantic, CC BY 4.0.
    """
    df = pd.read_csv(path, usecols=["date", "state", *columns])
    df = df[df["state"] == state]
    if df.empty:
        raise ValueError(f"no rows for state {state}")
    out = df.assign(date=pd.to_datetime(df["date"].astype(str), format="mixed")).set_index("date")
    out = out.sort_index()[list(columns)].astype(float)
    return out.reindex(pd.date_range(out.index[0], out.index[-1], freq="D"))


# ---- population and risk -------------------------------------------------------
# CDC PLACES measures that raise the risk of severe COVID-19 among adults.
RISK_MEASURES = ("Diagnosed diabetes among adults", "Obesity among adults",
                 "Current cigarette smoking among adults")


def places_comorbidity_multiplier(path: PathLike, county: str,
                                  measures: Sequence[str] = RISK_MEASURES,
                                  elasticity: float = 0.5) -> float:
    """A hospitalisation multiplier for one county from CDC PLACES prevalence.

    For each risk factor, compare the county's prevalence with the
    population-weighted average of all counties in the file, then average
    the ratios: multiplier = 1 + elasticity * (mean ratio - 1). elasticity
    is an assumption (0.5 means a county with 20% more risk factors has 10%
    more hospitalisations per infection). Use it as disease.hosp_scale.
    """
    df = pd.read_csv(path)
    for col in ("county", "measure", "prevalence", "population"):
        if col not in df.columns:
            raise KeyError(f"{path}: no column {col!r}")
    df = df[df["measure"].isin(measures)]
    if county not in set(df["county"]):
        raise ValueError(f"county {county!r} not in {path}")
    ratios = []
    for m in measures:
        rows = df[df["measure"] == m]
        if rows.empty:
            raise ValueError(f"measure {m!r} not in {path}")
        mean = np.average(rows["prevalence"], weights=rows["population"])
        ratios.append(float(rows.loc[rows["county"] == county, "prevalence"].iloc[0]) / mean)
    return float(1.0 + elasticity * (np.mean(ratios) - 1.0))


def population_from_csv(path: PathLike, patch_column: str = "patch",
                        age_columns: Sequence[str] | None = None) -> Population:
    """Population from a table with one row per patch and one column per age group.

    For example Census ACS counts aggregated to neighborhoods:
        patch,0-17,18-64,65+
        Dorchester,28000,80000,15000
    Age columns default to every column except the patch column, in order.
    """
    df = pd.read_csv(path)
    if patch_column not in df.columns:
        raise KeyError(f"{path}: no column {patch_column!r}")
    ages = list(age_columns) if age_columns is not None else [c for c in df.columns if c != patch_column]
    return Population(patches=df[patch_column].astype(str).tolist(), ages=[str(a) for a in ages],
                      counts=df[ages].astype(float).to_numpy().tolist())


def _age_start(label: str) -> float:
    """"0-4" -> 0, "75+" -> 75, "65" -> 65."""
    head = str(label).strip().split("-")[0].rstrip("+").strip()
    try:
        return float(head)
    except ValueError:
        raise ValueError(f"cannot read an age from {label!r}; use labels like 0-4 or 75+") from None


def age_contacts_from_csv(path: PathLike, band_starts: Sequence[float],
                          population: Sequence[float] | None = None,
                          last_width: float = 5.0) -> np.ndarray:
    """Age contact matrix for your age bands from a fine-grained one.

    The CSV has one row per fine age group: an "age" label ("0-4", ..., "75+"),
    a "population" column (people per group, used to weight the groups inside
    a band) and one contact column per group in the same order, e.g.
    data/prem2021_usa_contacts_all.csv (Prem et al. 2021, United States, all
    settings). band_starts are the lower edges of your bands, [0, 18, 65] for
    the project's three. With `population` (people per band, e.g. the
    scenario's age totals) the result is made reciprocal for that
    population, which is what the scenario should use.
    """
    df = pd.read_csv(path)
    if "age" not in df.columns:
        raise KeyError(f"{path}: no column 'age'")
    pop_cols = [c for c in df.columns if str(c).startswith("population")]
    if len(pop_cols) != 1:
        raise KeyError(f"{path}: needs exactly one population column")
    labels = df["age"].astype(str).tolist()
    missing = [a for a in labels if a not in df.columns]
    if missing:
        raise KeyError(f"{path}: no contact columns for age groups {missing}")
    M = df[labels].to_numpy(dtype=float)
    starts = [_age_start(a) for a in labels]
    C = aggregate_contacts(M, df[pop_cols[0]].to_numpy(dtype=float), starts, band_starts, last_width)
    return C if population is None else reciprocal_contacts(C, population)


def weekly(series: pd.Series, freq: str = "W-SAT", how: str = "sum") -> pd.Series:
    """Daily series -> weekly. W-SAT gives MMWR epidemiological weeks (Sunday to Saturday)."""
    return series.resample(freq).agg(how)
