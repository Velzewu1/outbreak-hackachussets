# Validation

Reproduce everything here with `python examples/calibrate_massachusetts.py`
(about a minute); `--save docs/seir_baseline.json` writes the numbers. This is
the SEIR-only baseline the full system should beat. Pass bars are the
writeup's: weekly values within ±40% for at least 60% of weeks, peak week
within ±1, peak height within ±25%.

## 1. Omicron wave, Massachusetts (fit)

HHS weekly admissions, 11 weeks ending 25 Dec 2021 to 5 Mar 2022. Fixed:
covid_omicron periods and stays, Prem 2021 contacts, 22% protected on 1 Dec
2021 (Klaassen 2023). Fitted: R0 1.95, hosp_scale 1.08, seed 71,300.
Result: every week within 40% (most within 17%), peak week exact, peak
height −16%. **PASS**.

## 2. Backtest as a forecast

Fit only up to a date, predict the rest:

| fitted up to | severity | weeks within 40% | peak week | peak height | result |
|---|---|---|---|---|---|
| 8 Jan 2022 | fitted | 50% | 0 | −15% | FAIL |
| 8 Jan 2022 | from preset | 100% | 0 | −6% | PASS |
| 15 Jan 2022 | fitted | 57% | 0 | +21% | FAIL |
| 15 Jan 2022 | from preset | 100% | 0 | +13% | PASS |

Early weeks cannot tell how many infections stand behind each admission, so
with severity free the forecast misses the turn. The preset's severity was
set before any fitting, and the full-wave fit later agreed with it
(hosp_scale 1.08).

## 3. Why immunity can't be fitted

Refitting the whole wave at different prior immunity gives the same fit
every time:

| immune on 1 Dec | R0 | hosp_scale | fit cost | R_eff on 1 Dec | infected by 5 Mar |
|---|---|---|---|---|---|
| 0% | 1.52 | 0.84 | 0.0611 | 1.50 | 54% |
| 22% | 1.95 | 1.08 | 0.0611 | 1.50 | 42% |
| 40% | 2.53 | 1.41 | 0.0611 | 1.50 | 32% |
| 50% | 3.04 | 1.69 | 0.0611 | 1.50 | 27% |

Admissions fix R_eff and admissions per susceptible, nothing more. With
preset severity the forecasts pass for 15% to 30% immunity and fail at 0%
and 50%, so the literature value (22%) matters.

Cross-check that nothing was fitted to: by mid-February the model has
infected 51% of children, 42% of adults 18-64 and 24% of people 65+.
US serology over Dec 2021 to Feb 2022 (Clarke 2022) shows the same
gradient: new infections in children about 1.2 times, and in 65+ about 0.56
times, the adult rate (model: 1.22 and 0.57). The model's overall level is
higher than serology's 24-point rise, which the authors say undercounts
(no reinfections, weaker antibody response after vaccination).

## 4. Out of sample: winter 2020-21

Fitted to admissions only (23 weeks, covid_ancestral, 5% immune): R0 1.40,
hosp_scale 0.51; admissions **PASS**. Census never fitted, scored against
the COVID Tracking Project:

| series | weeks within 40% | peak week | peak height | result |
|---|---|---|---|---|
| ICU census | 96% | 0 | 0% | PASS |
| all inpatients | 83% | 0 | −26% | **FAIL** |

The ward census falls short. Observed census per daily admission was about
8.5 days at the peak against the model's 6.8-day mean stay. Either ward
stays were longer than the 5-day preset or the census counted patients the
admissions series doesn't (probable cases, infections caught in hospital).
A 6-day ward stay would pass (peak −17%) and 7 days would match (−6%), but
that would be tuning to the test, so the scenario keeps the literature
value.

## 5. Mobility

Driving β with Google transit mobility (`omicron_2021_mobility.yaml`)
improves the in-sample fit (cost 0.061 → 0.050) but not forecasts: with
severity free the peak lands 4 weeks late; with preset severity forecasts
pass with or without mobility. The main scenario leaves it out.

## 6. Sensitivity (±25%, peak inpatients)

| input | Omicron elasticity | winter elasticity |
|---|---|---|
| R0 | +3.41 | +5.18 |
| immune share | −1.29 | −0.38 |
| hosp_scale | +1.00 | +1.00 |
| ward stay | +0.84 | +0.73 |
| infectious period | −0.65 | −0.62 |
| latent period | −0.32 | −0.36 |
| p_icu | +0.12 | +0.26 |
| ICU stay | +0.11 | +0.24 |
| seed | +0.11 | +0.05 |
| age contacts (scaled) | 0 | 0 |

R0 dominates, most of all when R_eff is near 1 (winter). Scaling contacts
changes nothing because β0 is re-solved to keep R0.

## Sources

- Klaassen 2023, population immunity against Omicron, https://doi.org/10.1093/cid/ciad210
- Clarke 2022, US infection-induced seroprevalence, https://doi.org/10.15585/mmwr.mm7117e3
- Wiegand 2022, US seroprevalence trends, https://doi.org/10.1016/j.lana.2022.100403
- Lambrou 2022, Delta to Omicron takeover, https://doi.org/10.15585/mmwr.mm7106a4
- Prem 2021, contact matrices, https://doi.org/10.1371/journal.pcbi.1009098
