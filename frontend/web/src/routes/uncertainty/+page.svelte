<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { api, type EnsembleResult, type SensitivityRow } from '#lib/api.ts';
	import { num, pct } from '#lib/format.ts';
	import { COMPARTMENT } from '#lib/colors.ts';
	import Card from '#lib/components/Card.svelte';
	import Stat from '#lib/components/Stat.svelte';
	import LineChart from '#lib/components/LineChart.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Slider from '#lib/components/Slider.svelte';
	import Tornado from '#lib/components/Tornado.svelte';

	// ---- ensemble
	let runs = $state(40);
	let seed = $state(0);
	let ens = $state<EnsembleResult | null>(null);
	let ensBusy = $state(false);
	let ensErr = $state<string | null>(null);
	let variable = $state('inpatients');

	const VARS: Record<string, { label: string; peak: string; color: string; fmt: (v: number) => string }> = {
		inpatients: { label: 'In hospital', peak: 'Most in hospital at once', color: COMPARTMENT.H, fmt: (v) => num(v) },
		icu: { label: 'In intensive care', peak: 'Most in intensive care at once', color: COMPARTMENT.C, fmt: (v) => num(v, 1) },
		new_hosp: { label: 'Admitted per day', peak: 'Most admitted in one day', color: COMPARTMENT.H, fmt: (v) => num(v, 1) },
		infections: { label: 'New infections per day', peak: 'Most new infections in one day', color: COMPARTMENT.I, fmt: (v) => num(v) },
		new_deaths: { label: 'Deaths per day', peak: 'Most deaths in one day', color: COMPARTMENT.D, fmt: (v) => num(v, 2) }
	};

	async function runEnsemble() {
		// Each press after the first rolls new luck.
		if (ens) seed = (seed + 1) % 100;
		ensBusy = true;
		ensErr = null;
		try {
			ens = await api.ensemble({ ...app.changes(), runs, seed });
		} catch (e) {
			ensErr = (e as Error).message;
		} finally {
			ensBusy = false;
		}
	}

	const band = $derived(ens?.bands[variable]);
	const v = $derived(VARS[variable]);
	const peaks = $derived(ens?.peaks[variable] ?? []);
	const peakStats = $derived.by(() => {
		const xs = peaks.filter((x): x is number => x !== null).sort((a, b) => a - b);
		if (!xs.length) return null;
		const q = (p: number) => xs[Math.min(xs.length - 1, Math.floor(p * xs.length))];
		return { lo: q(0.05), med: q(0.5), hi: q(0.95) };
	});
	const hist = $derived.by(() => {
		const xs = peaks.filter((x): x is number => x !== null);
		if (!xs.length) return [];
		const lo = Math.min(...xs),
			hi = Math.max(...xs);
		const n = 16;
		const w = (hi - lo) / n || 1;
		const bins = Array.from({ length: n }, (_, i) => ({ x0: lo + i * w, count: 0 }));
		xs.forEach((x) => bins[Math.min(n - 1, Math.floor((x - lo) / w))].count++);
		return bins;
	});
	const histMax = $derived(Math.max(1, ...hist.map((b) => b.count)));

	// ---- sensitivity
	const PARAMS = [
		'disease.r0',
		'disease.latent_period',
		'disease.infectious_period',
		'disease.hosp_scale',
		'disease.los_ward',
		'disease.los_icu',
		'disease.p_icu',
		'disease.p_death_icu',
		'seeding.immune_share'
	];
	const PARAM_LABEL: Record<string, string> = {
		'disease.r0': 'How contagious',
		'disease.latent_period': 'Days before contagious',
		'disease.infectious_period': 'Days contagious',
		'disease.hosp_scale': 'How severe',
		'disease.los_ward': 'Days on a ward',
		'disease.los_icu': 'Days in intensive care',
		'disease.p_icu': 'Chance of needing intensive care',
		'disease.p_death_icu': 'Chance of dying in intensive care',
		'seeding.immune_share': 'Already immune'
	};
	const METRICS = [
		{ value: 'peak_inpatients', label: 'Most in hospital at once' },
		{ value: 'peak_icu', label: 'Most in intensive care at once' },
		{ value: 'peak_admissions', label: 'Most admitted in one day' },
		{ value: 'attack_rate', label: 'Share of people ever infected' },
		{ value: 'deaths', label: 'Deaths' }
	];
	let metric = $state('peak_inpatients');
	let rel = $state(0.25);
	let chosen = $state<string[]>(PARAMS.slice(0, 6));
	let sens = $state<{ rows: SensitivityRow[]; metric: string; rel: number } | null>(null);
	let sensBusy = $state(false);
	let sensErr = $state<string | null>(null);

	async function runSensitivity() {
		sensBusy = true;
		sensErr = null;
		try {
			const params = chosen.filter((p) => typeof app.epiValue(p) === 'number' || Array.isArray(app.epiValue(p)));
			sens = await api.sensitivity({ ...app.changes(), params, metric, rel });
		} catch (e) {
			sensErr = (e as Error).message;
		} finally {
			sensBusy = false;
		}
	}
	const sensFmt = $derived(sens?.metric === 'attack_rate' ? (x: number) => pct(x, 1) : (x: number) => num(x, 1));

	$effect(() => {
		void app.scenarioId;
		ens = null;
		sens = null;
	});
