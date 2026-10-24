# README images

This folder holds the screenshots shown in the [root README](../../../README.md).
No image files exist yet. The root README shows a parenthesized placeholder for
each missing image so that no broken image link appears on GitHub.

## How to add an image

1. Capture the screenshot (see the table below).
2. Save it under the exact filename shown. Use PNG.
3. In the root `README.md`, find the matching line that starts with `(IMAGE:` and
   replace that whole line with the Markdown image line from the table.

Example. Replace this line:

```text
(IMAGE: docs/assets/images/dashboard-overview.png — Interactive dashboard overview)
```

with this line:

```markdown
![Interactive dashboard overview: map of Suffolk County tracts colored by access score, with hospital circles and four summary numbers](docs/assets/images/dashboard-overview.png)
```

Nothing else in the README needs to change.

## Reserved images

Recommended size: 1600 px wide (about 16:9 or 16:10), under 500 KB each.
Capture at normal browser zoom and crop out browser toolbars.

| File | What to capture | Alt text to use |
|---|---|---|
| `dashboard-overview.png` | Streamlit app, Map tab, week mid-run, phase "after". Show the sidebar, the four summary numbers, and the map. | Interactive dashboard overview: map of Suffolk County tracts colored by access score, with hospital circles and four summary numbers |
| `epidemic-timeline.png` | A chart of how pressure changes week by week. In the Streamlit app, use the trend chart on the "Hospitals" tab (requested load and committed beds) or the one on the "Districts" tab (access score and unmet need). Use the same dataset as the other screenshots. | Line chart of hospital requested load and committed beds across the simulated weeks |
| `hospital-network.png` | "Hospitals" tab with one hospital selected: requested load, effective capacity, own score, FDNA score. | Hospital detail panel showing requested load, capacity, and network score for one hospital |
| `rerouting-before-after.png` | Same week twice, phase "before" and phase "after", with a closure event added. Combine the two views side by side. | Side-by-side map of the same week before and after rerouting, with a hospital closed |
| `scenario-comparison.png` | Four summary numbers with the "vs baseline" change after a closure or capacity cut, plus the "Reroute ledger" tab if it fits. | Scenario comparison showing unmet need and rerouted people compared with the no-event baseline |
| `architecture-diagram.png` | Optional. A clean export of the nine-stage pipeline diagram. Keep the README text diagram until this exists. | Pipeline diagram from districts and hospitals through the epidemic model, patient allocation, and network analysis to interactive results |

## Rules

- Use only real screenshots from the running app. Do not mock up or edit results.
- Label the dataset in the shot. The default `synthetic` dataset shows a
  `SYNTHETIC / ILLUSTRATIVE` banner. Keep that banner visible.
- Write alt text that describes what the picture shows, not "screenshot".
- Use relative paths. Do not link to images hosted elsewhere.
