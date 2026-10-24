// Typed client for frontend/api. Every number arrives as a plain JSON array.

export type Series = (number | null)[];
export type Grid = (number | null)[][]; // [time][patch|hospital|node]

export interface ScenarioInfo {
	id: string;
	kind: 'system' | 'epi';
	title: string;
	blurb: string;
}

export interface Place {
	id: string;
	lat: number | null;
	lon: number | null;
}
export interface PatchGeo extends Place {
	population: number;
	vulnerability: number;
	/** [lon, lat] well inside the neighborhood outline, for its name. */
	label: [number, number] | null;
}
export interface HospitalGeo extends Place {
	name: string;
	ward_beds: number;
	icu_beds: number;
	er: boolean;
	baseline_occupancy: number;
}
export interface Geo {
	patches: PatchGeo[];
	hospitals: HospitalGeo[];
	mappable: boolean;
	/** Neighborhood outlines, feature id = patch index; null when the scenario has none. */
	districts: GeoJSON.FeatureCollection<GeoJSON.Polygon | GeoJSON.MultiPolygon, { patch: string }> | null;
}

export interface Describe {
	compartments: string[];
	population: number;
	transmission_rate: number;
	incubation_rate: number | null;
	recovery_rate: number | null;
	r0: number;
	generation_time_days: number;
	growth_rate_per_day: number;
	doubling_time_days: number | null;
	r_eff_start?: number;
	growth_rate_start?: number;
	doubling_time_start?: number | null;
	patches: number;
	age_groups: number;
}

export interface EpiSummary {
	start: string;
	end: string;
	days: number;
	population: number;
	infections: number;
	attack_rate: number;
	r_eff_start: number;
	r_eff_end: number;
	peak_infectious: number;
	peak_infectious_date: string;
	admissions?: number;
	peak_admissions?: number;
	peak_admissions_date?: string;
	peak_inpatients?: number;
	peak_inpatients_date?: string;
	peak_icu?: number;
	peak_icu_date?: string;
	deaths?: number;
}

export interface EpiResult {
	dates: string[];
	compartments: string[];
	ages: string[];
	summary: EpiSummary;
	citywide: Record<string, Series>;
	rates: Record<string, Series | null>;
	observed_rates: Record<string, Series>;
	by_patch: Record<string, Grid>;
	by_age: { infections: Grid; attack_rate: Series; new_hosp?: Grid };
}

export interface SystemSummary {
	peak_occupancy_icu: number;
	hospital_days_on_diversion: number;
	diverted_patients: number;
	overflow_patients: number;
	lost_access_person_days: number;
	weighted_access_loss: number;
	deaths: number;
}

export interface SystemResult {
	summary: SystemSummary;
	hospitals: string[];
	nodes: string[];
	edges: { src: string; dst: string; sod: number; cod: number }[];
	shares: number[][]; // [patch][hospital]
	travel: number[][];
	occupancy_ward: Grid;
	occupancy_icu: Grid;
	operability: Grid;
	on_diversion: (boolean | number)[][];
	access: Grid;
	lost_person_days: Grid;
	weighted_loss: Grid;
	diverted_patients: Series;
	overflow: Series;
	node_operability: Grid;
	arrivals: Grid;
}

export interface RunResult {
	scenario: string;
	describe: Describe;
	geo: Geo;
	epi: EpiResult;
	system: SystemResult | null;
}

export interface FdnaEvent {
	node: string;
	value: number;
	start: number;
	end: number | null;
}

export interface Changes {
	scenario: string;
	epi: Record<string, unknown>;
	system: Record<string, unknown>;
	events: FdnaEvent[] | null;
}

export interface ScenarioDetail extends ScenarioInfo {
	epi: {
		disease: Record<string, unknown> & { name: string; r0: number };
		population: { patches: string[]; ages: string[]; counts: number[][] };
		seeding: { exposed: Record<string, number>; immune_share: number | Record<string, number> };
		sim: { start: string; days: number; substeps: number; stochastic: boolean };
	};
	system?: {
		rerouting: { p_on: number; p_off: number; occ_on: number; occ_off: number; min_open: number };
		allocation: { decay: number };
		fdna: Record<string, unknown> & { staff_absence_per_prevalence: number; icu_strain_mortality: number };
		events: FdnaEvent[];
		network: { hospitals: { id: string; ward_beds: number; icu_beds: number; baseline_occupancy: number }[] };
	};
	describe: Describe;
	geo: Geo;
}

export interface EnsembleResult {
	dates: string[];
	runs: number;
	quantiles: number[];
	takeoff_share: number;
	bands: Record<string, Grid>; // [quantile][time]
	samples: Record<string, Grid>; // [run][time]
	peaks: Record<string, Series>;
}

export interface SensitivityRow {
	parameter: string;
	base_value: number | number[];
	metric_low: number;
	metric_base: number;
	metric_high: number;
	swing: number;
	elasticity: number | null;
}

export interface CriticalityRow {
	node: string;
	loss: number;
	extra_loss: number;
}

export interface Check {
	name: string;
	value: number;
	bar: string;
	passed: boolean;
}
export interface ValidationSeries {
	label: string;
	weeks: string[];
	observed: Series;
	model: Series;
	naive: Series;
	checks: { checks: Check[]; passed: boolean };
	passed: boolean;
	score: Record<string, number | null>;
	naive_score: Record<string, number | null>;
	params: { r0: number; hosp_scale: number };
}

export interface Presets {
	diseases: Record<string, Record<string, unknown> & { name: string; r0: number }>;
	sources: Record<string, string>;
}

async function call<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
	const res = await fetch(`/api/${path}`, {
		method: body === undefined ? 'GET' : 'POST',
		headers: body === undefined ? undefined : { 'content-type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body),
		signal
	});
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const j = await res.json();
			detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
		} catch {
			/* keep statusText */
		}
		throw new Error(detail);
	}
	return res.json() as Promise<T>;
}

export const api = {
	scenarios: () => call<ScenarioInfo[]>('scenarios'),
	scenario: (id: string) => call<ScenarioDetail>(`scenario/${id}`),
	presets: () => call<Presets>('presets'),
	run: (c: Changes, signal?: AbortSignal) => call<RunResult>('run', c, signal),
	ensemble: (c: Changes & { runs: number; seed: number }) => call<EnsembleResult>('ensemble', c),
	sensitivity: (c: Changes & { params: string[]; metric: string; rel: number }) =>
		call<{ metric: string; rel: number; rows: SensitivityRow[] }>('sensitivity', c),
	criticality: (c: Changes & { level: number }) =>
		call<{ level: number; rows: CriticalityRow[] }>('criticality', c),
	validation: (body: { omicron: Record<string, unknown>; winter: Record<string, unknown> }) =>
		call<Record<string, ValidationSeries>>('validation', body)
};
