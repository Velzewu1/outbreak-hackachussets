"""Command line for the SEIR layer: python -m cascade.epi <command> ...

  presets                          disease presets and where their numbers come from
  info SCENARIO                    derived rates: beta0, sigma, gamma, R0, generation time, doubling time
  run SCENARIO                     simulate and print curves, totals and a table by patch
  ensemble SCENARIO                stochastic runs with 5-50-95% bands
  sensitivity SCENARIO             +-25% one-at-a-time on chosen inputs
  calibrate SCENARIO --observed    fit inputs to a dated CSV and score the fit

Every command takes --set path=value (repeatable) to change the scenario on
the fly, e.g. --set disease.r0=2.2 --set sim.days=200, and --json for
machine-readable output (what a frontend would consume).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from pydantic import ValidationError

from . import terminal
from .calibrate import Param, fit_scenario, fitted_series
from .config import ScenarioConfig
from .engine import SEIREngine
from .presets import DISEASES, SOURCES
from .structure import STRUCTURES


# ---- shared helpers ------------------------------------------------------------
def _load(args) -> ScenarioConfig:
    cfg = ScenarioConfig.from_yaml(args.scenario)
    changes = {}
    for item in args.set or []:
        if "=" not in item:
            raise SystemExit(f"--set needs path=value, got {item!r}")
        path, value = item.split("=", 1)
        changes[path.strip()] = yaml.safe_load(value)
    return cfg.updated(changes) if changes else cfg


def _engine(cfg: ScenarioConfig, args) -> SEIREngine:
    feedback = tuple(getattr(args, "feedback", None) or ())
    return SEIREngine.from_config(cfg, structure=STRUCTURES[args.structure](), feedback=feedback)


def _print_json(obj) -> None:
    def default(x):
        if isinstance(x, (np.floating, np.integer)):
            return x.item()
        if isinstance(x, (pd.Timestamp,)):
            return str(x.date())
        if isinstance(x, np.ndarray):
            return x.tolist()
        return str(x)

    print(json.dumps(obj, indent=2, default=default))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "es" if word.endswith("ch") else "s")


def _growth(r: float) -> str:
    if r > 0:
        return f"growth {r:+.3f}/day, doubling every {np.log(2) / r:.1f} d"
    return f"growth {r:+.3f}/day" + (f", halving every {np.log(2) / -r:.1f} d" if r < 0 else "")


def _header(cfg: ScenarioConfig, eng: SEIREngine, path: str) -> str:
    d = eng.describe(seeding=cfg.seeding)
    pop = cfg.population
    dis = cfg.disease
    rates = [f"transmission {d['transmission_rate']:.4f}/day"]
    if d["incubation_rate"] is not None:
        rates.append(f"incubation {d['incubation_rate']:.4f}/day")
    if d["recovery_rate"] is not None:
        rates.append(f"recovery {d['recovery_rate']:.4f}/day")
    immune = cfg.immune_share()
    start = "on day 0" + (f" ({np.average(immune, weights=pop.N.sum(axis=1)):.0%} immune)" if immune.any() else "")
    return "\n".join([
        f"Scenario  {path}",
        f"          {'-'.join(d['compartments'])}, {_plural(len(pop.patches), 'patch')} x "
        f"{_plural(len(pop.ages), 'age group')}, {d['population']:,.0f} people",
        f"Disease   {dis.name}: R0 {dis.r0:g}, latent {dis.latent_period:g} d, infectious "
        f"{dis.infectious_period:g} d, ward {dis.los_ward:g} d, ICU {dis.los_icu:g} d",
        f"Rates     {', '.join(rates)}",
        f"Spread    R0 {d['r0']:.2f}: {_growth(d['growth_rate_per_day'])}; generation time "
        f"{d['generation_time_days']:.1f} d",
        f"          {start}: R_eff {d['r_eff_start']:.2f}, {_growth(d['growth_rate_start'])}",
    ])


# ---- commands ------------------------------------------------------------------
def cmd_presets(args) -> None:
    rows = []
    for name, p in DISEASES.items():
        hosp = p["p_hosp"]
        rows.append({
            "preset": name, "R0": p["r0"], "latent_d": p["latent_period"],
            "infectious_d": p["infectious_period"],
            "p_hosp": ", ".join(f"{v:g}" for v in hosp.values()) if isinstance(hosp, dict) else f"{hosp:g}",
            "p_icu": p["p_icu"], "p_death_icu": p["p_death_icu"],
            "ward_d": p["los_ward"], "icu_d": p["los_icu"],
        })
    if args.json:
        _print_json({"presets": DISEASES, "sources": SOURCES})
        return
    print(terminal.table(pd.DataFrame(rows), floatfmt="{:g}"))
    print("\np_hosp is per infection, by age 0-17, 18-64, 65+. Use one in YAML with")
    print("  disease: {preset: covid_omicron, r0: 2.2}")
    print("\nSources:")
    for k, v in SOURCES.items():
        print(f"  {k}: {v}")


def cmd_info(args) -> None:
    cfg = _load(args)
    eng = _engine(cfg, args)
    if args.json:
        _print_json({"scenario": args.scenario, "engine": eng.describe(seeding=cfg.seeding), "beta0": eng.beta0})
        return
    print(_header(cfg, eng, args.scenario))
    print(f"          beta0 {eng.beta0:.6g} (per contact-weighted infectious person per day)")
    print(f"\nInfection path {' -> '.join(eng.structure.infection_path)}; "
          f"rates: {', '.join(eng.rates.names)}")


def _by_patch(res) -> pd.DataFrame:
    inf = res.infections().sum(["time", "age"]).to_series()
    pop = res.population.sum("age").to_series()
    df = pd.DataFrame({"infections": inf, "attack_rate_%": 100 * inf / pop})
    if "new_hosp" in res.ds:
        df["admissions"] = res.ds["new_hosp"].sum(["time", "age"]).to_series()
    if "H" in res.ds and "C" in res.ds:
        df["peak_inpatients"] = res.inpatients().max("time").to_series()
    if "new_deaths" in res.ds:
        df["deaths"] = res.ds["new_deaths"].sum(["time", "age"]).to_series()
    return df.rename_axis("patch").reset_index()


def cmd_run(args) -> None:
    cfg = _load(args)
    if args.stochastic:
        cfg = cfg.updated({"sim.stochastic": True, "sim.seed": args.seed})
    eng = _engine(cfg, args)
    days = args.days or cfg.sim.days
    res = eng.run(cfg.seeding, days)
    if args.out:
        res.save(args.out)
    summary = res.summary()
    if args.json:
        _print_json({"scenario": args.scenario, "engine": eng.describe(seeding=cfg.seeding), "summary": summary,
                     "by_patch": _by_patch(res).to_dict(orient="records")})
        return
    print(_header(cfg, eng, args.scenario))
    print(f"\nDaily, {summary['start']} to {summary['end']} ({days} days)")
    rows = [("new infections", "infections"), ("admissions", "new_hosp"),
            ("inpatients", "inpatients"), ("in ICU", "icu"), ("deaths", "new_deaths")]
    width = 60
    for label, name in rows:
        try:
            s = res.series(name)
        except KeyError:
            continue
        print(f"  {label:<16}{terminal.sparkline(s.values, width)}  peak {s.max():,.0f} on {s.idxmax().date()}")
    r = res.ds["r_eff"].values
    print(f"  {'R_eff':<16}{terminal.sparkline(r, width, low=0)}  {r[0]:.2f} -> {r[-1]:.2f}")
    beta = res.ds["transmission_rate"]
    if beta.ndim == 1 and np.ptp(beta.values) > 0:
        print(f"  {'transmission':<16}{terminal.sparkline(beta.values, width, low=0)}  "
              f"{beta.values.min():.3f} to {beta.values.max():.3f}/day")
    totals = [f"infections {summary['infections']:,.0f} ({summary['attack_rate']:.1%} of people)"]
    if "admissions" in summary:
        totals.append(f"admissions {summary['admissions']:,.0f}")
    if "deaths" in summary:
        totals.append(f"deaths {summary['deaths']:,.0f}")
    print("\nTotals    " + ", ".join(totals))
    print("\nBy patch")
    print(terminal.table(_by_patch(res)))
    if args.weekly:
        weeks = pd.DataFrame({name: res.weekly(name) for _, name in rows if name in res.ds or
                              name in ("infections", "inpatients", "icu")})
        print("\nBy week (flows summed, census averaged)")
        print(terminal.table(weeks.rename_axis("week_ending"), floatfmt="{:,.0f}", index=True))
    if args.out:
        print(f"\nSaved {args.out}")


def cmd_ensemble(args) -> None:
    from .ensemble import bands, run_ensemble, takeoff_share

    cfg = _load(args)
    ens = run_ensemble(cfg, runs=args.runs, seed=args.seed, workers=args.workers,
                       days=args.days, structure=args.structure)
    b = bands(ens)
    weekly = {}
    for v in ("new_hosp", "inpatients"):
        da = b[v].to_pandas().T                                   # time x quantile
        how = "sum" if v == "new_hosp" else "mean"
        weekly[v] = da.resample("W-SAT").agg(how)
    share = takeoff_share(ens)
    if args.json:
        _print_json({"runs": args.runs, "takeoff_share": share,
                     "weekly": {v: df.reset_index().to_dict(orient="records") for v, df in weekly.items()}})
        return
    print(f"{args.runs} stochastic runs of {args.scenario}; {share:.0%} took off\n")
    for v, label in (("new_hosp", "Weekly admissions"), ("inpatients", "Weekly mean inpatients")):
        df = weekly[v].copy()
        df.columns = [f"q{int(round(100 * q)):02d}" for q in df.columns]
        print(label)
        print(terminal.table(df.rename_axis("week_ending"), floatfmt="{:,.0f}", index=True))
        print()
    lo, mid, hi = (b["inpatients"].sel(quantile=q).values for q in b["quantile"].values[[0, len(b["quantile"]) // 2, -1]])
    print(terminal.chart({"5%": lo, "median": mid, "95%": hi}, title="Inpatients (all patches)"))


def cmd_sensitivity(args) -> None:
    from .sensitivity import one_at_a_time

    cfg = _load(args)
    df = one_at_a_time(cfg, args.params, metric=args.metric, rel=args.rel, workers=args.workers,
                       days=args.days)
    if args.json:
        _print_json(df.to_dict(orient="records"))
        return
    print(f"One at a time, each input x{1 - args.rel:g} and x{1 + args.rel:g}; output: {args.metric}\n")
    print(terminal.table(df, floatfmt="{:,.3g}"))
    top = df["swing"].max() or 1.0
    print()
    for _, r in df.iterrows():
        bar = "#" * int(round(40 * r["swing"] / top))
        print(f"  {r['parameter']:<32} {bar}")


def _parse_fit(items) -> dict[str, Param]:
    params = {}
    for item in items:
        try:
            path, spec = item.split("=", 1)
            parts = spec.split(":")
            log = parts[-1] == "log"
            initial, low, high = (float(x) for x in parts[:3])
        except ValueError:
            raise SystemExit(f"--fit needs path=initial:low:high[:log], got {item!r}") from None
        params[path] = Param(initial, low, high, log=log)
    return params


def _observed(args) -> pd.Series:
    df = pd.read_csv(args.observed, dtype=str)
    for f in args.filter or []:
        col, value = f.split("=", 1)
        df = df[df[col] == value]
    s = pd.Series(pd.to_numeric(df[args.column], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df[args.date_column], format="mixed")).groupby(level=0).sum().sort_index()
    if args.start:
        s = s[s.index >= pd.Timestamp(args.start)]
    if args.end:
        s = s[s.index <= pd.Timestamp(args.end)]
    if args.weekly:
        counts = s.resample("W-SAT").count()
        s = s.resample("W-SAT").sum()[counts == 7]
    if s.empty:
        raise SystemExit("no observations left after filtering")
    return s


def cmd_calibrate(args) -> None:
    from .validation import backtest, validate_series

    params = _parse_fit(args.fit)
    cfg = _load(args)
    observed = _observed(args)
    kw = dict(variable=args.variable, engine_kwargs={"structure": STRUCTURES[args.structure]()})
    if args.split:
        bt = backtest(cfg, observed, params, args.split, **kw)
        fit, frame, report = bt.fit, pd.concat([bt.train, bt.test]), bt.report
    else:
        fit = fit_scenario(cfg, observed, params, **kw)
        frame = fitted_series(fit)
        report = validate_series(frame["model"], frame["observed"], title="fitted weeks")
    if args.write:
        fit.config.to_yaml(args.write)
    if args.json:
        _print_json({"params": fit.params, "cost": fit.cost, "success": fit.success,
                     "validation": report.to_dict(),
                     "series": frame.reset_index(names="date").to_dict(orient="records")})
        return
    print(f"Fitted {args.variable} to {len(observed)} observations from {args.observed}"
          + (f" (fit up to {args.split}, scored after)" if args.split else ""))
    print(terminal.key_values({k: float(v) for k, v in fit.params.items()}))
    print(f"  cost {fit.cost:.4g}, {fit.nfev} evaluations, {'converged' if fit.success else 'NOT converged'}\n")
    print(terminal.table(frame.rename_axis("date"), floatfmt="{:,.0f}", index=True))
    print()
    print(terminal.chart({"observed": frame["observed"].to_numpy(), "model": frame["model"].to_numpy()},
                         title=f"{args.variable}: observed (o) vs model (*)"))
    print()
    print(report)
    if args.write:
        print(f"\nWrote the fitted scenario to {args.write}")


# ---- argument parsing ------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m cascade.epi", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def scenario_cmd(name, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("scenario", help="scenario YAML")
        p.add_argument("--set", action="append", metavar="PATH=VALUE",
                       help="change a scenario value, e.g. disease.r0=2.2 (repeatable)")
        p.add_argument("--structure", default="seir_h", choices=sorted(STRUCTURES))
        p.add_argument("--json", action="store_true", help="machine-readable output")
        return p

    p = sub.add_parser("presets", help="list disease presets")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_presets)

    p = scenario_cmd("info", "derived rates and reproduction numbers")
    p.set_defaults(func=cmd_info)

    p = scenario_cmd("run", "simulate a scenario")
    p.add_argument("--days", type=int)
    p.add_argument("--stochastic", action="store_true", help="chain-binomial run")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--weekly", action="store_true", help="also print a weekly table")
    p.add_argument("--feedback", action="append", metavar="SIGNAL",
                   help="wire a standard feedback signal (see rates.FEEDBACK)")
    p.add_argument("--out", help="save results: .nc (everything) or .csv (table by day and patch)")
    p.set_defaults(func=cmd_run)

    p = scenario_cmd("ensemble", "stochastic runs with uncertainty bands")
    p.add_argument("--runs", type=int, default=50)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--days", type=int)
    p.set_defaults(func=cmd_ensemble)

    p = scenario_cmd("sensitivity", "one-at-a-time sensitivity")
    p.add_argument("--params", nargs="+", required=True, metavar="PATH",
                   help="scenario values to vary, e.g. disease.r0 disease.los_icu")
    p.add_argument("--metric", default="peak_inpatients", help="a key of SEIRResult.summary()")
    p.add_argument("--rel", type=float, default=0.25)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--days", type=int)
    p.set_defaults(func=cmd_sensitivity)

    p = scenario_cmd("calibrate", "fit scenario values to observed data")
    p.add_argument("--observed", required=True, help="CSV with a date column and a value column")
    p.add_argument("--column", default="value")
    p.add_argument("--date-column", default="date")
    p.add_argument("--filter", action="append", metavar="COLUMN=VALUE",
                   help="keep rows where COLUMN equals VALUE, e.g. location=25 (repeatable)")
    p.add_argument("--start", help="first observation date to use")
    p.add_argument("--end", help="last observation date to use")
    p.add_argument("--weekly", action="store_true", help="sum daily observations into MMWR weeks first")
    p.add_argument("--variable", default="new_hosp", help="model series to compare (new_hosp, inpatients, ...)")
    p.add_argument("--fit", action="append", required=True, metavar="PATH=INIT:LOW:HIGH[:log]",
                   help="a value to fit, e.g. disease.r0=2.5:1.2:5 (repeatable)")
    p.add_argument("--split", help="backtest: fit up to this date, score the rest")
    p.add_argument("--write", help="write the fitted scenario to this YAML file")
    p.set_defaults(func=cmd_calibrate)
    return ap


def _message(e: Exception) -> str:
    """One readable line, e.g. "disease.r0: Input should be greater than 0"."""
    if isinstance(e, ValidationError):
        return "; ".join((".".join(str(x) for x in err["loc"]) + ": " if err["loc"] else "")
                         + err["msg"].removeprefix("Value error, ") for err in e.errors())
    if isinstance(e, KeyError) and e.args:
        return str(e.args[0])
    return str(e)


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"error: {_message(e)}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
