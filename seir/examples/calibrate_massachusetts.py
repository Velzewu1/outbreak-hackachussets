"""Calibrate and validate the SEIR layer on Massachusetts data, in the terminal.

    python examples/calibrate_massachusetts.py           # all three checks, about a minute
    python examples/calibrate_massachusetts.py --quick   # step 1 only
    python examples/calibrate_massachusetts.py --json    # numbers only, for a frontend or a log

Follows the validation plan in the project writeup, with the SEIR layer on
its own (no hospitals or FDNA yet), so these numbers are the "SEIR-only
baseline" that the full system should beat:

  1. Calibrate on the Omicron wave: fit R0, the hospitalisation scale and the
     seed to HHS weekly COVID admissions and score the fit with the pass bars.
  2. Backtest as a forecast: fit only up to a date, predict every week after
     it and score those weeks.
  3. Out of sample: fit the winter 2020-21 wave to admissions only, then score
     the inpatient and ICU census, which the model never sees, against the
     COVID Tracking Project.

Everything held fixed (periods, lengths of stay, age contacts, prior
immunity) comes from the scenario files; their comments and
docs/validation.md say where each value comes from.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cascade.epi import ScenarioConfig, data, terminal                      # noqa: E402
from cascade.epi.calibrate import Param, aligned, fit_scenario, fitted_series  # noqa: E402
from cascade.epi.validation import backtest, score, validate_series         # noqa: E402

PATCH = "Massachusetts"
OMICRON_WEEKS = ("2021-12-25", "2022-03-05")   # weeks ending; Omicron-dominated admissions
WINTER_WEEKS = ("2020-10-03", "2021-03-06")
SPLITS = ("2022-01-08", "2022-01-15")          # a week before the peak, and the peak week


def fit_params(hosp_scale: bool = True) -> dict[str, Param]:
    """What is fitted, with deliberately generic starting values."""
    params = {"disease.r0": Param(2.0, 1.0, 8.0),
              f"seeding.exposed.{PATCH}": Param(5000, 10, 500_000, log=True)}
    if hosp_scale:
        params["disease.hosp_scale"] = Param(1.0, 0.05, 10.0)
    return params


def file_values(cfg: ScenarioConfig) -> dict[str, float]:
    return {"disease.r0": cfg.disease.r0, "disease.hosp_scale": cfg.disease.hosp_scale,
            f"seeding.exposed.{PATCH}": cfg.seeding.exposed[PATCH]}


def fitted_table(fit, cfg: ScenarioConfig) -> str:
    saved = file_values(cfg)
    fmt = (lambda k, v: f"{v:,.0f}" if k.startswith("seeding") else f"{v:.2f}")
    df = pd.DataFrame([{"value": k, "fitted": fmt(k, v), "in scenario file": fmt(k, saved[k])}
                       for k, v in fit.params.items()])
    return terminal.table(df)


def weeks_table(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["error"] = [f"{round(100 * (m - o) / o):+d}%" for m, o in zip(out["model"], out["observed"])]
    out.index = [d.strftime("%d %b %Y") for d in out.index]
    return out.rename_axis("week ending")


def step_omicron(adm_weekly: pd.Series, out: dict, quiet: bool) -> None:
    cfg = ScenarioConfig.from_yaml(ROOT / "scenarios" / "omicron_2021.yaml")
    observed = adm_weekly[OMICRON_WEEKS[0]:OMICRON_WEEKS[1]]
    t = time.perf_counter()
    fit = fit_scenario(cfg, observed, fit_params())
    frame = fitted_series(fit)
    report = validate_series(frame["model"], frame["observed"], title="Pass bars (fitted weeks)")
    summary = fit.result.summary()
    out["omicron_fit"] = {"params": fit.params, "cost": fit.cost, "validation": report.to_dict(),
                          "metrics": score(frame["model"], frame["observed"]),
                          "r_eff_start": summary["r_eff_start"], "attack_rate": summary["attack_rate"]}
    if quiet:
        return
    print("=" * 78)
    print("1. Calibrate on the Omicron wave")
    print("=" * 78)
    print(f"HHS weekly COVID admissions, Massachusetts, {len(observed)} weeks ending "
          f"{observed.index[0]:%d %b %Y} to {observed.index[-1]:%d %b %Y}.")
    print("Fixed: covid_omicron periods and stays, Prem 2021 contacts, 22% protected on 1 Dec 2021.")
    print(f"Fitted in {time.perf_counter() - t:.1f} s ({fit.nfev} evaluations):\n")
    print(fitted_table(fit, cfg))
    print(f"\nThat means R_eff {summary['r_eff_start']:.2f} on 1 Dec and {summary['attack_rate']:.0%} "
          f"of residents infected by {summary['end']}.\n")
    print(terminal.table(weeks_table(frame), floatfmt="{:,.0f}", index=True))
    print()
    print(terminal.chart({"observed": frame["observed"], "model": frame["model"]}, height=10, width=44,
                         title="Weekly admissions: observed (o) and model (*)"))
    print()
    print(report)


def step_backtest(adm_weekly: pd.Series, out: dict, quiet: bool) -> None:
    cfg = ScenarioConfig.from_yaml(ROOT / "scenarios" / "omicron_2021.yaml")
    observed = adm_weekly[OMICRON_WEEKS[0]:OMICRON_WEEKS[1]]
    rows, records, shown = [], [], None
    t = time.perf_counter()
    for split in SPLITS:
        for label, base, params in (("fitted", cfg, fit_params()),
                                    ("from preset", cfg.updated({"disease.hosp_scale": 1.0}),
                                     fit_params(hosp_scale=False))):
            bt = backtest(base, observed, params, split)
            c = {k.name: k.value for k in bt.report.checks}
            rows.append({"fitted up to": pd.Timestamp(split).strftime("%d %b %Y"), "severity": label,
                         "weeks within 40%": f"{c['weeks within +-40%']:.0%}",
                         "peak week": int(c["peak week offset"]),
                         "peak height": f"{round(100 * c['peak height error']):+d}%",
                         "result": "PASS" if bt.report.passed else "FAIL"})
            records.append({"split": split, "severity": label, "params": bt.fit.params,
                            "validation": bt.report.to_dict(), "metrics": bt.metrics})
            if split == SPLITS[0] and label == "from preset":
                shown = bt
    out["backtest"] = records
    if quiet:
        return
    print("\n" + "=" * 78)
    print("2. Backtest as a forecast")
    print("=" * 78)
    print("Fit only the weeks up to a date, predict every week after it, score those weeks.")
    print("'from preset' keeps hospitalisation per infection at the covid_omicron preset")
    print(f"and fits only R0 and the seed. ({time.perf_counter() - t:.0f} s)\n")
    print(terminal.table(pd.DataFrame(rows)))
    both = pd.concat([shown.train, shown.test])
    print()
    print(terminal.chart({"observed": both["observed"], "forecast": both["model"]}, height=10, width=44,
                         title=f"Fitted up to {pd.Timestamp(SPLITS[0]):%d %b} with preset severity: "
                               "observed (o), model (*)"))
    print("""
