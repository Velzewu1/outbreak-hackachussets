# Prompt — WS2 FDNA developer

> Do not start until the architecture is approved (gate CLOSED).

You are the **FDNA agent**. Own `pipeline/fdna.py` and `tests/test_fdna.py`. Do
**not** edit `contracts/`, shared files, or other workstreams' modules. Do **not**
import the reference document's daily resource-node / ICU / diversion equations.

Read in authority order: `AGENTS.md`, `Addiotional Info 1.txt`,
`docs/mathematical-model.md` (§4), `contracts/pipeline-types.md` (`FDNAGraph`
= dependency edges only, `FDNAResult`, `HospitalLoad`),
`contracts/stage-io-and-signatures.md` (FDNA signatures),
`contracts/validation-rules.md` (§5),
`docs/end-to-end-walkthrough.md` (§1.4, §1.8, §2.3, §2.5), then primary plan §5.6
and blueprint §11. Read the Garvey–Pinto 2009 reference only to label the method
accurately as **"FDNA-based"**, not classical FDNA. Adapt any existing FDNA code
to these contracts; do not redesign the shared interface.

Implement two pure solvers, run **twice per week** (before and after reroute):

1. **Hospital fixed point** over symmetric cycles:
   `strength_ij = α_ij·P_j + (1−α_ij)·O_i`, `critical_i = min_j(P_j+β_ij)`,
   `P_i_new = clip(min(O_i, mean_j strength_ij, critical_i), 0, 100)`. Init
   `P_i=O_i`; **synchronous (Jacobi)** update from the prior vector; stop when
   `max|ΔP| <= 0.1`; hard cap 500 iterations; **non-convergence raises** and is
   reported (never silent). `O_i = 100·min(1, Ceff_i / requested_load_i)`
   (requested-load / need view), closed ⇒ 0.
2. **District share-weighted score** using post-cascade `P_i` and **unchanged base
   shares**: `SOD_j = α_D·Σ_i s_ji·P_i + (1−α_D)·100`,
   `COD_j = min_{s_ji>0}(P_i + 100·(1−s_ji))`,
   `DistrictScore_j = clip(min(SOD_j, COD_j), 0, 100)`.

Honor disjoint graph semantics (correction 4): only `hospital_hospital`
(symmetric, configurable) and `hospital_district` edges; **no** district→hospital
edge; an FDNA edge is not a routing route.

Tests (`tests/test_fdna.py`): F-1 golden 0/50/75 (1/2/4 equal hospitals, one
failed, α_D=0.9); cyclic convergence; `α_H=0` ⇒ no spillover; closed node stays 0;
ID-order independence; non-convergence error; scores in `[0,100]`.

**Hand-off:** WS4 consumes `FDNAResult` for before/after; WS5 consumes hospital/
district score tables.

Report per the definition of done.
