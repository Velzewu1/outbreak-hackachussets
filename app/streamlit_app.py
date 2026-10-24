"""ResiliNet | Boston Hospital Cascade — Streamlit app.

Thin client over ``pipeline.api`` ONLY. No model math here. Caches immutable runs
by config/scenario JSON. Display week/phase never advance the model. Core demo
(polygons + points + tables + charts) renders without external APIs/tiles; an
optional online basemap is used only if available.

Research simulation — NOT for emergency planning. Labels synthetic/mixed/real
data status prominently.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from pipeline import api

st.set_page_config(
    page_title="ResiliNet | Boston Hospital Cascade",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Stable 0-100 color scale (fixed across weeks; never rescaled per week).
SCORE_DOMAIN = [0, 50, 70, 85, 100]


# --------------------------------------------------------------------------- #
# Cached engine calls (keyed by content)
# --------------------------------------------------------------------------- #


@st.cache_data(show_spinner="Loading data...")
def _load(mode: str, cfg_json: str):
    cfg = api.run_config_from_dict(json.loads(cfg_json))
    inp = api.load_inputs(mode, cfg)
    gj = api.district_geojson(inp)
    hosp = api.list_hospitals(inp)
    manifest = dict(inp.manifest)
    observed_available = bool(
        getattr(inp, "observed", None) and inp.observed.get("status") == "available"
    )
    return inp, gj, hosp, manifest, observed_available


@st.cache_data(show_spinner="Running simulation...")
def _run(mode: str, cfg_json: str, injections_json: str):
    inp, _gj, _h, _m, _o = _load(mode, cfg_json)
    injs = [
        api.make_injection(
            i["id"], i["kind"], i["start_week"], i["payload"], i.get("end_week"), i.get("note", "")
        )
        for i in json.loads(injections_json)
    ]
    run = api.run_scenario(inp, injs)
    base = api.run_scenario(inp, [])
    weeks = {}
    base_weeks = {}
    for w in api.list_weeks(run):
        weeks[(w, "before")] = api.get_week(run, w, "before")
        weeks[(w, "after")] = api.get_week(run, w, "after")
    for w in api.list_weeks(base):
        base_weeks[(w, "before")] = api.get_week(base, w, "before")
        base_weeks[(w, "after")] = api.get_week(base, w, "after")
    # Cache export bytes WITH the run so display reruns don't re-run the engine.
    exports = {
        "hospital_week.csv": api.export_csv(run, "hospital_week"),
        "district_week.csv": api.export_csv(run, "district_week"),
        "reroute_week.csv": api.export_csv(run, "reroute_week"),
        "run.json": api.export_json(run),
    }
    return run.run_id, base.run_id, weeks, base_weeks, len(api.list_weeks(run)), exports


def _cfg_json(mode, r0, d0, alpha_d, alpha_h, weeks, seed_frac, p_h, fallback):
    d = {
        "disease": {"r0": r0, "initial_infectious_fraction": seed_frac, "p_h": p_h},
        "network": {"d0_km": d0, "alpha_d": alpha_d, "alpha_h": alpha_h},
        "weeks": weeks,
        "nearest_outside_radius_fallback": bool(fallback),
    }
    return json.dumps(d, sort_keys=True)


def _score_color(score):
    # red (low) -> amber -> teal (high); supplementary to printed numbers.
    if score < 50:
        return [200, 30, 30]
    if score < 70:
        return [230, 140, 30]
    if score < 85:
        return [120, 170, 90]
    return [40, 130, 140]


# --------------------------------------------------------------------------- #
# Sidebar controls
# --------------------------------------------------------------------------- #

st.sidebar.title("ResiliNet")
st.sidebar.caption("Boston hospital cascade — epidemic pressure & care access")

mode = st.sidebar.selectbox(
    "Dataset",
    ["synthetic", "real", "golden"],
    help="synthetic = illustrative demo; real = Suffolk tracts + MassGIS hospitals "
    "(licensed-bed proxy, simulated epidemic); golden = 3x3 unit fixture.",
)

st.sidebar.subheader("Disease & network")
r0 = st.sidebar.slider("R0", 0.5, 5.0, 2.6, 0.1)
p_h = st.sidebar.slider("Hospitalization fraction p_H", 0.005, 0.1, 0.03, 0.005)
seed_frac = st.sidebar.slider(
    "Initial infectious fraction", 0.0005, 0.01, 0.003, 0.0005, format="%.4f"
)
d0 = st.sidebar.slider("Distance decay d0 (km)", 0.5, 15.0, 3.0, 0.5)
alpha_d = st.sidebar.slider("District dependence alpha_D", 0.0, 1.0, 0.9, 0.05)
alpha_h = st.sidebar.slider("Hospital dependence alpha_H", 0.0, 1.0, 0.1, 0.05)
weeks = st.sidebar.slider("Weeks", 2, 16, 8, 1)

fallback = st.sidebar.checkbox(
    "Nearest-outside-radius fallback",
    value=(mode == "real"),
    help="When a populated tract has no hospital within radius_km, assign its "
    "single nearest hospital (disclosed). Required for one NE-Suffolk tract "
    "in real mode; turning it off there raises an actionable error.",
)

cfg_json = _cfg_json(mode, r0, d0, alpha_d, alpha_h, weeks, seed_frac, p_h, fallback)
try:
    inp, gj, hospitals, manifest, observed_available = _load(mode, cfg_json)
except Exception as exc:  # graceful uncovered-tract (or other) error
    st.error(f"Could not load dataset '{mode}': {exc}")
    if mode == "real" and not fallback:
        st.info(
            "Enable 'Nearest-outside-radius fallback' to include the one "
            "NE-Suffolk peninsula tract (nearest hospital ~11.4 km)."
        )
    st.stop()

st.sidebar.subheader("Scenario events")
if "injections" not in st.session_state:
    st.session_state.injections = []

hosp_ids = [h["hospital_id"] for h in hospitals]

# Purge stale events when the dataset or horizon changes (hospital IDs differ,
# or end_week now exceeds the horizon). Prevents crashes on unknown targets.
ctx_key = (mode, weeks)
if st.session_state.get("_ctx_key") != ctx_key:
    kept = [
        i
        for i in st.session_state.injections
        if i["payload"].get("hospital_id") in hosp_ids and i["start_week"] < weeks
    ]
    for i in kept:
        if i.get("end_week") is not None:
            i["end_week"] = min(i["end_week"], weeks)
    if len(kept) != len(st.session_state.injections):
        st.sidebar.warning(
            "Removed scenario events that no longer apply to this dataset / horizon."
        )
    st.session_state.injections = kept
    st.session_state._ctx_key = ctx_key

with st.sidebar.form("add_injection", clear_on_submit=True):
    kind = st.selectbox("Event", ["close_hospital", "set_capacity"])
    target = st.selectbox("Hospital", hosp_ids)
    col1, col2 = st.columns(2)
    start_w = col1.number_input("Start week", 0, weeks - 1, 0, 1)
    end_w = col2.number_input("End week (excl)", 1, weeks, weeks, 1)
    factor = st.slider("Capacity factor (set_capacity)", 0.0, 1.0, 0.6, 0.05)
    submitted = st.form_submit_button("Add event")
    if submitted:
        payload = {"hospital_id": target}
        if kind == "set_capacity":
            payload["factor"] = float(factor)
        candidate = {
            "id": f"inj{len(st.session_state.injections)}",
            "kind": kind,
            "start_week": int(start_w),
            "end_week": int(end_w),
            "payload": payload,
            "note": f"{kind} {target} wks {start_w}-{end_w}",
        }
        try:
            api.make_injection(
                candidate["id"],
                candidate["kind"],
                candidate["start_week"],
                candidate["payload"],
                candidate["end_week"],
                candidate["note"],
            )
            st.session_state.injections.append(candidate)
        except Exception as exc:
            st.error(f"Invalid event: {exc}")

if st.session_state.injections:
    st.sidebar.write("Active events:")
    for i in st.session_state.injections:
        st.sidebar.write(f"- {i['note']}")
    if st.sidebar.button("Remove last event"):
        st.session_state.injections.pop()
        st.rerun()  # the list above was already drawn; redraw without the event
if st.sidebar.button("Reset to baseline"):
    st.session_state.injections = []
    st.rerun()

injections_json = json.dumps(st.session_state.injections, sort_keys=True)

# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

run_id, base_run_id, weeks_map, base_weeks, n_weeks, exports = _run(mode, cfg_json, injections_json)

# --------------------------------------------------------------------------- #
# Header + provenance
# --------------------------------------------------------------------------- #

mode_label = {
    "synthetic": "SYNTHETIC / ILLUSTRATIVE — not observed Boston data",
    "real": "MIXED ASSUMPTIONS — real Suffolk geography + licensed-bed proxy + SIMULATED epidemic",
    "golden": "SYNTHETIC golden unit fixture",
}[mode]

st.title("ResiliNet | Boston Hospital Cascade")
st.markdown(f"**Data mode:** {mode_label}")
st.caption(
    "Research simulation. Models potential access under simplified "
    "assumptions. Not for emergency dispatch, medical triage, or hospital planning."
)
st.caption(
    f"Run ID: `{run_id}` | Study area: Suffolk County, MA | Unit: census tracts | Step: 1 week"
)

week = st.slider(
    "Week (display only — does not advance the model)",
    0,
    n_weeks - 1,
    min(n_weeks - 1, n_weeks // 2),
)
phase = st.radio(
    "Phase",
    ["after", "before"],
    horizontal=True,
    help="before = provisional direct reservations; after = redirects applied (final).",
)

v = weeks_map[(week, phase)]
m = v["metrics"]

# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #

# Baseline comparison uses the SAME phase (baseline is computed as the 'after'
# of a no-injection run; when viewing 'before' we only show the scenario value,
# since baseline 'before' == baseline 'after' only absent reroutes).
baseline_same_phase = base_weeks.get((week, phase))
k1, k2, k3, k4 = st.columns(4)
k1.metric("Overloaded hospitals", m["overloaded_hospitals"])
if baseline_same_phase is not None:
    _delta = m["unmet_need_people"] - baseline_same_phase["metrics"]["unmet_need_people"]
    k2.metric(
        "Unmet need (people/wk)",
        f"{m['unmet_need_people']:.0f}",
        delta=f"{_delta:+.0f} vs baseline ({phase})",
        delta_color="inverse",
    )
else:
    k2.metric("Unmet need (people/wk)", f"{m['unmet_need_people']:.0f}")
k3.metric("Rerouted (people/wk)", f"{m['rerouted_people']:.1f}")
k4.metric(f"Districts < {int(api.RunConfig().score_threshold)}", m["districts_below_threshold"])

if mode == "real" and manifest.get("nearest_fallback_districts"):
    st.info(
        "Nearest-outside-radius fallback applied to tract(s): "
        f"{manifest['nearest_fallback_districts']} (disclosed; nearest care beyond 10 km)."
    )

tab_map, tab_hosp, tab_dist, tab_reroute, tab_valid, tab_data, tab_how = st.tabs(
    [
        "Map",
        "Hospitals",
        "Districts",
        "Reroute ledger",
        "Validation",
        "Data & methods",
        "How it works",
    ]
)

# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #

with tab_map:
    dscore = {d["district_id"]: d for d in v["districts"]}
    feats = []
    for f in gj["features"]:
        did = f["properties"]["district_id"]
        s = dscore.get(did, {}).get("access_score", 100.0)
        f2 = dict(f)
        f2["properties"] = dict(f["properties"])
        f2["properties"]["access_score"] = round(s, 1)
        f2["properties"]["name"] = ""  # districts show district_id
        f2["properties"]["score"] = ""  # hospital-only field, blank for tracts
        f2["properties"]["fill_color"] = _score_color(s)
        feats.append(f2)
    fc = {"type": "FeatureCollection", "features": feats}

    show_map = st.checkbox(
        "Render interactive map (pydeck)",
        value=True,
        help="Uncheck for a pure-table view (no map renderer).",
    )
    try:
        if not show_map:
            raise RuntimeError("map disabled by user")
        import pydeck as pdk

        poly = pdk.Layer(
            "GeoJsonLayer",
            fc,
            stroked=True,
            filled=True,
            get_fill_color="properties.fill_color",
            get_line_color=[80, 80, 80],
            line_width_min_pixels=0.5,
            pickable=True,
        )
        hosp_data = []
        for h in hospitals:
            hv = next((x for x in v["hospitals"] if x["hospital_id"] == h["hospital_id"]), None)
            score = hv["fdna_final_score"] if hv else 100.0
            hosp_data.append(
                {
                    **h,
                    "score": round(score, 1),
                    "access_score": "",  # district-only field, blank for hospitals
                    "district_id": "",
                    "color": _score_color(score),
                    "radius": 80 + (h["staffed_beds"] ** 0.5) * 12,
                }
            )
        points = pdk.Layer(
            "ScatterplotLayer",
            hosp_data,
            get_position=["lon", "lat"],
            get_fill_color="color",
            get_radius="radius",
            pickable=True,
            opacity=0.85,
        )
        lat0 = sum(h["lat"] for h in hospitals) / max(1, len(hospitals))
        lon0 = sum(h["lon"] for h in hospitals) / max(1, len(hospitals))
        deck = pdk.Deck(
            layers=[poly, points],
            initial_view_state=pdk.ViewState(latitude=lat0, longitude=lon0, zoom=10.5),
            map_style=None,  # core demo renders polygons/points without external tiles
            tooltip={
                "html": "<b>{name}{district_id}</b><br/>"
                "Hospital FDNA score: {score}<br/>"
                "District access score: {access_score}",
                "style": {"backgroundColor": "#222", "color": "white"},
            },
        )
        st.pydeck_chart(deck)
    except Exception as e:  # pragma: no cover - map fallback
        if show_map:
            st.warning(f"Map renderer unavailable ({e}); showing table fallback below.")
        else:
            st.caption("Map disabled — table view below.")

    beds_label = (
        "licensed-bed CAPACITY PROXY (not verified staffed beds)"
        if mode == "real"
        else "staffed beds (synthetic)"
    )
    st.caption(
        f"District color = access score (0-100, fixed legend). Hospital dot "
        f"size = {beds_label}, color = FDNA score. Legend: red<50, amber<70, "
        f"green<85, teal>=85."
    )
    st.dataframe(
        pd.DataFrame(v["districts"]).sort_values("access_score").reset_index(drop=True),
        width="stretch",
        height=260,
    )

# --------------------------------------------------------------------------- #
# Hospitals
# --------------------------------------------------------------------------- #

with tab_hosp:
    hdf = pd.DataFrame(v["hospitals"])
    st.dataframe(hdf, width="stretch")
    sel = st.selectbox("Hospital detail", [h["hospital_id"] for h in v["hospitals"]])
    hrow = next(h for h in v["hospitals"] if h["hospital_id"] == sel)
    c1, c2, c3 = st.columns(3)
    c1.metric("Requested load", f"{hrow['requested_load']:.1f}")
    c1.metric("Effective capacity", f"{hrow['effective_capacity_beds']:.0f}")
    c2.metric("Committed occupancy", f"{hrow['committed_beds']:.1f}")
    c2.metric("Inherited deficit", f"{hrow['inherited_deficit_beds']:.1f}")
    c3.metric("Own score", f"{hrow['own_score']:.1f}")
    c3.metric("FDNA score", f"{hrow['fdna_final_score']:.1f}")
    # trend across weeks
    trend = pd.DataFrame(
        [
            {
                "week": w,
                "requested_load": weeks_map[(w, phase)]["hospitals"][
                    [
                        i
                        for i, x in enumerate(weeks_map[(w, phase)]["hospitals"])
                        if x["hospital_id"] == sel
                    ][0]
                ]["requested_load"],
                "committed": weeks_map[(w, phase)]["hospitals"][
                    [
                        i
                        for i, x in enumerate(weeks_map[(w, phase)]["hospitals"])
                        if x["hospital_id"] == sel
                    ][0]
                ]["committed_beds"],
            }
            for w in range(n_weeks)
        ]
    ).set_index("week")
    st.line_chart(trend)

# --------------------------------------------------------------------------- #
# Districts
# --------------------------------------------------------------------------- #

with tab_dist:
    # EJ overlay control (disabled with explanation when flags unavailable).
    ej_values = {f["properties"].get("ej_flag") for f in gj["features"]}
    ej_known = any(x in (True, False) for x in ej_values)
    if ej_known:
        st.checkbox(
            "Environmental-justice overlay",
            value=False,
            help="Outlines EJ-flagged tracts. Styling only; does not change scores.",
            key="ej_overlay",
        )
    else:
        st.checkbox(
            "Environmental-justice overlay",
            value=False,
            disabled=True,
            help="EJ flags are unavailable/unknown for this dataset "
            "(ej_flag=null). Overlay disabled; scores still shown.",
        )
        st.caption("EJ data unavailable for this dataset — overlay disabled.")

    ddf = pd.DataFrame(v["districts"])
    st.dataframe(ddf.sort_values("access_score"), width="stretch", height=320)
    st.caption("new_admission_need and unmet_need are people/week (NOT beds).")

    # Selected-tract detail + access-over-time.
    sel_d = st.selectbox("Tract detail", [d["district_id"] for d in v["districts"]])
    drow = next(d for d in v["districts"] if d["district_id"] == sel_d)
    dc = st.columns(3)
    dc[0].metric("Access score", f"{drow['access_score']:.1f}")
    dc[1].metric("New-admission need (ppl/wk)", f"{drow['new_admission_need_people']:.1f}")
    dc[2].metric("Unmet need (ppl/wk)", f"{drow['unmet_need_people']:.1f}")
    trend = pd.DataFrame(
        [
            {
                "week": w,
                "access_score": next(
                    x for x in weeks_map[(w, phase)]["districts"] if x["district_id"] == sel_d
                )["access_score"],
                "unmet_need": next(
                    x for x in weeks_map[(w, phase)]["districts"] if x["district_id"] == sel_d
                )["unmet_need_people"],
            }
            for w in range(n_weeks)
        ]
    ).set_index("week")
    st.caption(f"Access and unmet need over time for {sel_d} (phase {phase}):")
    st.line_chart(trend)

# --------------------------------------------------------------------------- #
# Reroute ledger
# --------------------------------------------------------------------------- #

with tab_reroute:
    if v["reroutes"]:
        st.dataframe(pd.DataFrame(v["reroutes"]), width="stretch")
    elif phase == "before":
        st.info("Reroutes are computed in the 'after' phase; switch phase to 'after'.")
    elif m["unmet_need_people"] <= 1e-6:
        st.info(
            "No rerouting needed: all new-admission requests were placed "
            "directly this week (no residual demand)."
        )
    else:
        st.info(
            "No rerouting occurred: residual new-admission demand exists but no "
            "eligible hospital had spare capacity to receive it. With 0 moves, "
            "before == after by construction."
        )

# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

with tab_valid:
    st.subheader("Historical validation (real mode only)")
    if mode != "real":
        st.info("Validation uses real HHS data and is available in 'real' mode only.")
    else:
        st.markdown(
            "Facility-level backtest against HHS Suffolk COVID occupied beds "
            "(weekly MEANS), 2020-10-04 .. 2021-05-30. Two strategies reported: a "
            "**fixed-origin multi-week rollout** and a **rolling-origin one-week-"
            "ahead** forecast with expanding-window train fitting (target week "
            "never in the fit). Computed offline and exposed via `pipeline.api`."
        )
        report = api.evaluation_report()
        if report.get("status") == "unavailable":
            st.warning(
                f"Validation unavailable — {report.get('reason', 'not computed')}. "
                "Run `PYTHONPATH=. .venv/bin/python scripts/run_backtest.py`."
            )
        else:
            fo = report.get("fixed_origin", {})
            ro = report.get("rolling_origin", {})

            def _headline(label, block):
                verified = report.get("status") == "verified" and block.get("forecast_pairs", 0) > 0
                st.markdown(f"**{label}** — {block.get('strategy', '')}")
                if not verified:
                    st.info("No numeric headline: status is not 'verified' or 0 forecast pairs.")
                    return
                c = st.columns(3)
                c[0].metric("Model MAE (beds)", f"{block['model_mae_beds']:.2f}")
                c[1].metric("Persistence MAE (beds)", f"{block['persistence_mae_beds']:.2f}")
                c[2].metric("Forecast pairs", block["forecast_pairs"])

            _headline("Fixed-origin", fo)
            _headline("Rolling-origin (one-week-ahead)", ro)
            st.warning(
                "The model's measured MAE is WORSE than the naive persistence "
                "baseline in both strategies. Reported honestly; a simple "
                "shared-curve SEIR does not beat 'next week = this week' here."
            )
            st.caption(
                f"status={report.get('status')} | train_weeks={report.get('train_weeks')} "
                f"| holdout_weeks={report.get('holdout_weeks')} "
                f"| matched_facilities={report.get('matched_facilities')} "
                f"| min_coverage_days={report.get('min_coverage_days')} "
                f"| leakage_free={ro.get('leakage_free')}"
            )

            # observed vs model vs persistence per-facility chart (rolling rows)
            rows = ro.get("rows") or fo.get("rows") or []
            if rows:
                rdf = pd.DataFrame(rows)
                ccns = sorted(rdf["ccn"].unique())
                sel_ccn = st.selectbox("Facility (CCN)", ccns)
                sub = rdf[rdf["ccn"] == sel_ccn].copy()
                sub = sub.set_index("target")[["observed", "model", "persistence"]]
                st.line_chart(sub)
                st.caption(
                    "Dated holdout target weeks. observed = HHS weekly mean; "
                    "model = fixed/rolling forecast; persistence = prior-week observed."
                )
            if fo.get("per_facility"):
                st.markdown("Per-facility MAE (fixed-origin):")
                st.dataframe(pd.DataFrame(fo["per_facility"]).T, width="stretch")

# --------------------------------------------------------------------------- #
# Data & methods
# --------------------------------------------------------------------------- #

with tab_data:
    st.subheader("Data mode & provenance")
    st.json(manifest)
    st.subheader("Exports")
    # Cached export bytes (produced with the run); no engine re-run on interaction.
    colx = st.columns(4)
    colx[0].download_button(
        "hospital_week.csv", exports["hospital_week.csv"], "hospital_week.csv", "text/csv"
    )
    colx[1].download_button(
        "district_week.csv", exports["district_week.csv"], "district_week.csv", "text/csv"
    )
    colx[2].download_button(
        "reroute_week.csv", exports["reroute_week.csv"], "reroute_week.csv", "text/csv"
    )
    colx[3].download_button("run.json", exports["run.json"], "run.json", "application/json")

# --------------------------------------------------------------------------- #
# How it works
# --------------------------------------------------------------------------- #

with tab_how:
    st.markdown(
        """
