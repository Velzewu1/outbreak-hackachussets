<script lang="ts">
	import { onMount } from 'svelte';
	import { rn } from '#lib/rn.svelte.ts';
	import { fixed, longDate, shortDate } from '#lib/format.ts';
	import type { Strategy } from '#lib/rn-api.ts';
	import Card from '#lib/components/Card.svelte';
	import LineChart from '#lib/components/LineChart.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import More from '#lib/components/More.svelte';

	onMount(() => rn.loadEvaluation());

	const e = $derived(rn.evaluation);
	const ok = $derived(e?.status === 'verified');
	type Which = 'fixed_origin' | 'rolling_origin';
	let which = $state<Which>('rolling_origin');
	const strat = $derived<Strategy | undefined>(e?.[which]);
	const facilities = $derived(e?.facilities ?? {});
	const ccns = $derived(Object.keys(facilities).sort((a, b) => facilities[a].name.localeCompare(facilities[b].name)));
	let ccn = $state('');
	$effect(() => {
		if (!ccn && ccns.length) ccn = ccns.find((c) => facilities[c].hospitals.includes('MGH')) ?? ccns[0];
	});
	const rows = $derived((strat?.rows ?? []).filter((x) => x.ccn === ccn).sort((a, b) => a.target.localeCompare(b.target)));
	// every test week, so a week this hospital didn't report shows as a gap, not a straight line
	const targets = $derived([...new Set((strat?.rows ?? []).map((x) => x.target))].sort());
	const byTarget = $derived(new Map(rows.map((x) => [x.target, x])));
	const col = (k: 'observed' | 'model' | 'persistence') => targets.map((t) => byTarget.get(t)?.[k] ?? null);
	const verified = (s: Strategy | undefined) => ok && !!s && s.forecast_pairs > 0;
	const STRATS = $derived<{ key: Which; title: string; plain: string }[]>([
		{
			key: 'fixed_origin',
			title: 'One run, read ahead',
			plain: `Fit on the first ${e?.train_weeks ?? '–'} weeks, run once, compare the next ${e?.holdout_weeks ?? '–'} weeks.`
		},
		{ key: 'rolling_origin', title: 'One week ahead, refit each week', plain: 'Each week, refit on data up to that week only, then predict the next week.' }
	]);
	const perFacility = $derived(
		Object.entries(e?.fixed_origin?.per_facility ?? {})
			.map(([c, x]) => ({ ccn: c, name: facilities[c]?.name ?? c, ...x }))
			.sort((a, b) => b.model_mae - a.model_mae)
	);
	const changedFromFit = $derived(rn.changeCount > 0 || rn.dataset !== 'real');
</script>

