<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { num, pct, fixed, days, shortDate } from '#lib/format.ts';
	import { COMPARTMENT, LABEL, SERIES, heatColor } from '#lib/colors.ts';
	import Card from '#lib/components/Card.svelte';
	import Stat from '#lib/components/Stat.svelte';
	import LineChart, { type LineSeries } from '#lib/components/LineChart.svelte';
	import Heatmap from '#lib/components/Heatmap.svelte';
	import BarList from '#lib/components/BarList.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import More from '#lib/components/More.svelte';

	// Plain names for this page's charts.
	const PLAIN: Record<string, string> = {
		E: 'Caught it, not yet contagious',
		I: 'Contagious',
		H: 'On a hospital ward',
		C: 'In intensive care'
	};

	const r = $derived(app.result!);
	const e = $derived(r.epi);
	const d = $derived(r.describe);
	const t = $derived(Math.min(app.day, e.dates.length - 1));
	const city = $derived(e.citywide);
	const pop = $derived(e.summary.population);
	const scrub = (i: number) => (app.day = i);

	const comp = (c: string, scale = 1): LineSeries => ({
		id: c,
		label: PLAIN[c] ?? LABEL[c] ?? c,
		values: (city[c] ?? []).map((v) => (v === null ? null : v * scale)),
		color: COMPARTMENT[c] ?? '#888'
	});

	// Realised rates: what the run actually did, next to the rates it was given.
	const obs = $derived(e.observed_rates);
	const recoveredObs = $derived(
		obs.new_recovered?.map((v, i) => (v === null ? null : v + (obs.new_hosp?.[i] ?? 0))) ?? []
	);

	const rateCards = $derived([
		{
			id: 'transmission_rate',
			title: 'Transmission rate β',
			sub: 'Infection probability per contact-day, β(t) = β₀ × contact multiplier; β₀ is solved so the scenario hits its R₀',
			values: e.rates.transmission_rate ?? [],
			observed: null as (number | null)[] | null,
			color: COMPARTMENT.I,
			hint: `R₀ ${fixed(d.r0, 2)}`
		},
		{
			id: 'incubation_rate',
			title: 'Incubation rate σ',
			sub: 'Share of the exposed who become infectious each day, 1 / latent period',
			values: e.rates.incubation_rate ?? [],
			observed: obs.new_infectious ?? null,
			color: COMPARTMENT.E,
			hint: d.incubation_rate ? `latent period ${days(1 / d.incubation_rate)}` : ''
		},
		{
			id: 'recovery_rate',
			title: 'Recovery rate γ',
			sub: 'Rate of leaving the infectious state, to recovery or hospital, 1 / infectious period',
			values: e.rates.recovery_rate ?? [],
			observed: recoveredObs,
			color: COMPARTMENT.R,
			hint: d.recovery_rate ? `infectious period ${days(1 / d.recovery_rate)}` : ''
		}
	]);

	let popView = $state<'share' | 'count'>('share');
	let patchMetric = $state<'prevalence' | 'attack_rate' | 'inpatients'>('prevalence');
	const patches = $derived(r.geo.patches.map((p) => p.id));
	const patchGrid = $derived.by(() => {
		const g = e.by_patch[patchMetric] ?? e.by_patch.prevalence;
		if (patchMetric === 'inpatients')
			return g.map((row) => row.map((v, p) => ((v ?? 0) / r.geo.patches[p].population) * 1e5));
		return g;
	});
	const patchFmt = $derived(
		patchMetric === 'inpatients' ? (v: number) => `${num(v, 1)} per 100k` : (v: number) => pct(v, v < 0.1 ? 2 : 1)
	);
	const PATCH_LEGEND = { prevalence: 'share contagious', attack_rate: 'share infected so far', inpatients: 'in hospital per 100k' };
	const reff = $derived(e.rates.r_eff?.[t] ?? null);
	const selIdx = $derived(app.selectedPatch ? patches.indexOf(app.selectedPatch) : -1);

	const peakRows = $derived(
		patches
			.map((id, p) => {
				const col = e.by_patch.prevalence.map((row) => row[p] ?? 0);
				let best = 0;
				col.forEach((v, i) => v > col[best] && (best = i));
				return { id, label: id, value: e.by_patch.attack_rate[e.dates.length - 1]?.[p] ?? 0, note: shortDate(e.dates[best]) };
			})
			.sort((a, b) => b.value - a.value)
	);
</script>

