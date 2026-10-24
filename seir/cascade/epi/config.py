"""Validated scenario configuration for the SEIR layer.

Everything a run needs lives in one ScenarioConfig, which loads from YAML.
Periods are in days; rates are derived from them as 1 / period in one place
(DiseaseParams.sigma and .gamma). Every model rejects unknown keys, so a typo
in a YAML file fails loudly instead of being ignored.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .presets import DISEASES

# A per-age value: one number for every age group, a list in age order, or a
# mapping from age label to value (checked against population.ages).
AgeValue = float | list[float] | dict[str, float]
AGE_FIELDS = ("p_hosp", "p_icu", "p_death_icu")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiseaseParams(_Strict):
    name: str = "custom"
    r0: float = Field(gt=0, description="Basic reproduction number in a fully susceptible population")
    latent_period: float = Field(gt=0, description="Mean days in E before becoming infectious")
    infectious_period: float = Field(gt=0, description="Mean days in I")
    p_hosp: AgeValue = 0.0       # share of infections that are hospitalised
    p_icu: AgeValue = 0.0        # share of hospitalised who move to ICU
    p_death_icu: AgeValue = 0.0  # share of ICU patients who die
    los_ward: float = Field(default=5.0, gt=0, description="Mean days on the ward")
    los_icu: float = Field(default=10.0, gt=0, description="Mean days in ICU")
    # Multiplies p_hosp in every age group. Calibration fits it, and
    # data.places_comorbidity_multiplier() can set it from CDC PLACES.
    hosp_scale: float = Field(default=1.0, gt=0)

    @model_validator(mode="before")
    @classmethod
    def _apply_preset(cls, data: Any) -> Any:
        if isinstance(data, dict) and "preset" in data:
            data = dict(data)
            name = data.pop("preset")
            if name not in DISEASES:
                raise ValueError(f"unknown disease preset {name!r}; choose from {sorted(DISEASES)}")
            data = {**DISEASES[name], **data}
        return data

    @model_validator(mode="after")
    def _check_shares(self) -> "DiseaseParams":
        for name in AGE_FIELDS:
            v = getattr(self, name)
            values = np.asarray(list(v.values()) if isinstance(v, dict) else v, dtype=float)
            if ((values < 0) | (values > 1)).any():
                raise ValueError(f"{name} values must be shares between 0 and 1")
        return self

    @property
    def sigma(self) -> float:
        """Incubation rate (per day): 1 / latent period."""
        return 1.0 / self.latent_period

    @property
    def gamma(self) -> float:
        """Recovery rate (per day): 1 / infectious period."""
        return 1.0 / self.infectious_period

    def by_age(self, name: str, n_age: int, ages: list[str] | None = None) -> np.ndarray:
        """A per-age field as an array of length n_age."""
        value = getattr(self, name)
        if isinstance(value, dict):
            if ages is None:
                raise ValueError(f"{name} is given per age label; pass the population's age labels")
            if set(value) != set(ages):
                raise ValueError(f"{name} labels {sorted(value)} do not match population ages {list(ages)}")
            return np.array([value[a] for a in ages], dtype=float)
        arr = np.atleast_1d(np.asarray(value, dtype=float))
        if arr.size == 1:
            return np.full(n_age, arr.item())
        if arr.size != n_age:
            raise ValueError(f"{name} has {arr.size} values but there are {n_age} age groups")
        return arr


class Population(_Strict):
    patches: list[str]
    ages: list[str] = ["all"]
    counts: list[list[float]]  # [patch][age], residents

    @model_validator(mode="after")
    def _check(self) -> "Population":
        for label, names in (("patch", self.patches), ("age", self.ages)):
            if len(set(names)) != len(names):
                raise ValueError(f"{label} names must be unique")
        arr = np.asarray(self.counts, dtype=float)
        if arr.shape != (len(self.patches), len(self.ages)):
            raise ValueError(f"counts must be {len(self.patches)} x {len(self.ages)}, got {arr.shape}")
        if not np.isfinite(arr).all() or (arr <= 0).any():
            raise ValueError("every patch and age group needs a positive, finite population")
        return self

    @property
    def N(self) -> np.ndarray:
        """Residents as a [patch, age] array."""
        return np.asarray(self.counts, dtype=float)


class ContactMultiplier(_Strict):
    """beta(t) = beta0 * m(t), with m(t) = 1 + elasticity * (raw(t) - 1).

    Give exactly one source:
      values: daily raw values starting at sim.start
      steps:  {day: value} held until the next step, e.g. a lockdown timeline
      csv:    a dated CSV (path relative to the YAML file), e.g. MBTA gated
              entries or Google mobility; rows sharing a date are summed
    percent_change: raw values are % change from some normal (Google mobility
                    reports), so they are first turned into 1 + raw / 100.
    Then say what 1.0 means, with at most one of:
      baseline:       values are divided by this number
      baseline_dates: [start, end]; each day is divided by the median of the
                      same weekday in that window (Google's method; use it to
                      rebase mobility to the weeks before a fit starts)
    smooth_days averages the last n days (after normalising). elasticity < 1
    says contacts fall less than mobility does.
    """
    values: list[float] | None = None
    steps: dict[int, float] | None = None
    csv: str | None = None
    column: str = "multiplier"
    date_column: str = "date"
    baseline: float | None = Field(default=None, gt=0)
    baseline_dates: tuple[date, date] | None = None
    percent_change: bool = False
    smooth_days: int = Field(default=1, ge=1)
    elasticity: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _one_source(self) -> "ContactMultiplier":
        given = [s for s in (self.values, self.steps, self.csv) if s is not None]
        if len(given) != 1:
            raise ValueError("contact_multiplier needs exactly one of values, steps or csv")
        if self.baseline is not None and self.baseline_dates is not None:
            raise ValueError("give at most one of baseline and baseline_dates")
        if self.baseline_dates is not None:
            if self.csv is None:
                raise ValueError("baseline_dates needs a dated csv source")
            if self.baseline_dates[0] > self.baseline_dates[1]:
                raise ValueError("baseline_dates must be [start, end]")
        if self.steps is not None and self.smooth_days > 1:
            raise ValueError("smooth_days applies to daily series, not steps")
        return self


class Mixing(_Strict):
    # C[a, b]: relative daily contacts of an age-a person with age-b people.
    age_contacts: list[list[float]] | None = None
    # W[p, r]: share of time residents of patch p spend in location r. Rows sum to 1.
    patch_coupling: list[list[float]] | None = None
    contact_multiplier: ContactMultiplier | None = None


class Seeding(_Strict):
    """Initial state. Counts are people per patch, spread over ages by population."""
    exposed: dict[str, float] = {}
    infectious: dict[str, float] = {}
    # Share of each patch already immune at the start (moved from S to R):
    # one number for every patch, or a share per patch.
    immune_share: float | dict[str, float] = 0.0
    # People already in other compartments on day 0, as {compartment: {patch:
    # count}}: e.g. today's hospital census, {"H": {"Boston": 280}, "C":
    # {"Boston": 55}}, when a run starts mid-wave. A number is spread over
    # ages by population; a list gives one count per age group.
    initial: dict[str, dict[str, float | list[float]]] = {}

    @model_validator(mode="after")
    def _initial_names(self) -> "Seeding":
        clash = {"exposed", "infectious"} & set(self.initial)
        if clash:
            raise ValueError(f"use seeding.{sorted(clash)[0]} for those seeds, not seeding.initial")
        return self

    def counts(self, n_age: int) -> dict[str, dict[str, np.ndarray | float]]:
        """exposed, infectious and initial together: {compartment or role: {patch: count}}."""
        out: dict[str, dict] = {"exposed": dict(self.exposed), "infectious": dict(self.infectious)}
        for comp, by_patch in self.initial.items():
            out[comp] = {p: (np.asarray(v, dtype=float) if isinstance(v, list) else float(v))
                         for p, v in by_patch.items()}
        return out


class SimConfig(_Strict):
    start: date
    days: int = Field(gt=0)
    substeps: int = Field(default=4, ge=1)
    stochastic: bool = False
    seed: int | None = None


class ScenarioConfig(_Strict):
    disease: DiseaseParams
    population: Population
    mixing: Mixing = Mixing()
    seeding: Seeding
    sim: SimConfig

    @model_validator(mode="after")
    def _check_shapes(self) -> "ScenarioConfig":
        pop = self.population
        n_patch, n_age = len(pop.patches), len(pop.ages)
        if self.mixing.age_contacts is not None:
            C = np.asarray(self.mixing.age_contacts, dtype=float)
            if C.shape != (n_age, n_age):
                raise ValueError(f"age_contacts must be {n_age} x {n_age}, got {C.shape}")
            if (C < 0).any() or not C.any():
                raise ValueError("age_contacts must be non-negative and not all zero")
        if self.mixing.patch_coupling is not None:
            W = np.asarray(self.mixing.patch_coupling, dtype=float)
            if W.shape != (n_patch, n_patch):
                raise ValueError(f"patch_coupling must be {n_patch} x {n_patch}, got {W.shape}")
            if (W < 0).any():
                raise ValueError("patch_coupling must be non-negative")
            if not np.allclose(W.sum(axis=1), 1.0, atol=1e-6):
                raise ValueError("each row of patch_coupling must sum to 1")

        # Per-age values given as {label: value} become lists in age order, so
        # everything downstream can call by_age(name, n_age).
        updates = {}
        for name in AGE_FIELDS:
            values = self.disease.by_age(name, n_age, pop.ages)
            if isinstance(getattr(self.disease, name), dict):
                updates[name] = values.tolist()
        if updates:
            self.disease = self.disease.model_copy(update=updates)

        seeds = self.seeding
        groups = seeds.counts(n_age)
        named = set().union(*(set(g) for g in groups.values()))
        if isinstance(seeds.immune_share, dict):
            named |= set(seeds.immune_share)
        unknown = named - set(pop.patches)
        if unknown:
            raise ValueError(f"seeding names unknown patches: {sorted(unknown)}")
        immune = self.immune_share()
        if ((immune < 0) | (immune > 1)).any():
            raise ValueError("immune_share must be between 0 and 1")
        N = pop.N.sum(axis=1)
        for i, patch in enumerate(pop.patches):
            seeded = 0.0
            for comp, by_patch in groups.items():
                v = np.asarray(by_patch.get(patch, 0.0), dtype=float)
                if v.ndim and v.shape != (n_age,):
                    raise ValueError(f"seeding.initial.{comp}.{patch} needs one count per age group ({n_age})")
                if (v < 0).any() or not np.isfinite(v).all():
                    raise ValueError(f"seeding for {patch} must be non-negative")
                seeded += float(v.sum())
            if seeded > N[i] * (1.0 - immune[i]) + 1e-9:
                raise ValueError(f"seeding for {patch} exceeds its susceptible population")
        return self

    # ---- derived inputs ------------------------------------------------
    def contact_matrix(self) -> np.ndarray:
        n_age = len(self.population.ages)
        if self.mixing.age_contacts is None:
            return np.ones((n_age, n_age)) / n_age
        return np.asarray(self.mixing.age_contacts, dtype=float)

    def coupling_matrix(self) -> np.ndarray:
        if self.mixing.patch_coupling is None:
            return np.eye(len(self.population.patches))
        return np.asarray(self.mixing.patch_coupling, dtype=float)

    def immune_share(self) -> np.ndarray:
        """Initial immune share per patch, as an array in patch order."""
        share = self.seeding.immune_share
        if isinstance(share, dict):
            return np.array([share.get(p, 0.0) for p in self.population.patches], dtype=float)
        return np.full(len(self.population.patches), float(share))

    # ---- copies and files ----------------------------------------------
    def updated(self, changes: Mapping[str, Any]) -> "ScenarioConfig":
        """A validated copy with dotted-path changes, e.g. {"disease.r0": 2.2}.

        {"disease.preset": "measles"} swaps the pathogen: the disease section
        starts again from that preset (other changes in the same call apply
        on top), rather than keeping the old disease's values.
        """
        data = self.model_dump()
        changes = dict(changes)
        if "disease.preset" in changes:
            data["disease"] = {"preset": changes.pop("disease.preset")}
        for path, value in changes.items():
            node, keys = data, path.split(".")
            for key in keys[:-1]:
                if not isinstance(node.get(key), dict):
                    raise KeyError(f"{path}: {key!r} is not a section of the scenario")
                node = node[key]
            node[keys[-1]] = value
        return type(self).model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ScenarioConfig":
        path = Path(path)
        raw = yaml.safe_load(path.read_text())
        cm = ((raw or {}).get("mixing") or {}).get("contact_multiplier") or {}
        if cm.get("csv") and not Path(cm["csv"]).is_absolute():
            cm["csv"] = str((path.parent / cm["csv"]).resolve())
        return cls.model_validate(raw)

    def to_yaml(self, path: str | Path | None = None) -> str:
        """YAML text for this scenario; also written to `path` when given."""
        text = yaml.safe_dump(self.model_dump(mode="json", exclude_none=True), sort_keys=False)
        if path is not None:
            Path(path).write_text(text)
        return text
