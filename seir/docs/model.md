# Model notes

## Compartments and flows

The state is people per `[compartment, patch, age]`. The default structure,
`seir_h()`, is S-E-I-R plus ward (H), ICU (C) and death (D):

| move | rate per day | daily flow |
|---|---|---|
| S → E | force of infection λ | `new_exposed` |
| E → I | σ = 1 / latent period | `new_infectious` |
| I → R | γ (1 − p_hosp) | `new_recovered` |
| I → H | γ p_hosp | `new_hosp` |
| H → C | p_icu / ward stay | `new_icu` |
| H → R | (1 − p_icu) / ward stay | `ward_discharges` |
| C → D | p_death_icu / ICU stay | `new_deaths` |
| C → R | (1 − p_death_icu) / ICU stay | `icu_discharges` |

`p_hosp` is per infection and by age, multiplied by `disease.hosp_scale`.
Hospital patients do not transmit. Structures are data: `with_waning`,
`with_vaccination` and `with_asymptomatic` add compartments without engine
changes, and `examples/extend_model.py` adds an admission-delay stage.

Every run outputs compartments, flows and the day-averaged rates:
`transmission_rate` (β), `incubation_rate` (σ), `recovery_rate` (γ),
`force_of_infection`, the hospital shares and exits, and `r_eff`.

## Force of infection

    λ[p, a] = β(t) Σ_r W[p, r] Σ_b C[a, b] I_loc[r, b] / N_loc[r, b]

`C` is daily contacts by age (Prem 2021 for the Massachusetts scenarios),
`W[p, r]` is the share of time residents of patch p spend in location r,
and `I_loc`, `N_loc` count infectious and all people present in r. The
operator is applied in factored form, so cost grows with patches × ages and
`W` can be sparse. β(t) = β0 × a contact multiplier (mobility, a policy
timeline, or a feedback signal).

## R0, R_eff, β0

R_eff = ρ(diag(S_eff · β · D) M), the dominant eigenvalue of the
next-generation matrix, where D is infectiousness-weighted days infectious
per infection (exact for any chain of exponential stages) and S_eff weights
susceptibles by how easily they are infected. β0 is solved so the
scenario's R0 holds for whatever structure and mixing it uses. Growth rates
come from the Euler-Lotka equation, so for plain SEIR
(1 + r/σ)(1 + r/γ) = R. `python -m cascade.epi info` prints all of these.

## Time step

Each day has `sim.substeps` substeps (4 by default). A compartment's
outflow is split between its exits in proportion to their rates. Infection
uses p = 1 − exp(−λ dt), the exact chance for a held force of infection;
every later stay uses p = rate × dt, which keeps each mean stay at exactly
1 / rate. The usual choice, 1 − exp(−rate dt) everywhere (the reference
code's), adds about dt/2 to every stay, which inflates R0 and the hospital
census. Against an accurate ODE solve (`tests/test_engine.py` checks this):

| case, 4 substeps | final size | peak inpatients |
|---|---|---|
| covid-like, this engine | 0.0% | +0.5%, 1 day late |
| covid-like, 1 − exp everywhere | +1.1% | +3.2% |
| flu-like, this engine | 0.0% | +0.2% |
| flu-like, 1 − exp everywhere | +4.6% | +9.8% |

The chain-binomial stepper draws whole people with the same probabilities.

## FDNA plug

`SEIRModule` runs inside the shared `Simulation` loop and writes a frozen
`EpiSnapshot` (prevalence, admissions, ICU transfers, census, the three
rates, R_eff, all per patch) to `state.epi` each day. Other layers write
multipliers to `state.signals["seir"]`; SEIR reads them the next morning.
Standard channels (`rates.FEEDBACK`): `icu_mortality_multiplier` →
p_death_icu, `hosp_multiplier` → p_hosp, `contact_multiplier` → β.
Probabilities are clipped to [0, 1].

## Presets

| preset | R0 | latent (d) | infectious (d) | p_hosp 0-17 / 18-64 / 65+ | p_icu | p_death_icu | ward (d) | ICU (d) |
|---|---|---|---|---|---|---|---|---|
| `covid_ancestral` | 2.9 | 3 | 5 | 0.001 / 0.015 / 0.1 | 0.2 | 0.3 | 5 | 9 |
| `covid_omicron` | 1.95 | 2 | 4 | 0.0005 / 0.004 / 0.03 | 0.1 | 0.25 | 4 | 6 |
| `influenza_seasonal` | 1.28 | 1 | 4.8 | 0.0015 / 0.002 / 0.02 | 0.15 | 0.3 | 4 | 6 |
| `influenza_pandemic_2009` | 1.46 | 1 | 4.8 | 0.002 / 0.002 / 0.004 | 0.2 | 0.3 | 4 | 7 |
| `measles` | 15 | 10 | 8 | 0.2 (all ages) | 0.05 | 0.2 | 4 | 7 |

Sources with DOIs are in `cascade/epi/presets.py` (`SOURCES`) and printed by
`python -m cascade.epi presets`. Values marked approximate there have no
single source.

## Known limitations

- Stays are exponential, so lengths of stay are means, not medians.
- The I stage also covers time from becoming infectious to admission, so
  the generation time (latent + infectious) is longer than measured ones
  (8 d for covid_ancestral against 5.2 d in Ganyani 2020).
- One immune share for all ages; immunity does not wane unless
  `with_waning` is used.
- Admissions alone cannot separate prior immunity, R0 and severity
  (docs/validation.md), so one of them has to come from outside the data.
