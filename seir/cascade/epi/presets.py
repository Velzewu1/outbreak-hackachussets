"""Disease presets: starting values for DiseaseParams, one entry per pathogen.

Use one from YAML with `disease: {preset: covid_omicron}` and override any
field next to it, e.g. `disease: {preset: covid_omicron, r0: 2.4}`.

These are planning defaults, not fitted values. Periods and R0 come from the
sources in SOURCES; hospital shares are per infection, rounded, and meant to
be rescaled by calibration (DiseaseParams.hosp_scale). Age-specific values
use the project's three age bands. A scenario with other bands must give its
own per-age values.

Three things to know when reading or changing them:

  * `latent_period` is time to becoming infectious, which is shorter than
    the clinical incubation period (time to symptoms) for diseases with
    pre-symptomatic spread. The engine calls 1 / latent_period the
    incubation rate, as SEIR models usually do.
  * Stays are exponential, so lengths of stay are means, not medians. For
    the right-skewed stays seen in hospitals the mean is well above the
    median (Rees 2020: ICU median 7 days, IQR 4-11, mean about 9).
  * In seir_h() the I compartment also covers the time from becoming
    infectious to hospital admission, so the generation time (latent +
    infectious period) comes out longer than measured ones: 8 days for
    covid_ancestral against 5.2 (Ganyani 2020). The presets keep the longer
    delay because admissions are what the model is fitted to. R0 values are
    tied to the generation time they were estimated with and to the
    behaviour of their time and place (covid_ancestral: France before
    lockdown; covid_omicron: Massachusetts in December 2021), so treat r0 as
    a starting point for calibration; `python -m cascade.epi info` prints the
    growth rate and doubling time a scenario implies.
"""
from __future__ import annotations

AGE_BANDS = ("0-17", "18-64", "65+")


def _bands(young: float, adult: float, old: float) -> dict[str, float]:
    return dict(zip(AGE_BANDS, (young, adult, old)))


DISEASES: dict[str, dict] = {
    "covid_ancestral": dict(
        name="covid_ancestral",
        r0=2.9,                       # France before lockdown, Salje 2020
        latent_period=3.0,            # incubation median 5.1 d (Lauer 2020) minus ~2 d of
                                      # pre-symptomatic spread (about half of transmission, Ganyani 2020)
        infectious_period=5.0,        # generation time 8 d here; 5.2 d measured (Ganyani 2020), see above
        p_hosp=_bands(0.001, 0.015, 0.10),   # ~2.6% of infections overall; Salje 2020 reports 2.9%
        p_icu=0.2,                    # approximate
        p_death_icu=0.3,              # approximate
        los_ward=5.0,                 # Rees 2020 outside China: hospital stay median 5 (IQR 3-9), mean ~7;
                                      # here 5 + p_icu * los_icu = 6.8 days on average
        los_icu=9.0,                  # Rees 2020 outside China: ICU median 7 (IQR 4-11), mean ~9
    ),
    "covid_omicron": dict(
        name="covid_omicron",
        r0=1.95,                      # fitted to Massachusetts admissions, Dec 2021-Mar 2022, with 22% of
                                      # people protected at the start (Klaassen 2023; scenarios/omicron_2021.yaml)
        latent_period=2.0,            # BA.1 incubation mean 3.4-3.5 d (Wu 2022, Xu 2023) minus pre-symptomatic spread
        infectious_period=4.0,        # generation time 6 d here; BA.1 intrinsic 6.84 d, realised 2.99 d (Xu 2023)
        # Per infection in the largely vaccinated and previously infected
        # population of winter 2021-22: about 0.3 x covid_ancestral. An
        # assumption built from Omicron being ~0.4 x as likely as Delta to put
        # a case in hospital (Nyberg 2022) and vaccination lowering it further.
        p_hosp=_bands(0.0005, 0.004, 0.03),
        p_icu=0.1,                    # approximate
        p_death_icu=0.25,             # approximate
        los_ward=4.0,                 # NSW Omicron-Delta wave, ward-only stays 2.2 / 3.9 / 7.6 d by age (Tobin 2023)
        los_icu=6.0,                  # approximate
    ),
    "influenza_seasonal": dict(
        name="influenza_seasonal",
        r0=1.28,                      # median seasonal R, Biggerstaff 2014
        latent_period=1.0,            # shedding rises 0.5-1 d after challenge, Carrat 2008
        infectious_period=4.8,        # mean shedding duration, Carrat 2008
        p_hosp=_bands(0.0015, 0.002, 0.02),  # approximate
        p_icu=0.15,                   # approximate
        p_death_icu=0.3,              # approximate
        los_ward=4.0,                 # approximate
        los_icu=6.0,                  # approximate
    ),
    "influenza_pandemic_2009": dict(
        name="influenza_pandemic_2009",
        r0=1.46,                      # median 2009 pandemic R, Biggerstaff 2014
        latent_period=1.0,            # as seasonal influenza, Carrat 2008
        infectious_period=4.8,
        p_hosp=_bands(0.002, 0.002, 0.004),  # approximate; younger skew than seasonal flu
        p_icu=0.2,                    # approximate
        p_death_icu=0.3,              # approximate
        los_ward=4.0,                 # approximate
        los_icu=7.0,                  # approximate
    ),
    "measles": dict(
        name="measles",
        r0=15.0,                      # often cited 12-18; Guerra 2017 finds a wider range
        latent_period=10.0,           # textbook values, approximate
        infectious_period=8.0,        # approximate
        p_hosp=0.2,                   # about 1 in 5 unvaccinated cases in the US is hospitalised (CDC), approximate
        p_icu=0.05,                   # approximate
        p_death_icu=0.2,              # approximate
        los_ward=4.0,                 # approximate
        los_icu=7.0,                  # approximate
    ),
}

# Where the numbers come from (DOIs found through PubMed). Values marked
# "approximate" in the comments above have no single source.
SOURCES = {
    "Lauer 2020, incubation period of COVID-19": "https://doi.org/10.7326/M20-0504",
    "Ganyani 2020, COVID-19 generation interval": "https://doi.org/10.2807/1560-7917.ES.2020.25.17.2000257",
    "Salje 2020, burden of SARS-CoV-2 in France": "https://doi.org/10.1126/science.abc3517",
    "Rees 2020, COVID-19 length of hospital stay": "https://doi.org/10.1186/s12916-020-01726-3",
    "Wu 2022, incubation period by SARS-CoV-2 variant": "https://doi.org/10.1001/jamanetworkopen.2022.28008",
    "Xu 2023, incubation, serial interval and generation time by variant": "https://doi.org/10.1186/s12916-023-03070-8",
    "Backer 2022, Omicron BA.1 serial interval": "https://doi.org/10.2807/1560-7917.ES.2022.27.6.2200042",
    "Nyberg 2022, Omicron vs Delta severity": "https://doi.org/10.1016/S0140-6736(22)00462-7",
    "Tobin 2023, length of stay in an Omicron-Delta epidemic": "https://doi.org/10.1186/s12879-022-07971-6",
    "Biggerstaff 2014, influenza reproduction numbers": "https://doi.org/10.1186/1471-2334-14-480",
    "Carrat 2008, influenza infection time lines": "https://doi.org/10.1093/aje/kwm375",
    "Guerra 2017, measles R0": "https://doi.org/10.1016/S1473-3099(17)30307-9",
    "Klaassen 2023, US population immunity against Omicron": "https://doi.org/10.1093/cid/ciad210",
}