The first weeks of a wave can't tell how many infections stand behind each
admission, so with severity free the fit can't tell when susceptibles will run
out, and the forecast misses the turn. Taking severity from outside the data
(here the preset; in practice the last wave or the literature) fixes that.""")


def step_winter(adm_weekly: pd.Series, out: dict, quiet: bool) -> None:
    cfg = ScenarioConfig.from_yaml(ROOT / "scenarios" / "winter_2020.yaml")
    observed = adm_weekly[WINTER_WEEKS[0]:WINTER_WEEKS[1]]
    t = time.perf_counter()
    fit = fit_scenario(cfg, observed, fit_params())
    frame = fitted_series(fit)
    fitted_report = validate_series(frame["model"], frame["observed"], title="Admissions (fitted)")
    census = data.ctp_state(ROOT / "data" / "ctp_ma_hospital_census.csv")
    weekly_census = census.resample("W-SAT").mean().loc[WINTER_WEEKS[0]:WINTER_WEEKS[1]]
    checks, frames = {}, {}
    for name, column, label in (("inpatients", "hospitalizedCurrently", "COVID inpatients"),
                                ("icu", "inIcuCurrently", "COVID patients in ICU")):
        model = pd.Series(aligned(fit.result.series(name), weekly_census.index, 7, "end", "mean"),
                          index=weekly_census.index)
        frames[name] = pd.DataFrame({"observed": weekly_census[column], "model": model})
        checks[name] = validate_series(model, weekly_census[column], title=f"{label} (never fitted)")
    out["winter"] = {"params": fit.params,
                     **{k: {"validation": r.to_dict(), "metrics": score(f["model"], f["observed"])}
                        for k, r, f in (("admissions", fitted_report, frame),
                                        ("inpatients", checks["inpatients"], frames["inpatients"]),
                                        ("icu", checks["icu"], frames["icu"]))}}
    if quiet:
        return
    print("\n" + "=" * 78)
    print("3. Out of sample: winter 2020-21")
    print("=" * 78)
    print(f"Fitted to admissions only ({len(observed)} weeks, covid_ancestral preset) in "
          f"{time.perf_counter() - t:.1f} s:\n")
    print(fitted_table(fit, cfg))
    print()
    print(fitted_report)
    print("\nThe census follows from the admissions and the literature lengths of stay")
    print("(ward 5 d, ICU 9 d). Weekly mean census against the COVID Tracking Project:\n")
    both = frames["inpatients"].rename(columns={"observed": "inpatients_obs", "model": "inpatients_model"})
    both = both.join(frames["icu"].rename(columns={"observed": "icu_obs", "model": "icu_model"}))
    both.index = [d.strftime("%d %b %Y") for d in both.index]
    print(terminal.table(both.rename_axis("week ending"), floatfmt="{:,.0f}", index=True))
    print()
    print(terminal.chart({"observed": frames["inpatients"]["observed"], "model": frames["inpatients"]["model"]},
                         height=10, width=44, title="COVID inpatients: observed (o) and model (*)"))
    print()
    print(checks["inpatients"])
    print()
    print(checks["icu"])


def _plain(x):
    """JSON for the odd numpy or pandas value."""
    if isinstance(x, (pd.Timestamp,)):
        return str(x.date())
    if isinstance(x, (np.integer,)):
        return int(x)
    return float(x)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true", help="only step 1, the Omicron fit")
    ap.add_argument("--json", action="store_true", help="print the numbers as JSON instead")
    ap.add_argument("--save", metavar="PATH", help="also write the numbers as JSON to PATH "
                                                   "(docs/seir_baseline.json is one such file)")
    args = ap.parse_args(argv)
    admissions = data.hhs_state_admissions(ROOT / "data" / "hhs_ma_daily_admissions.csv")
    adm_weekly = data.weekly(admissions)               # MMWR weeks, Sunday to Saturday
    out: dict = {}
    steps = [step_omicron] if args.quick else [step_omicron, step_backtest, step_winter]
    for step in steps:
        step(adm_weekly, out, quiet=args.json)
    text = json.dumps(out, indent=2, default=_plain)
    if args.json:
        print(text)
    if args.save:
        Path(args.save).write_text(text + "\n")


if __name__ == "__main__":
    main()
