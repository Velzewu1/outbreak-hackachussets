"""Write boston_districts.geojson: one outline per neighborhood in boston_neighborhoods.csv.

    pip install shapely
    python systems/make_districts.py [boston.geojson]

Source: the City of Boston's 26 neighborhood boundaries (Analyze Boston, public
domain), as republished by Code for America's click_that_hood. The scenario's 15
neighborhoods merge some of them; the grouping below is ours. The Harbor Islands
are left out. Shapes are simplified to about 20 m, which is plenty for a city map.
Each feature also carries a label point well inside the shape.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import polylabel, unary_union

HERE = Path(__file__).resolve().parent
SOURCE = ("https://raw.githubusercontent.com/codeforgermany/click_that_hood/"
          "main/public/data/boston.geojson")
TOLERANCE = 0.0002          # degrees, about 20 m

GROUPS = {
    "Allston-Brighton": ["Allston", "Brighton"],
    "Back Bay-Beacon Hill": ["Back Bay", "Beacon Hill", "Bay Village"],
    "Charlestown": ["Charlestown"],
    "Dorchester": ["Dorchester"],
    "Downtown-North End": ["Downtown", "North End", "West End", "Chinatown", "Leather District"],
    "East Boston": ["East Boston"],
    "Fenway-Mission Hill": ["Fenway", "Mission Hill", "Longwood Medical Area"],
    "Hyde Park": ["Hyde Park"],
    "Jamaica Plain": ["Jamaica Plain"],
    "Mattapan": ["Mattapan"],
    "Roslindale": ["Roslindale"],
    "Roxbury": ["Roxbury"],
    "South Boston": ["South Boston", "South Boston Waterfront"],
    "South End": ["South End"],
    "West Roxbury": ["West Roxbury"],
}


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 5), round(coords[1], 5)]
    return [_round(c) for c in coords]


def build(source: dict) -> dict:
    parts = {f["properties"]["name"]: shape(f["geometry"]).buffer(0) for f in source["features"]}
    features = []
    for patch, names in GROUPS.items():
        missing = [n for n in names if n not in parts]
        if missing:
            raise KeyError(f"{patch}: {missing} not in the source")
        geom = unary_union([parts[n] for n in names]).simplify(TOLERANCE, preserve_topology=True)
        biggest = max(getattr(geom, "geoms", [geom]), key=lambda g: g.area)
        label = polylabel(biggest, tolerance=1e-4)
        g = mapping(geom)
        features.append({"type": "Feature",
                         "properties": {"patch": patch, "label": [round(label.x, 5), round(label.y, 5)]},
                         "geometry": {"type": g["type"], "coordinates": _round(g["coordinates"])}})
    return {"type": "FeatureCollection", "features": features}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        src = json.loads(Path(sys.argv[1]).read_text())
    else:
        with urllib.request.urlopen(SOURCE, timeout=60) as r:
            src = json.load(r)
    out = HERE / "boston_districts.geojson"
    out.write_text(json.dumps(build(src), separators=(",", ":")) + "\n")
    print(f"wrote {out}")