### Pipeline (weekly)
`DATA -> SEPARATE -> IL1 -> SEIR -> IL2 -> FDNA -> ANALYSIS -> IL3 -> RESULTS`

1. **SEIR (need-state):** a shared regional S/E/I/R curve (`S+E+I+R=N`) produces a
   per-district **new-admission need** signal `H_need = p_H x i_exit`
   (people/week, **not** beds). `risk_weight` scales hospitalization need.
2. **Accessibility:** distance-decay shares `exp(-d/d0)`, nearest-k within radius.
3. **IL2 / allocation:** **new admissions only** are requested at hospitals;
   existing inpatients are persistent retained cohorts and are never re-allocated.
4. **FDNA:** two bounded passes (before/after rerouting) over hospital cycles and
   share-weighted district scores. Scores never change physical beds.
5. **ANALYSIS:** direct reservation then row-preserving global reroute of unmet
   new-admission requests to hospitals with real spare capacity. Zero moves =>
   before == after.
6. **Accounting:** `accepted + unmet = need` per origin district; occupants
   survive closure as an **inherited deficit** (never deleted).

### Honesty
Synthetic runs are labeled. Real mode uses real geography but a **licensed-bed
capacity proxy** and a **simulated** epidemic. The historical backtest reports the
model's error even though it **loses** to persistence.
"""
    )
