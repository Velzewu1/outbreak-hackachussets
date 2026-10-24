# Data

Small public extracts, so the tests, the examples and the calibration run
offline. Each file below says where it comes from, what was done to it and
under what terms it can be reused. Loaders for every file are in
`cascade/epi/data.py`; nothing else in the package reads raw column names.

Downloaded on 24 October 2026 unless stated otherwise.

| file | what it is | used by |
|---|---|---|
| `hhs_ma_daily_admissions.csv` | daily new COVID admissions, Massachusetts, Jul 2020 to Apr 2024 | calibration target (`omicron_2021.yaml`, `winter_2020.yaml`) |
| `ctp_ma_hospital_census.csv` | COVID inpatients and ICU patients per day, Massachusetts, to 7 Mar 2021 | out-of-sample check of the winter 2020-21 fit |
| `google_mobility_massachusetts.csv` | Google mobility, Massachusetts, Feb 2020 to Feb 2022 | contact multiplier in `omicron_2021_mobility.yaml` |
| `google_mobility_suffolk.csv` | the same for Suffolk County (Boston) | available for a Boston-only run |
| `nyt_suffolk_county.csv` | cumulative cases and deaths, Suffolk County, 2020 to 2022 | `data.nyt_county()`; a case series for Boston |
| `places_ma_counties_2023.csv` | CDC PLACES risk factors, 14 Massachusetts counties | `data.places_comorbidity_multiplier()` |
| `prem2021_usa_contacts_all.csv` | age contact matrix, United States, all settings, 16 age groups | `mixing.age_contacts` in every Massachusetts scenario |

## hhs_ma_daily_admissions.csv

Columns `date, location, location_name, value`; `location` 25 is
Massachusetts; `value` is new confirmed COVID-19 admissions that day.

- Source: HHS "COVID-19 Reported Patient Impact and Hospital Capacity by
  State Timeseries" (HealthData.gov, dataset g62h-syeh), as processed by the
  COVID-19 Forecast Hub into
  `data-truth/truth-Incident Hospitalizations.csv` in
  https://github.com/reichlab/covid19-forecast-hub
- Processing by the Forecast Hub (its data-truth README): `value` is
  `previous_day_admission_adult_covid_confirmed` plus
  `previous_day_admission_pediatric_covid_confirmed`, moved one day earlier
  so the date is the day of admission. Suspected cases are left out.
- Processing here: kept the rows for location 25. `data.weekly()` sums
  them into MMWR weeks (Sunday to Saturday) for fitting.
- Terms: HHS data are a work of the US federal government (public domain).

Notes: these are patients with confirmed COVID-19 when admitted, so in the
Omicron wave they include people admitted for something else who tested
positive. The daily series is complete from 14 July 2020 (one isolated row
on 1 July); the fits use October 2020 onwards.

## ctp_ma_hospital_census.csv

Columns `date, state, hospitalizedCurrently, inIcuCurrently`: COVID-19
patients in hospital, and in ICU, on each day.

- Source: The COVID Tracking Project at The Atlantic, `states_daily_4pm_et.csv`
  from https://github.com/COVID19Tracking/covid-tracking-data (collection
  ended 7 March 2021).
- Processing: Massachusetts rows only, dates as ISO, these two columns.
- Terms: CC BY 4.0. Attribution: The COVID Tracking Project at The Atlantic.

Notes: the Project reported each state's own definition of a COVID-19
inpatient, which can include probable cases and patients who caught
COVID-19 in hospital; the admissions file counts confirmed admissions only.
docs/validation.md comes back to this where the model's census falls short
of the observed peak.

## google_mobility_massachusetts.csv, google_mobility_suffolk.csv

Columns `date` and six place categories (`retail_and_recreation`,
`grocery_and_pharmacy`, `parks`, `transit_stations`, `workplaces`,
`residential`), each a percent change from the median of the same weekday
over 3 Jan to 6 Feb 2020.

- Source: Google COVID-19 Community Mobility Reports, through the mirror
  `google_reports/mobility_report_US.csv` in
  https://github.com/ActiveConclusion/COVID19_mobility (Google stopped
  publishing the reports in October 2022).
- Processing: the Massachusetts state total and Suffolk County rows, these
  columns, 15 Feb 2020 to 1 Feb 2022.
- Terms: Google's terms of service. Attribution as Google asks: Google LLC
  "Google COVID-19 Community Mobility Reports".
  https://www.google.com/covid19/mobility/ Accessed: 24 October 2026.

`ContactMultiplier(percent_change=True, baseline_dates=[...])` turns a
column into a contact multiplier around 1.0; `omicron_2021_mobility.yaml`
shows it. MBTA gated entries can replace it with `csv:`, `column:` and
`baseline:`.

## nyt_suffolk_county.csv

Columns `date, county, state, fips, cases, deaths`, cumulative.

- Source: The New York Times, `us-counties-2020.csv`, `us-counties-2021.csv`
  and `us-counties-2022.csv` from https://github.com/nytimes/covid-19-data
- Processing: Suffolk County, Massachusetts rows from each year, stacked.
  `data.nyt_county()` turns them into daily counts and sets downward
  corrections to zero.
- Terms: CC BY-NC 4.0 (non-commercial use). Attribution: "Data from The New
  York Times, based on reports from state and local health agencies."

## places_ma_counties_2023.csv

Columns `year, county, measure, prevalence, low, high, population`: crude
prevalence (%) with its 95% interval for five adult measures, by county.

- Source: CDC PLACES county data (data.cdc.gov dataset swc5-untb), as saved
  in the project's healthcare starter kit on 18 October 2026
  (`healthcare/places/`); the request URL is in that kit's README.
- Processing: none; copied as is.
- Terms: CDC data, public domain.

`data.places_comorbidity_multiplier()` turns obesity, diabetes and smoking
prevalence into a hospitalisation multiplier for one county against the
state, for `disease.hosp_scale`. Its elasticity (0.5) is an assumption.

## prem2021_usa_contacts_all.csv

One row per five-year age group (`0-4` ... `75+`): `age`, `population`
(people in the group) and the mean daily contacts of a person that age with
each age group (columns, same order).

- Source: Prem K, et al. Projecting contact matrices in 177 geographical
  regions: an update and comparison with empirical data for the COVID-19
  era. PLoS Comput Biol 2021;17(7):e1009098.
  https://doi.org/10.1371/journal.pcbi.1009098 . Matrix `contact_all`
  (home, work, school and other settings together), country USA, from
  `generate_synthetic_matrices/output/syntheticmatrices/contact_all.rdata`
  in https://github.com/kieshaprem/synthetic-contact-matrices
- Population: the same repository's
  `generate_synthetic_matrices/input/pop/popage_total2020.csv` (UN World
  Population Prospects 2019, United States, 2020), with 75 and over added
  into one group.
- Processing: values rounded to four decimals.
- Terms: the paper is open access under CC BY 4.0 and the repository is
  GPL-3.0; cite the paper when you use the matrix.

`data.age_contacts_from_csv(path, [0, 18, 65], population)` collapses it to
the project's three age bands and makes it reciprocal for the scenario's
population (contacts of A with B equal contacts of B with A). That is where
the `age_contacts` in the Massachusetts scenarios come from:

```
         0-17   18-64   65+
0-17     9.00    8.09   0.96
18-64    2.50   10.47   1.18
65+      1.11    4.40   1.80
```