</script>

<div class="page">
	<div class="page-head">
		<h1>Range of outcomes</h1>
		<p>
			The map shows one possible outbreak. Real outbreaks involve luck, and several of the numbers that go into the
			model are educated guesses. This page shows how far the answer could move because of either. Both use your
			current <b>What if…?</b> settings.
		</p>
	</div>

	<Card title="What luck can do" sub="The same outbreak, run many times with chance at every step: who meets whom, who gets sick enough for hospital. The thin lines are single runs. The shaded band holds 9 in 10 of them and the bright line is the middle one.">
		{#snippet actions()}
			<button class="btn" class:primary={!ens} onclick={runEnsemble} disabled={ensBusy}>
				{ensBusy ? `Running ${runs} outbreaks…` : ens ? 'Roll again' : `Run ${runs} outbreaks`}
			</button>
		{/snippet}
		<div class="ensgrid">
			<div class="knobs">
				<Slider label="How many runs" help="More runs give a smoother range but take longer." value={runs} min={10} max={200} step={10} format={(x) => String(x)} onchange={(x) => (runs = Math.round(x))} />
				{#if ens}
					<div class="stats one">
						<Stat label="Outbreaks that took off" value={pct(ens.takeoff_share)} hint="in the rest, it fizzled out early by chance" />
						{#if peakStats}
							<Stat label={v.peak} value={v.fmt(peakStats.med)} hint={`in a typical run; 9 in 10 runs fall between ${v.fmt(peakStats.lo)} and ${v.fmt(peakStats.hi)}`} />
						{/if}
					</div>
					{#if hist.length}
						<div class="hist" aria-label="How the highest point varies across runs">
							{#each hist as b, i (i)}
								<span style:height="{(b.count / histMax) * 100}%" title="{v.fmt(b.x0)}: {b.count} runs"></span>
							{/each}
						</div>
						<div class="histlab muted">Where the highest point landed in each run, low to high</div>
					{/if}
				{/if}
			</div>
			<div class="chart">
				<Segmented
					options={Object.entries(VARS).map(([value, x]) => ({ value, label: x.label }))}
					value={variable}
					onchange={(x) => (variable = x)}
				/>
				{#if ensErr}<div class="empty">{ensErr}</div>{/if}
				{#if ens && band}
					<LineChart
						dates={ens.dates}
						height={320}
						marker={app.day}
						onscrub={(i) => (app.day = i)}
						yFormat={v.fmt}
						bands={[
							{ lo: band[0], hi: band[4], color: v.color, opacity: 0.12 },
							{ lo: band[1], hi: band[3], color: v.color, opacity: 0.22 }
						]}
						series={[
							...(ens.samples[variable] ?? []).map((s, i) => ({ id: `s${i}`, label: `run ${i + 1}`, values: s, color: v.color, muted: true })),
							{ id: 'p95', label: 'High end (1 in 20 runs above)', values: band[4], color: v.color, width: 0 },
							{ id: 'med', label: 'Middle run', values: band[2], color: v.color },
							{ id: 'p5', label: 'Low end (1 in 20 runs below)', values: band[0], color: v.color, width: 0 }
						]}
						legend={false}
					/>
				{:else if !ensBusy}
					<div class="empty tall">Press <b>Run {runs} outbreaks</b> to see the range. It takes a few seconds.</div>
				{:else}
					<div class="empty tall">Simulating…</div>
				{/if}
			</div>
		</div>
	</Card>

	<Card title="Which guesses matter most" sub="Each number is moved down and up by the same amount while everything else stays put. The longer the bar, the more the result depends on getting that number right.">
		{#snippet actions()}
			<button class="btn" class:primary={!sens} onclick={runSensitivity} disabled={sensBusy || !chosen.length}>
				{sensBusy ? 'Running…' : sens ? 'Run again' : 'Compare'}
			</button>
		{/snippet}
		<div class="sensgrid">
			<div class="knobs">
				<label class="field"
					><span>Result to watch</span>
					<select class="input" bind:value={metric}>
						{#each METRICS as m (m.value)}<option value={m.value}>{m.label}</option>{/each}
					</select>
				</label>
				<Slider label="Move each number by" value={rel} min={0.05} max={0.5} step={0.05} format={(x) => `±${Math.round(x * 100)}%`} onchange={(x) => (rel = x)} />
				<div class="params">
					<span class="ph">Numbers to compare</span>
					{#each PARAMS as p (p)}
						<label class="chk"
							><input
								type="checkbox"
								checked={chosen.includes(p)}
								onchange={(e) =>
									(chosen = (e.currentTarget as HTMLInputElement).checked ? [...chosen, p] : chosen.filter((x) => x !== p))}
							/>{PARAM_LABEL[p]}</label
						>
					{/each}
				</div>
			</div>
			<div>
				{#if sensErr}<div class="empty">{sensErr}</div>{/if}
				{#if sens}
					<Tornado rows={sens.rows} format={sensFmt} rel={sens.rel} label={(p) => PARAM_LABEL[p] ?? p} />
				{:else if !sensBusy}
					<div class="empty tall">Pick the numbers and a result, then press <b>Compare</b>.</div>
				{:else}
					<div class="empty tall">Simulating…</div>
				{/if}
			</div>
		</div>
	</Card>
</div>

<style>
	.ensgrid,
	.sensgrid {
		display: grid;
		grid-template-columns: 240px minmax(0, 1fr);
		gap: 28px;
	}
	.chart {
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-width: 0;
	}
	.stats.one {
		grid-template-columns: 1fr;
		margin-top: 14px;
		gap: 14px;
	}
	.hist {
		display: flex;
		align-items: flex-end;
		gap: 2px;
		height: 60px;
		margin-top: 16px;
	}
	.hist span {
		flex: 1;
		background: var(--text-2);
		opacity: 0.6;
		border-radius: 2px 2px 0 0;
		min-height: 1px;
	}
	.histlab {
		font-size: 11px;
		margin-top: 4px;
	}
	.tall {
		padding: 90px 0;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 12.5px;
		color: var(--text-2);
		margin-bottom: 6px;
	}
	.params {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin-top: 10px;
	}
	.ph {
		font-size: 12.5px;
		color: var(--text-2);
		margin-bottom: 2px;
	}
	.chk {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12.5px;
		color: var(--text-2);
		cursor: pointer;
	}
	.chk input {
		accent-color: var(--accent);
	}
	@media (max-width: 900px) {
		.ensgrid,
		.sensgrid {
			grid-template-columns: 1fr;
		}
	}
</style>
