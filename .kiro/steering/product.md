---
inclusion: always
---

# Product overview

Build a transparent, Boston-focused what-if model showing how an epidemic can overload hospitals and reduce neighborhood access to care.

The core user journey is:

1. Choose a disease and network scenario.
2. Run the model one week at a time.
3. Inspect hospital load and district access on a map.
4. Inject a disruption or intervention, such as closing a hospital or reducing capacity.
5. Compare before/after operability, rerouting, unmet demand, and validation metrics.

The MVP combines district-level SEIR+H dynamics, distance-based patient allocation, hospital capacity scores, FDNA-style dependency propagation, and bounded patient rerouting.

## Product constraints

- This is a research and demonstration tool, not a clinical or operational decision system.
- Use public, aggregate data only; never use patient-level records.
- Never invent observations. Clearly label modeled assumptions and configurable defaults.
- Preserve validation: compare next-week hospital occupancy against real historical data and a simple baseline.
- Optimize for a three-minute demo: one map, a small control set, and a clear before/after story.

For more detail, read `docs/project-brief.md`.
