# Outbreak Hackachussets

A Boston-focused epidemic and hospital dependency-network prototype for DS+X 2026 and Hackachusetts. The planned MVP combines a district-level SEIR+H epidemic model with hospital capacity, FDNA-style dependency propagation, patient rerouting, scenario injections, validation, and a Streamlit map.

## Start in Kiro

1. Open this folder with `kiro .`.
2. Open the Kiro panel and review the workspace steering files.
3. Open the `epidemic-hospital-mvp` spec under **Specs**.
4. Review the requirements, design, and tasks before running implementation tasks.
5. Create the Python environment with `python3.12 -m venv .venv` and activate it with `source .venv/bin/activate`.

The repository intentionally starts with project context and specifications only. Implementation work should be performed in Kiro on the `kiro/project-setup` branch.

## Guardrails

- Use only public, aggregate data; never patient-level data.
- Label assumptions in `config.yaml`, the README, and the presentation.
- Keep each pipeline layer behind small, typed functions with validated inputs and outputs.
- Treat the app as a what-if research prototype, not a clinical or operational decision tool.

See [docs/project-brief.md](docs/project-brief.md) for the condensed project plan.
