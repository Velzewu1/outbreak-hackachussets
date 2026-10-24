"""Command line: python -m cascade run|criticality scenario.yaml"""
from __future__ import annotations

import argparse
import json

from . import api


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cascade")
    ap.add_argument("command", choices=["run", "criticality"])
    ap.add_argument("scenario")
    ap.add_argument("--days", type=int)
    ap.add_argument("--out", help="NetCDF path for the system dataset (run only)")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)
    cfg = api.load(a.scenario)
    if a.command == "run":
        res = api.run(cfg, a.days)
        print(json.dumps(res.summary(), indent=2))
        if a.out:
            res.system.to_netcdf(a.out)
    else:
        print(api.criticality(cfg, a.days, workers=a.workers).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
