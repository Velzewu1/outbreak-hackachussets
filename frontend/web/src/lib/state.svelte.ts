// One shared app state: the scenario, the changes the controls make, and the latest run.
import {
	api,
	type Changes,
	type FdnaEvent,
	type Presets,
	type RunResult,
	type ScenarioDetail,
	type ScenarioInfo
} from './api';

export type MapMetric = 'prevalence' | 'attack_rate' | 'inpatients' | 'access_loss';

class AppState {
	scenarios = $state<ScenarioInfo[]>([]);
	presets = $state<Presets | null>(null);
	scenarioId = $state('boston_city');
	detail = $state<ScenarioDetail | null>(null);

	// Changes on top of the scenario file, as dotted paths (same as the CLI's --set).
	epi = $state<Record<string, unknown>>({});
	system = $state<Record<string, unknown>>({});
	events = $state<FdnaEvent[]>([]);
	seedScale = $state(1);

	result = $state<RunResult | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	lastRunMs = $state(0);

	day = $state(0);
	playing = $state(false);
	selectedPatch = $state<string | null>(null);
	selectedHospital = $state<string | null>(null);
	mapMetric = $state<MapMetric>('inpatients');
	controlsOpen = $state(false);

	#abort: AbortController | null = null;
	#timer: ReturnType<typeof setTimeout> | null = null;

	get isSystem() {
		return this.detail?.kind === 'system';
	}

	get nDays() {
		return this.result?.epi.dates.length ?? 0;
	}

	get date() {
		return this.result?.epi.dates[Math.min(this.day, this.nDays - 1)] ?? '';
	}

	get changeCount() {
		return (
			Object.keys(this.epi).length +
			Object.keys(this.system).length +
			this.events.length +
			(this.seedScale !== 1 ? 1 : 0)
		);
	}

	/** The request body for any endpoint: scenario plus every change. */
	changes(): Changes {
		const epi: Record<string, unknown> = { ...this.epi };
		const exposed = this.detail?.epi.seeding.exposed;
		if (this.seedScale !== 1 && exposed) {
			epi['seeding.exposed'] = Object.fromEntries(
				Object.entries(exposed).map(([k, v]) => [k, v * this.seedScale])
			);
		}
		return {
			scenario: this.scenarioId,
			epi,
			system: this.isSystem ? { ...this.system } : {},
			events: this.isSystem ? $state.snapshot(this.events) : null
		};
	}

	async init() {
		const [list, presets] = await Promise.all([api.scenarios(), api.presets()]);
		this.scenarios = list;
		this.presets = presets;
		await this.load(this.scenarioId);
	}

	async load(id: string) {
		this.scenarioId = id;
		this.epi = {};
		this.system = {};
		this.events = [];
		this.seedScale = 1;
		this.selectedPatch = null;
		this.selectedHospital = null;
		this.detail = await api.scenario(id);
		this.day = 0;
		await this.run();
		if (this.result) this.day = peakDay(this.result);
	}

	setEpi(path: string, value: unknown) {
		this.epi = { ...this.epi, [path]: value };
		if (path === 'disease.preset') {
			// a new pathogen starts from its preset: drop the old disease's tweaks
			this.epi = Object.fromEntries(
				Object.entries(this.epi).filter(([k]) => !k.startsWith('disease.') || k === 'disease.preset')
			);
		}
		this.schedule();
	}

	setSystem(path: string, value: unknown) {
		this.system = { ...this.system, [path]: value };
		this.schedule();
	}

	setSeedScale(v: number) {
		this.seedScale = v;
		this.schedule();
	}

	addEvent(e: FdnaEvent) {
		this.events = [...this.events.filter((x) => x.node !== e.node), e];
		this.schedule(0);
	}

	removeEvent(node: string) {
		this.events = this.events.filter((x) => x.node !== node);
		this.schedule(0);
	}

	reset() {
		this.epi = {};
		this.system = {};
		this.events = [];
		this.seedScale = 1;
		this.schedule(0);
	}

	/** Current value of a disease or sim field: the change if any, else the scenario's. */
	epiValue<T = number>(path: string): T | undefined {
		if (path in this.epi) return this.epi[path] as T;
		let node: unknown = this.detail?.epi;
		for (const k of path.split('.')) node = (node as Record<string, unknown> | undefined)?.[k];
		return node as T;
	}

	systemValue<T = number>(path: string): T | undefined {
		if (path in this.system) return this.system[path] as T;
		let node: unknown = this.detail?.system;
		for (const k of path.split('.')) node = (node as Record<string, unknown> | undefined)?.[k];
		return node as T;
	}

	schedule(delay = 250) {
		if (this.#timer) clearTimeout(this.#timer);
		this.#timer = setTimeout(() => this.run(), delay);
	}

	async run() {
		this.#abort?.abort();
		const ctrl = new AbortController();
		this.#abort = ctrl;
		this.loading = true;
		const t0 = performance.now();
		try {
			const res = await api.run(this.changes(), ctrl.signal);
			this.result = res;
			this.error = null;
			this.day = Math.min(this.day, res.epi.dates.length - 1);
			this.lastRunMs = performance.now() - t0;
		} catch (e) {
			if ((e as Error).name !== 'AbortError') this.error = (e as Error).message;
		} finally {
			if (this.#abort === ctrl) this.loading = false;
		}
	}
}

export function peakDay(r: RunResult): number {
	const s = r.epi.citywide.inpatients ?? r.epi.citywide.infectious;
	let best = 0;
	s.forEach((v, i) => {
		if ((v ?? 0) > (s[best] ?? 0)) best = i;
	});
	return best;
}

export const app = new AppState();
