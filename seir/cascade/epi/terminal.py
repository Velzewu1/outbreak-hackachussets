"""Plain-text charts and tables for terminal demos (no plotting library needed)."""
from __future__ import annotations

from typing import Mapping, Sequence

import re

import numpy as np
import pandas as pd

BLOCKS = "▁▂▃▄▅▆▇█"
_NUMBER = re.compile(r"^[+-]?[\d,]*\.?\d+(e[+-]?\d+)?%?$")


def _resample(values: np.ndarray, width: int) -> np.ndarray:
    """Average consecutive values down to at most `width` points."""
    values = np.asarray(values, dtype=float)
    if len(values) <= width:
        return values
    edges = np.linspace(0, len(values), width + 1).astype(int)
    return np.array([np.nanmean(values[a:b]) for a, b in zip(edges[:-1], edges[1:])])


def sparkline(values, width: int = 60, low: float | None = None, high: float | None = None) -> str:
    """One line of block characters showing the shape of a series."""
    v = _resample(np.asarray(values, dtype=float), width)
    if v.size == 0:
        return ""
    lo = np.nanmin(v) if low is None else low
    hi = np.nanmax(v) if high is None else high
    if not np.isfinite(hi - lo) or hi - lo <= 0:
        return BLOCKS[0] * len(v)
    idx = np.clip(((v - lo) / (hi - lo) * (len(BLOCKS) - 1)).round(), 0, len(BLOCKS) - 1)
    return "".join(" " if not np.isfinite(x) else BLOCKS[int(i)] for i, x in zip(idx, v))


def chart(series: Mapping[str, pd.Series | Sequence[float]], height: int = 12, width: int = 64,
          markers: str = "o*+x#", title: str = "") -> str:
    """Several series on one character grid, sharing the y axis (x is position, left to right).

    Long series are averaged down to `width` columns; short ones are spread
    out over it. Each series gets a marker, and "@" marks points where two
    series land on the same cell. A legend and the y range are printed below.
    """
    cols = {name: _resample(np.asarray(s, dtype=float), width) for name, s in series.items()}
    n = max(len(v) for v in cols.values())
    step = max(1, (width - 1) // max(n - 1, 1)) if n < width else 1
    span = (n - 1) * step + 1
    finite = [np.nanmax(v) for v in cols.values() if np.isfinite(v).any()]
    top = max(finite) if finite else 1.0
    top = top if top > 0 else 1.0
    grid = [[" "] * span for _ in range(height)]
    overlap = False
    for (name, v), mark in zip(cols.items(), markers):
        for x, y in enumerate(v):
            if np.isfinite(y):
                row = min(max(height - 1 - int(round(y / top * (height - 1))), 0), height - 1)
                here = grid[row][x * step]
                overlap |= here not in (" ", mark)
                grid[row][x * step] = "@" if here not in (" ", mark) else mark
    label_w = len(f"{top:,.0f}")
    lines = [title] if title else []
    for r, row in enumerate(grid):
        y = top * (height - 1 - r) / (height - 1)
        label = f"{y:,.0f}" if r in (0, height // 2, height - 1) else ""
        lines.append(f"{label:>{label_w}} |" + "".join(row))
    lines.append(" " * label_w + " +" + "-" * span)
    legend = [f"{m} {name}" for name, m in zip(cols, markers)] + (["@ both"] if overlap else [])
    lines.append(" " * (label_w + 2) + "   ".join(legend))
    return "\n".join(lines)


def table(df: pd.DataFrame, floatfmt: str | Mapping[str, str] = "{:,.1f}", index: bool = False) -> str:
    """A DataFrame as aligned text, with thousands separators for numbers.

    floatfmt is one format for every float, or {column: format} with an
    optional "" entry as the default, e.g. {"seed": "{:,.0f}", "": "{:.2f}"}.
    """
    data = df.reset_index() if index else df
    formats = floatfmt if isinstance(floatfmt, Mapping) else {"": floatfmt}

    def fmt(x, column):
        if isinstance(x, (float, np.floating)):
            return "" if np.isnan(x) else formats.get(column, formats.get("", "{:,.1f}")).format(x)
        if isinstance(x, (int, np.integer)) and not isinstance(x, bool):
            return f"{x:,}"
        if isinstance(x, pd.Timestamp):
            return str(x.date())
        return str(x)

    columns = list(data.columns)
    cells = [[str(c) for c in columns]] + [[fmt(x, c) for x, c in zip(row, columns)]
                                           for row in data.itertuples(index=False)]
    widths = [max(len(r[i]) for r in cells) for i in range(len(cells[0]))]
    numeric = [pd.api.types.is_numeric_dtype(data[c])
               or all(_NUMBER.match(r[i]) for r in cells[1:] if r[i]) for i, c in enumerate(columns)]
    out = []
    for k, r in enumerate(cells):
        out.append("  ".join(c.rjust(w) if num else c.ljust(w) for c, w, num in zip(r, widths, numeric)).rstrip())
        if k == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def key_values(d: Mapping[str, object], floatfmt: str = "{:,.4g}") -> str:
    """A dict as aligned "key  value" lines."""
    width = max(len(k) for k in d) if d else 0
    lines = []
    for k, v in d.items():
        if isinstance(v, float):
            v = floatfmt.format(v)
        elif isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        lines.append(f"  {k:<{width}}  {v}")
    return "\n".join(lines)
