<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { api, type EnsembleResult, type SensitivityRow } from '#lib/api.ts';
	import { num, pct, fixed } from '#lib/format.ts';
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

	const VARS: Record<string, { label: string; color: string; fmt: (v: number) => string }> = {
		infections: { label: 'New infections', color: COMPARTMENT.I, fmt: (v) => num(v) },
		new_hosp: { label: 'Admissions', color: COMPARTMENT.H, fmt: (v) => num(v, 1) },
		inpatients: { label: 'Inpatients', color: COMPARTMENT.H, fmt: (v) => num(v) },
		icu: { label: 'ICU', color: COMPARTMENT.C, fmt: (v) => num(v, 1) },
		new_deaths: { label: 'Deaths / day', color: COMPARTMENT.D, fmt: (v) => num(v, 2) },
		r_eff: { label: 'Rₑff', color: COMPARTMENT.I, fmt: (v) => fixed(v, 2) }
	};

	async function runEnsemble() {
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
	const METRICS = [
		{ value: 'peak_inpatients', label: 'Peak inpatients' },
		{ value: 'peak_icu', label: 'Peak ICU' },
		{ value: 'attack_rate', label: 'Attack rate' },
		{ value: 'deaths', label: 'Deaths' },
		{ value: 'peak_admissions', label: 'Peak admissions' }
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
		<h1>Uncertainty</h1>
		<p>
			Two questions: how much does chance alone move the outcome (stochastic chain-binomial runs of the same scenario),
			and which assumptions move it most (one input at a time, ± a share of its value). Both use the epidemic layer
			with your current controls.
		</p>
	</div>

	<Card title="Stochastic ensemble" sub="Each run draws its own random infections, recoveries and admissions. Bands show the 5–95% and 25–75% ranges across runs.">
		{#snippet actions()}
			<button class="btn" class:primary={!ens} onclick={runEnsemble} disabled={ensBusy}>
				{ensBusy ? `Running ${runs} runs…` : ens ? 'Re-run' : 'Run ensemble'}
			</button>
		{/snippet}
		<div class="ensgrid">
			<div class="knobs">
				<Slider label="Runs" value={runs} min={10} max={200} step={10} format={(x) => String(x)} onchange={(x) => (runs = Math.round(x))} />
				<Slider label="Random seed" value={seed} min={0} max={99} step={1} format={(x) => String(x)} onchange={(x) => (seed = Math.round(x))} />
				{#if ens}
					<div class="stats one">
						<Stat label="Runs that took off" value={pct(ens.takeoff_share)} hint="the rest died out by chance" />
						{#if peakStats}
							<Stat
								label={`Peak ${v.label.toLowerCase()}`}
								value={v.fmt(peakStats.med)}
								hint={`90% of runs: ${v.fmt(peakStats.lo)} – ${v.fmt(peakStats.hi)}`}
							/>
						{/if}
					</div>
					{#if hist.length}
						<div class="hist" aria-label="Distribution of peaks">
							{#each hist as b, i (i)}
								<span style:height="{(b.count / histMax) * 100}%" title="{v.fmt(b.x0)}: {b.count} runs"></span>
							{/each}
						</div>
						<div class="histlab muted">Peaks across runs</div>
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
						refLine={variable === 'r_eff' ? { value: 1, label: 'R = 1' } : null}
						bands={[
							{ lo: band[0], hi: band[4], color: v.color, opacity: 0.12 },
							{ lo: band[1], hi: band[3], color: v.color, opacity: 0.22 }
						]}
						series={[
							...(ens.samples[variable] ?? []).map((s, i) => ({ id: `s${i}`, label: `run ${i}`, values: s, color: v.color, muted: true })),
							{ id: 'p95', label: '95th percentile', values: band[4], color: v.color, width: 0 },
							{ id: 'med', label: 'Median', values: band[2], color: v.color },
							{ id: 'p5', label: '5th percentile', values: band[0], color: v.color, width: 0 }
						]}
						legend={false}
					/>
				{:else if !ensBusy}
					<div class="empty tall">Run the ensemble to see the spread. 40 runs take a few seconds.</div>
				{:else}
					<div class="empty tall">Simulating…</div>
				{/if}
			</div>
		</div>
	</Card>

	<Card title="Sensitivity" sub="Each input at −/+ the chosen share, others held at their current values. ε is the elasticity: % change in the output per % change in the input.">
		{#snippet actions()}
			<button class="btn" class:primary={!sens} onclick={runSensitivity} disabled={sensBusy || !chosen.length}>
				{sensBusy ? 'Running…' : sens ? 'Re-run' : 'Run sensitivity'}
			</button>
		{/snippet}
		<div class="sensgrid">
			<div class="knobs">
				<label class="field"
					><span>Output</span>
					<select class="input" bind:value={metric}>
						{#each METRICS as m (m.value)}<option value={m.value}>{m.label}</option>{/each}
					</select>
				</label>
				<Slider label="Move each input by" value={rel} min={0.05} max={0.5} step={0.05} format={(x) => `±${Math.round(x * 100)}%`} onchange={(x) => (rel = x)} />
				<div class="params">
					{#each PARAMS as p (p)}
						<label class="chk"
							><input
								type="checkbox"
								checked={chosen.includes(p)}
								onchange={(e) =>
									(chosen = (e.currentTarget as HTMLInputElement).checked ? [...chosen, p] : chosen.filter((x) => x !== p))}
							/>{p.split('.')[1].replaceAll('_', ' ')}</label
						>
					{/each}
				</div>
			</div>
			<div>
				{#if sensErr}<div class="empty">{sensErr}</div>{/if}
				{#if sens}
					<Tornado rows={sens.rows} format={sensFmt} rel={sens.rel} />
				{:else if !sensBusy}
					<div class="empty tall">Pick inputs and an output, then run. About two runs per input.</div>
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
	.chk {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12.5px;
		color: var(--text-2);
		text-transform: capitalize;
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
