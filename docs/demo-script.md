# Three-minute demo script

Setup: `.venv/bin/python -m streamlit run app/streamlit_app.py` → 127.0.0.1:8501.
Keep the hero map visible. Say "research simulation" once up front.

**0:00–0:25 — Problem.** "Hospitals don't work in isolation. When an epidemic
adds bed demand, a shortfall at one facility pushes nearby neighborhoods onto
already-stressed alternatives. ResiliNet is an educational Boston what-if model."
Point to the data-mode banner (synthetic vs real-geography + licensed-bed proxy +
simulated epidemic).

**0:25–1:35 — Live demo (synthetic first for a clean wave).**
1. Slide **Week** forward; watch the district choropleth and KPIs change.
2. Open **Scenario events**, add `close_hospital` for a stressed hospital for a
   week range; "Add event".
3. Toggle **Phase** before→after; narrate: "same week, same epidemic — rerouting
   moves only new admissions into hospitals with real spare capacity."
4. Read the KPIs: overloaded hospitals, **unmet need (people/week, not beds)**,
   rerouted people, districts below the access threshold. Note the baseline delta.
5. Open the **Reroute ledger** tab: `(district, source→destination, amount)`.

**1:35–2:15 — Method + validation.** Switch dataset to **real** (Suffolk tracts +
MassGIS hospitals). Open **Validation**: facility-level backtest vs HHS COVID
occupied beds. **Say honestly: the model's MAE is worse than persistence.** Show
the observed-vs-model-vs-persistence chart for one facility. This is real data
science reported truthfully, not a manufactured win.

**2:15–2:40 — Equity & limits.** Mention the EJ overlay control (disabled with an
explanation when flags are unknown, as in real mode). State limits: licensed-bed
proxy, distance ≠ real transfers, simulated epidemic, weekly-mean target.

**2:40–3:00 — Impact / next steps.** "A transparent sandbox for who-loses-access
questions. Next: real staffed-bed and transfer data, calibrated parameters,
coupled epidemic." 

Backup: if Wi-Fi/tiles fail, the map still renders polygons/points offline
(`map_style=None`); a recorded run is the fallback. Never claim a deployed URL or
a validation win that wasn't computed.
