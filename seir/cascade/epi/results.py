"""Run output as a labelled xarray Dataset with dims (time, patch, age).

Every variable carries attrs["kind"]: "compartment" (people at the end of the
day), "flow" (people who moved during the day) or "rate" (the day-averaged
rates in effect, plus r_eff). The people-facing rates are renamed:

    beta -> transmission_rate    sigma -> incubation_rate
    gamma -> recovery_rate       foi -> force_of_infection

Other rates (p_hosp, ward_exit, ...) keep their own names. A rate that is the
same everywhere is stored per day; one that varies by patch or age per cell.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from .config import Population
from .structure import ModelStructure

# Output names for the rates people ask about; other rates keep their own names.
RATE_NAMES = {
    "beta": "transmission_rate",
    "sigma": "incubation_rate",
    "gamma": "recovery_rate",
    "foi": "force_of_infection",
}
RATE_UNITS = "per day"
# Rates that are shares of people rather than per-day rates.
SHARES = {"p_hosp", "p_icu", "p_death_icu", "p_asym", "vax_efficacy"}
DESCRIPTIONS = {
    "transmission_rate": "beta(t): beta0 times the contact multiplier",
    "incubation_rate": "sigma: share of the exposed who become infectious per day (1 / latent period)",
    "recovery_rate": "gamma: rate of leaving I, to R or to hospital (1 / infectious period)",
    "force_of_infection": "per-capita rate at which susceptibles are infected",
    "p_hosp": "share of infections that are hospitalised",
    "p_icu": "share of ward patients who move to ICU",
    "p_death_icu": "share of ICU patients who die",
    "ward_exit": "rate of leaving the ward (1 / ward length of stay)",
    "icu_exit": "rate of leaving ICU (1 / ICU length of stay)",
    "r_eff": "effective reproduction number at the end of the day",
}


class SEIRResult:
    def __init__(self, ds: xr.Dataset, initial: xr.Dataset, structure: ModelStructure):
        self.ds = ds
        self.initial = initial
        self.structure = structure

    @classmethod
    def from_records(cls, records, X0: np.ndarray, structure: ModelStructure,
                     population: Population) -> "SEIRResult":
        if not records:
            raise ValueError("no days to collect: run at least one day")
        time = pd.DatetimeIndex([r.date for r in records], name="time")
        coords = {"time": time, "patch": population.patches, "age": population.ages}
        cell = ("time", "patch", "age")
        shape = population.N.shape
        data = {}
        for c in structure.compartments:
            data[c] = (cell, np.stack([r.compartments[c] for r in records]),
                       {"kind": "compartment", "units": "people"})
        for f in structure.flows:
            data[f] = (cell, np.stack([r.flows[f] for r in records]),
                       {"kind": "flow", "units": "people per day"})
        for name in records[0].rates:
            values = [r.rates[name] for r in records]
            out = RATE_NAMES.get(name, name)
            attrs = {"kind": "rate", "units": "share" if name in SHARES else RATE_UNITS,
                     "source_name": name}
            if out in DESCRIPTIONS:
                attrs["description"] = DESCRIPTIONS[out]
            if all(np.ndim(v) == 0 for v in values):
                data[out] = (("time",), np.asarray(values, dtype=float), attrs)
            else:
                data[out] = (cell, np.stack([np.broadcast_to(v, shape) for v in values]), attrs)
        data["r_eff"] = (("time",), np.array([r.r_eff for r in records]),
                         {"kind": "rate", "units": "secondary infections per infection",
                          "description": DESCRIPTIONS["r_eff"]})
        ds = xr.Dataset(data, coords=coords)
        ds = ds.assign_coords(population=(("patch", "age"), population.N))
        initial = xr.Dataset(
            {c: (("patch", "age"), X0[i]) for i, c in enumerate(structure.compartments)},
            coords={"patch": population.patches, "age": population.ages},
        )
        return cls(ds, initial, structure)

    # ---- views ---------------------------------------------------------
    def _of_kind(self, kind: str) -> xr.Dataset:
        return self.ds[[v for v in self.ds.data_vars if self.ds[v].attrs.get("kind") == kind]]

    @property
    def compartments(self) -> xr.Dataset:
        return self._of_kind("compartment")

    @property
    def flows(self) -> xr.Dataset:
        return self._of_kind("flow")

    @property
    def rates(self) -> xr.Dataset:
        return self._of_kind("rate")

    @property
    def population(self) -> xr.DataArray:
        return self.ds["population"]

    def counts_by_patch(self) -> xr.Dataset:
        return xr.merge([self.compartments, self.flows]).sum("age")

    def citywide(self) -> xr.Dataset:
        return xr.merge([self.compartments, self.flows]).sum(["patch", "age"])

    def _start_of_day(self, src: str) -> xr.DataArray:
        """Compartment `src` at the start of each day (the previous day's end)."""
        return xr.concat([self.initial[src].expand_dims(time=[self.ds.time.values[0]]),
                          self.ds[src].isel(time=slice(None, -1)).assign_coords(time=self.ds.time[1:])],
                         dim="time")

    def observed_rate(self, src: str, flow: str, method: str = "start") -> xr.DataArray:
        """Realised per-day rate of `flow` out of `src`, e.g. ("E", "new_infectious") for sigma.

        method="average": flow over the day's average count, which estimates
        the rate itself and is what to compare with incubation_rate or
        recovery_rate. method="start": flow over the start-of-day count, a
        daily probability for the people present at the start of the day
        (people who arrive and leave on the same day push it up).
        """
        start = self._start_of_day(src)
        if method == "start":
            base = start
        elif method == "average":
            base = (start + self.ds[src]) / 2
        else:
            raise ValueError("method must be 'start' or 'average'")
        return (self.ds[flow] / base.where(base > 0)).rename(f"observed_{flow}_rate")

    def observed_rates(self, method: str = "average") -> xr.Dataset:
        """observed_rate for every transition, citywide (patches and ages pooled)."""
        out = {}
        for t in self.structure.transitions:
            start = self._start_of_day(t.src).sum(["patch", "age"])
            end = self.ds[t.src].sum(["patch", "age"])
            base = start if method == "start" else (start + end) / 2
            out[t.flow] = self.ds[t.flow].sum(["patch", "age"]) / base.where(base > 0)
        return xr.Dataset(out)

    def infections(self) -> xr.DataArray:
        """New infections per day: every flow into the exposed compartment from outside the infection path."""
        path = set(self.structure.infection_path)
        names = [t.flow for t in self.structure.transitions
                 if t.dst == self.structure.exposed and t.src not in path]
        return sum(self.ds[n] for n in names).rename("new_infections")

    def inpatients(self) -> xr.DataArray:
        """COVID inpatients (ward + ICU census) per day and patch, ages summed."""
        present = [c for c in ("H", "C") if c in self.ds]
        if not present:
            raise KeyError("this structure has no hospital compartments (H, C)")
        return sum(self.ds[c] for c in present).sum("age").rename("inpatients")

    def series(self, name: str, patches=None) -> pd.Series:
        """One daily series summed over ages and (selected) patches, e.g. series("new_hosp").

        Besides any variable in ds, accepts "inpatients" (H + C), "icu" (C),
        "infections" and "infectious" (all transmitting compartments).
        """
        if name == "inpatients":
            da = self.inpatients()
        elif name == "icu":
            da = self.ds["C"].sum("age")
        elif name == "infections":
            da = self.infections().sum("age")
        elif name == "infectious":
            da = sum(self.ds[c] for c in self.structure.infectious).sum("age")
        elif name in self.ds and self.ds[name].attrs.get("kind") != "rate":
            da = self.ds[name].sum("age")
        else:
            raise KeyError(f"no count series {name!r}; rates live in ds")
        if patches is not None:
            da = da.sel(patch=list(patches))
        return da.sum("patch").to_series().rename(name)

    def weekly(self, name: str, freq: str = "W-SAT", how: str | None = None,
               complete: bool = True) -> pd.Series:
        """series(name) by week. Flows are summed, counts averaged, unless `how` says otherwise.

        W-SAT gives MMWR weeks (Sunday to Saturday). With complete=True,
        partial weeks at either end are dropped.
        """
        s = self.series(name)
        kind = self.ds[name].attrs.get("kind") if name in self.ds else None
        how = how or ("sum" if kind == "flow" or name == "infections" else "mean")
        grouped = s.resample(freq)
        out = grouped.agg(how)
        if complete:
            out = out[grouped.count() == 7]
        return out.rename(name)

    def peak(self, name: str) -> tuple[pd.Timestamp, float]:
        """Date and height of the citywide peak of a series."""
        s = self.series(name)
        return s.idxmax(), float(s.max())

    def summary(self) -> dict:
        """Headline numbers as plain Python values (JSON-ready)."""
        pop = float(self.population.sum())
        inf = self.infections().sum(["patch", "age"])
        out: dict = {
            "start": str(self.ds.time.values[0])[:10],
            "end": str(self.ds.time.values[-1])[:10],
            "days": int(self.ds.sizes["time"]),
            "population": pop,
            "infections": float(inf.sum()),
            "attack_rate": float(inf.sum()) / pop,
            "r_eff_start": float(self.ds["r_eff"][0]),
            "r_eff_end": float(self.ds["r_eff"][-1]),
        }
        d, v = self.peak("infectious")
        out.update(peak_infectious=v, peak_infectious_date=str(d.date()))
        if "new_hosp" in self.ds:
            out["admissions"] = float(self.ds["new_hosp"].sum())
            d, v = self.peak("new_hosp")
            out.update(peak_admissions=v, peak_admissions_date=str(d.date()))
        if "H" in self.ds and "C" in self.ds:
            d, v = self.peak("inpatients")
            out.update(peak_inpatients=v, peak_inpatients_date=str(d.date()))
            d, v = self.peak("icu")
            out.update(peak_icu=v, peak_icu_date=str(d.date()))
        if "new_deaths" in self.ds:
            out["deaths"] = float(self.ds["new_deaths"].sum())
        return out

    # ---- export --------------------------------------------------------
    def to_frame(self, include_rates: bool = True) -> pd.DataFrame:
        """Long table by day and patch (ages summed), handy for CSV or a dashboard.

        With include_rates, rates are added as columns: per-cell rates are
        averaged over ages with population weights (as in EpiSnapshot).
        """
        df = self.counts_by_patch().to_dataframe()
        if include_rates:
            w = self.population
            for name in self.rates.data_vars:
                da = self.ds[name]
                if "age" in da.dims:
                    da = (da * w).sum("age") / w.sum("age")
                da = da.broadcast_like(self.ds["patch"]) if "patch" not in da.dims else da
                df[name] = da.transpose("time", "patch").to_series().reindex(df.index).to_numpy()
        df = df.drop(columns=[c for c in ("population",) if c in df.columns])
        return df.reset_index()

    def save(self, path: str | Path) -> None:
        """NetCDF for .nc (everything); CSV for .csv (the to_frame table)."""
        path = Path(path)
        if path.suffix == ".csv":
            self.to_frame().to_csv(path, index=False)
        else:
            self.ds.to_netcdf(path)