<div class="page">
	<div class="page-head">
		<h1>Tested on real data</h1>
		<p>
			We asked the model to predict COVID patients in beds at each Suffolk County hospital for weeks it had not seen, using
			federal HHS hospital reports from October 2020 to May 2021, and compared it with the simplest possible guess: next week
			looks like this week.
		</p>
	</div>

	{#if !e}
		<Card>
			{#if rn.evalError}
				<p class="empty">The backtest isn't available: {rn.evalError}</p>
			{:else}
				<p class="empty"><span class="spin"></span> Running the backtest on the real data. The first time takes about 20 seconds.</p>
			{/if}
		</Card>
	{:else if !ok}
		<Card title="No historical test available">
			<p class="plain">
				The backtest hasn't been verified ({e.reason ?? e.status}), so no accuracy numbers are shown. Run
				<code>PYTHONPATH=. python scripts/run_backtest.py</code> from the repository root to compute it.
			</p>
		</Card>
	{:else}
		<div class="verdict">
			<b>The model loses to the simple guess.</b>
			In both tests its typical weekly miss is several times larger than "next week looks like this week". We report it as
			measured, with no tuning to the test weeks. The model is for exploring what-ifs, not for forecasting.
		</div>

		<div class="grid-2">
			{#each STRATS as s (s.key)}
				{@const st = e[s.key]}
				<Card title={s.title} sub={s.plain}>
					{#if verified(st)}
						<div class="heads">
							<div class="h"><span>Model's typical miss</span><b class="bad">{fixed(st!.model_mae_beds, 1)}</b><small>beds per hospital-week</small></div>
							<div class="h"><span>Simple guess's miss</span><b>{fixed(st!.persistence_mae_beds, 1)}</b><small>beds per hospital-week</small></div>
							<div class="h"><span>Weeks compared</span><b>{st!.forecast_pairs}</b><small>hospital-weeks</small></div>
						</div>
					{:else}
						<p class="empty">No numbers: this test isn't verified or compared no weeks.</p>
					{/if}
				</Card>
			{/each}
		</div>

		{#if changedFromFit}
			<p class="caveat">
				These numbers belong to the model as fitted (R₀ {fixed(e.fixed_origin?.fit?.fitted_r0, 2)} on the real data), not to
				the settings you are exploring now.
			</p>
		{/if}

		<Card title="One hospital, week by week" sub="COVID patients in beds, weekly average. Gaps are weeks the hospital didn't report.">
			{#snippet actions()}
				<Segmented options={STRATS.map((s) => ({ value: s.key, label: s.key === 'fixed_origin' ? 'One run' : 'Week ahead' }))} value={which} onchange={(w) => (which = w)} />
			{/snippet}
			<div class="picker">
				{#each ccns as c (c)}
					<button class:on={c === ccn} onclick={() => (ccn = c)}>{facilities[c].name}</button>
				{/each}
			</div>
			{#if rows.length}
				<LineChart
					dates={targets}
					height={250}
					series={[
						{ id: 'obs', label: 'Reported', values: col('observed'), color: '#f0efec', width: 2.5 },
						{ id: 'model', label: 'Model', values: col('model'), color: '#d55181' },
						{ id: 'naive', label: 'Next week = this week', values: col('persistence'), color: '#3987e5', dashed: true }
					]}
				/>
			{:else}
				<p class="empty">No valid reported weeks for this hospital in this test.</p>
			{/if}
		</Card>

		<Card title="Typical miss by hospital" sub="One-run test, beds per week. Lower is better.">
			<table>
				<thead><tr><th>Hospital</th><th>Weeks</th><th>Model</th><th>Simple guess</th></tr></thead>
				<tbody>
					{#each perFacility as f (f.ccn)}
						<tr>
							<td>{f.name}</td>
							<td>{f.n}</td>
							<td class="bad">{fixed(f.model_mae, 1)}</td>
							<td>{fixed(f.persistence_mae, 1)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<p class="muted small">Both Beth Israel Deaconess campuses report under one federal ID, so they are compared together.</p>
		</Card>

		<More title="How the test was run" sub="Periods, counts and rules">
			<div class="kvs">
				<div class="kv"><span>Data</span><b><a href={e.source_url} target="_blank" rel="noreferrer">HHS COVID-19 hospital capacity by facility</a></b></div>
				<div class="kv"><span>Period</span><b>{longDate(e.period?.[0])} to {longDate(e.period?.[1])} · {e.calendar_weeks} weeks</b></div>
				<div class="kv"><span>Fitting weeks / test weeks</span><b>{e.train_weeks} / {e.holdout_weeks}</b></div>
				<div class="kv"><span>Hospitals matched</span><b>{e.matched_facilities}</b></div>
				<div class="kv"><span>Hospital-weeks dropped (missing or suppressed)</span><b>{e.excluded_records}</b></div>
				<div class="kv"><span>Minimum reporting days per week</span><b>{e.min_coverage_days}</b></div>
				<div class="kv"><span>Week-ahead test uses only past data</span><b>{e.rolling_origin?.leakage_free ? 'yes' : 'no'}</b></div>
				<div class="kv"><span>Fitted R₀ (one-run test)</span><b>{fixed(e.fixed_origin?.fit?.fitted_r0, 2)}</b></div>
				<div class="kv"><span>All hospitals together: model / simple guess</span><b>{fixed(e.fixed_origin?.regional_model_mae_beds, 1)} / {fixed(e.fixed_origin?.regional_persistence_mae_beds, 1)} beds</b></div>
			</div>
			<p class="muted small">{e.fixed_origin?.strategy}.</p>
			<p class="muted small">{e.rolling_origin?.strategy}.</p>
			<p class="muted small">Observation: {e.fixed_origin?.observation_operator}.</p>
			<p class="muted small">Test weeks start {shortDate(targets[0])}. {e.honest_note}</p>
		</More>
	{/if}
</div>

<style>
	.verdict {
		border: 1px solid rgb(236 131 90 / 0.45);
		background: rgb(236 131 90 / 0.08);
		border-radius: 12px;
		padding: 12px 16px;
		font-size: 13px;
		line-height: 1.55;
		color: var(--text-2);
		max-width: 980px;
	}
	.verdict b {
		color: #ffb199;
		margin-right: 4px;
	}
	.heads {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
	}
	.h {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.h span {
		font-size: 12px;
		color: var(--text-3);
	}
	.h b {
		font-size: 24px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.h small {
		font-size: 11px;
		color: var(--text-3);
	}
	.bad {
		color: #ff8a8a !important;
	}
	.caveat {
		margin: 0;
		font-size: 12.5px;
		color: var(--text-3);
		border-left: 2px solid var(--warning);
		padding-left: 10px;
	}
	.picker {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: 12px;
	}
	.picker button {
		border: 1px solid var(--line-2);
		background: transparent;
		color: var(--text-3);
		font: inherit;
		font-size: 12px;
		padding: 4px 10px;
		border-radius: 999px;
		cursor: pointer;
	}
	.picker button:hover {
		color: var(--text-1);
	}
	.picker button.on {
		background: var(--elev);
		color: var(--text-1);
		border-color: #4a4a52;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12.5px;
		font-variant-numeric: tabular-nums;
	}
	th,
	td {
		padding: 6px 8px;
		border-bottom: 1px solid var(--line);
		text-align: right;
	}
	th:first-child,
	td:first-child {
		text-align: left;
	}
	th {
		color: var(--text-3);
		font-weight: 500;
	}
	td {
		color: var(--text-2);
	}
	.kvs {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.kv {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		font-size: 12.5px;
		color: var(--text-3);
	}
	.kv b {
		color: var(--text-1);
		font-weight: 500;
		text-align: right;
	}
	.kv a {
		color: inherit;
	}
	.small {
		font-size: 11.5px;
		line-height: 1.5;
		margin: 8px 0 0;
	}
	.plain {
		font-size: 13px;
		color: var(--text-2);
		line-height: 1.55;
		margin: 0;
	}
	code {
		font-family: var(--mono);
		font-size: 12px;
		background: var(--bg);
		padding: 1px 5px;
		border-radius: 4px;
	}
	.empty {
		text-align: left;
		padding: 8px 0;
		display: flex;
		gap: 10px;
		align-items: center;
	}
	.spin {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		border: 2px solid var(--line-2);
		border-top-color: var(--text-1);
		animation: spin 0.7s linear infinite;
		display: inline-block;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