<div class="page">
	<div class="page-head">
		<h1>How it spreads</h1>
		<p>
			How many people catch it, when, and where in the city. Drag across any chart to move the day; the map and the
			other pages follow.
		</p>
	</div>

	<Card>
		<div class="stats">
			<Stat
				label="Each case infects, today"
				value={fixed(reff, 1)}
				hint={reff === null ? '' : reff > 1 ? 'above 1: growing' : 'below 1: shrinking'}
			/>
			<Stat label="Ever infected" value={pct(e.summary.attack_rate, 0)} hint={`${num(e.summary.infections)} people`} />
			{#if e.summary.peak_inpatients !== undefined}
				<Stat
					label="Most in hospital at once"
					value={num(e.summary.peak_inpatients)}
					hint={`on ${shortDate(e.summary.peak_inpatients_date)}`}
					dot={COMPARTMENT.H}
				/>
			{/if}
			{#if e.summary.deaths !== undefined}
				<Stat label="Deaths" value={num(e.summary.deaths)} dot={COMPARTMENT.D} />
			{/if}
		</div>
	</Card>

	<div class="grid-2">
		<Card title="People who have it" sub="Citywide, each day.">
			<LineChart dates={e.dates} height={220} marker={t} onscrub={scrub} series={[comp('E'), comp('I')]} />
		</Card>
		{#if city.H}
			<Card title="People in hospital" sub="Citywide, each day.">
				<LineChart dates={e.dates} height={220} marker={t} onscrub={scrub} series={[comp('H'), comp('C')]} />
			</Card>
		{:else}
			<Card title="Each case infects" sub="Above 1 the outbreak grows; below 1 it shrinks.">
				<LineChart dates={e.dates} height={220} marker={t} onscrub={scrub} refLine={{ value: 1, label: '1' }} yMin={0} yFormat={(v) => fixed(v, 1)} series={[{ id: 'reff', label: 'Each case infects', values: e.rates.r_eff ?? [], color: COMPARTMENT.I, area: true }]} />
			</Card>
		{/if}
	</div>

	{#if patches.length > 1}
		<Card title="Neighborhood by neighborhood" sub="Each row is a neighborhood, each column a day; brighter means more. Click a row to compare it with the city below.">
			{#snippet actions()}
				<Segmented
					options={[
						{ value: 'prevalence', label: 'Sick now' },
						{ value: 'attack_rate', label: 'Infected so far' },
						...(e.by_patch.inpatients ? [{ value: 'inpatients' as const, label: 'In hospital' }] : [])
					]}
					value={patchMetric}
					onchange={(v) => (patchMetric = v)}
				/>
			{/snippet}
			<Heatmap
				rows={patches}
				dates={e.dates}
				values={patchGrid}
				color={heatColor}
				format={patchFmt}
				marker={t}
				selected={app.selectedPatch}
				onrow={(p) => (app.selectedPatch = app.selectedPatch === p ? null : p)}
				onscrub={scrub}
				legend={PATCH_LEGEND[patchMetric]}
			/>
		</Card>

		{#if selIdx >= 0}
			<Card title={`${app.selectedPatch} compared with the whole city`} sub="Share of residents who are contagious.">
				<LineChart
					dates={e.dates}
					height={220}
					marker={t}
					onscrub={scrub}
					yFormat={(v) => pct(v, 1)}
					series={[
						{ id: 'city', label: 'Whole city', values: city.infectious.map((v) => (v ?? 0) / pop), color: '#c3c2b7', dashed: true, width: 1.5 },
						{ id: 'sel', label: app.selectedPatch!, values: e.by_patch.prevalence.map((row) => row[selIdx]), color: COMPARTMENT.I }
					]}
				/>
			</Card>
		{/if}
	{/if}

	<div class="grid-2">
		<Card title="Who catches it, by age" sub="Share of each age group infected over the whole run.">
			<BarList
				items={e.ages.map((a, i) => ({ id: a, label: a, value: e.by_age.attack_rate[i] ?? 0 }))}
				format={(v) => pct(v, 0)}
				color={COMPARTMENT.I}
			/>
		</Card>
		{#if e.by_age.new_hosp}
			<Card title="Who ends up in hospital, by age" sub="New hospital admissions per day.">
				<LineChart
					dates={e.dates}
					height={180}
					marker={t}
					onscrub={scrub}
					series={e.ages.map((a, i) => ({ id: a, label: a, values: e.by_age.new_hosp![i], color: SERIES[i] }))}
				/>
			</Card>
		{/if}
	</div>

	<More title="Technical detail" sub="Model rates, growth, force of infection and the full compartments, for modellers.">
		<div class="stats tech">
			<Stat label="R₀" value={fixed(d.r0, 2)} hint="fully susceptible" />
			<Stat label="Rₑff on day 0" value={fixed(d.r_eff_start, 2)} hint="with prior immunity" />
			<Stat label="Generation time" value={days(d.generation_time_days)} hint="latent + infectious" />
			<Stat
				label="Doubling time"
				value={d.doubling_time_start ? days(d.doubling_time_start) : '—'}
				hint={d.growth_rate_start !== undefined ? `growth ${fixed(d.growth_rate_start, 3)}/day at start` : ''}
			/>
		</div>

		<div class="grid-3">
			{#each rateCards as rc (rc.id)}
				<Card title={rc.title} sub={rc.sub}>
					<div class="rateval">
						<span class="big">{fixed(rc.values[t], 4)}</span><span class="muted">per day · {rc.hint}</span>
					</div>
					<LineChart
						dates={e.dates}
						height={130}
						marker={t}
						onscrub={scrub}
						yMin={0}
						yFormat={(v) => fixed(v, 3)}
						series={[
							{ id: 'given', label: 'Rate in the model', values: rc.values, color: rc.color },
							...(rc.observed
								? [{ id: 'obs', label: 'Realised in the run', values: rc.observed, color: '#c3c2b7', dashed: true, width: 1.5 }]
								: [])
						]}
					/>
				</Card>
			{/each}
		</div>

		<div class="grid-2">
			<Card title="Effective reproduction number Rₑff" sub="Secondary infections per infection given today's immunity.">
				<LineChart
					dates={e.dates}
					height={200}
					marker={t}
					onscrub={scrub}
					refLine={{ value: 1, label: 'R = 1' }}
					yMin={0}
					yFormat={(v) => fixed(v, 1)}
					series={[{ id: 'reff', label: 'Rₑff', values: e.rates.r_eff ?? [], color: COMPARTMENT.I, area: true }]}
				/>
			</Card>
			<Card title="Force of infection" sub="Per-capita rate at which susceptible people are infected, citywide.">
				<LineChart
					dates={e.dates}
					height={200}
					marker={t}
					onscrub={scrub}
					yMin={0}
					yFormat={(v) => fixed(v, 3)}
					series={[{ id: 'foi', label: 'Force of infection', values: e.rates.force_of_infection ?? [], color: COMPARTMENT.E, area: true }]}
				/>
			</Card>
		</div>

		<div class="grid-2">
			<Card title="Susceptible and recovered">
				{#snippet actions()}
					<Segmented
						options={[
							{ value: 'share', label: '% of people' },
							{ value: 'count', label: 'People' }
						]}
						value={popView}
						onchange={(v) => (popView = v)}
					/>
				{/snippet}
				<LineChart
					dates={e.dates}
					height={200}
					marker={t}
					onscrub={scrub}
					yFormat={popView === 'share' ? (v) => pct(v) : (v) => num(v)}
					yMax={popView === 'share' ? 1 : undefined}
					series={[comp('S', popView === 'share' ? 1 / pop : 1), comp('R', popView === 'share' ? 1 / pop : 1)]}
				/>
			</Card>
			{#if city.H}
				<Card title="Admissions per day" sub="New hospital admissions, citywide.">
					<LineChart
						dates={e.dates}
						height={200}
						marker={t}
						onscrub={scrub}
						series={[{ id: 'adm', label: 'Admissions', values: city.new_hosp ?? [], color: COMPARTMENT.H, area: true }]}
					/>
				</Card>
			{/if}
		</div>

		{#if patches.length > 1}
			<Card title="Ever infected by the end, by neighborhood" sub="Right: the day the neighborhood peaked.">
				<BarList
					items={peakRows}
					format={(v) => pct(v, 1)}
					color={COMPARTMENT.I}
					selected={app.selectedPatch}
					onselect={(id) => (app.selectedPatch = app.selectedPatch === id ? null : id)}
				/>
			</Card>
		{/if}
	</More>
</div>

<style>
	.rateval {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin: -4px 0 8px;
	}
	.big {
		font-size: 22px;
		font-weight: 600;
		font-family: var(--mono);
		letter-spacing: -0.02em;
	}
	.rateval .muted {
		font-size: 12px;
	}
	.tech {
		padding: 4px 2px;
	}
</style>
