---
inclusion: always
---

# Project structure

Keep the repository organized by pipeline boundary:

```text
README.md
requirements.txt
config.yaml
app/                 Streamlit entry point and presentation components
data/raw/            fetch scripts and reviewed source snapshots
data/clean/          validated, analysis-ready tables
docs/                project context, data dictionary, sources, and limits
pipeline/            data, separate, il1, seir, il2, fdna, analysis, il3
tests/               unit and integration tests mirroring pipeline modules
validation/          backtests, baseline forecasts, and metrics
```

## Architecture rules

- A pipeline stage may consume the previous stage's typed output but must not reach backward into raw internals.
- SEIR and FDNA never read raw data and never call each other directly; IL1 and IL2 translate between contracts.
- Put all adjustable values in `config.yaml`; do not hide model parameters in functions.
- Keep one primary module per pipeline block and mirror it with tests.
- Prefer small pure functions for transformations and explicit result types for layer boundaries.
- Validate schemas, ranges, IDs, conservation constraints, and share sums at every boundary.
- Keep Streamlit presentation logic out of the scientific pipeline.
- Save generated results outside source directories and do not commit secrets or large unreviewed raw files.
