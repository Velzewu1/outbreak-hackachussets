"""Config loading/validation. Builds a validated RunConfig from a dict or YAML."""

from __future__ import annotations

from pathlib import Path

from .contracts import (
    DiseaseConfig,
    FDNASettings,
    NetworkConfig,
    RunConfig,
    Tolerances,
)


def run_config_from_dict(d: dict | None) -> RunConfig:
    d = dict(d or {})
    disease = DiseaseConfig(**d.get("disease", {}))
    network = NetworkConfig(**d.get("network", {}))
    tol = Tolerances(**d.get("tolerances", {}))
    fdna = FDNASettings(**d.get("fdna", {}))
    top = {k: v for k, v in d.items() if k not in ("disease", "network", "tolerances", "fdna")}
    cfg = RunConfig(disease=disease, network=network, tolerances=tol, fdna=fdna, **top)
    return cfg.validate()


def load_config(path: str | Path | None = None) -> RunConfig:
    if path is None:
        return RunConfig().validate()
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return run_config_from_dict(data)
