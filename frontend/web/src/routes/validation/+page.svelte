<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type ValidationSeries } from '#lib/api.ts';
	import { num, pct, fixed } from '#lib/format.ts';
	import { COMPARTMENT } from '#lib/colors.ts';
	import Card from '#lib/components/Card.svelte';
	import LineChart from '#lib/components/LineChart.svelte';
	import Slider from '#lib/components/Slider.svelte';
	import More from '#lib/components/More.svelte';

	let data = $state<Record<string, ValidationSeries> | null>(null);
	let busy = $state(false);
	let err = $state<string | null>(null);
	let r0 = $state(1.95);
	let hosp = $state(1.08);
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function load() {
		busy = true;
		try {
			const omicron: Record<string, unknown> = {};
			if (Math.abs(r0 - 1.95) > 1e-9) omicron['disease.r0'] = r0;
			if (Math.abs(hosp - 1.08) > 1e-9) omicron['disease.hosp_scale'] = hosp;
			data = await api.validation({ omicron, winter: {} });
			err = null;
		} catch (e) {
			err = (e as Error).message;
		} finally {
			busy = false;
		}
	}
	function later() {
		clearTimeout(timer);
		timer = setTimeout(load, 200);
	}
	onMount(load);

	const ORDER = ['omicron', 'winter_icu', 'winter_inpatients'];
	const COLORS: Record<string, string> = { omicron: COMPARTMENT.H, winter_icu: COMPARTMENT.C, winter_inpatients: COMPARTMENT.H };
	const PANEL: Record<string, { title: string; sub: string }> = {
		omicron: {
			title: 'Omicron wave, winter 2021–22',
			sub: 'New hospital admissions each week. The model was tuned to this wave, so a close match is expected.'
		},
		winter_icu: {
			title: 'Winter 2020–21: patients in intensive care',
			sub: 'The model never saw this data, which makes it a fair test.'
		},
		winter_inpatients: {
			title: 'Winter 2020–21: all patients in hospital',
			sub: 'Also never seen. The model comes in too low here; the note at the bottom says why.'
		}
	};
	// The scorer's check names, said plainly.
	const CHECK: Record<string, string> = {
		'weeks within +-40%': 'Weeks within 40% of reality',
		'peak week offset': 'Busiest week lands on time',
		'peak height error': 'Height of the peak'
	};
	const BAR: Record<string, string> = {
		'>= 60% of weeks': 'needs 60% of weeks or more',
		'within +-1': 'needs to be within a week',
		'within +-25%': 'needs to be within 25%'
	};
	const SCORES = [
		{ k: 'mae', label: 'Mean abs. error', f: (v: number) => num(v, 1) },
		{ k: 'rmse', label: 'RMSE', f: (v: number) => num(v, 1) },
		{ k: 'mape', label: 'Mean abs. % error', f: (v: number) => pct(v, 0) },
		{ k: 'log_rmse', label: 'Log RMSE', f: (v: number) => fixed(v, 3) },
		{ k: 'bias', label: 'Bias', f: (v: number) => num(v, 1) }
	];
	const checkValue = (name: string, v: number) =>
		name.startsWith('weeks')
			? pct(v)
			: name.includes('offset')
				? v === 0
					? 'same week'
					: `${Math.abs(v)} wk ${v > 0 ? 'late' : 'early'}`
				: `${pct(Math.abs(v), 0)} ${v < 0 ? 'low' : 'high'}`;
</script>

<div class="page">
	<div class="page-head">
		<h1>Tested on real data</h1>
		<p>
			Does the model match what really happened? Here it replays two Massachusetts COVID waves and is laid over the real
			hospital numbers. As a yardstick there is also a lazy guess, “this week will look like last week”, which gets to
			peek at the real numbers; the model does not.
		</p>
	</div>

	<Card title="Try to break the fit" sub="The Omicron match comes from tuning two numbers. Move them and watch the match get worse.">
		<div class="knobs">
			<Slider label="How contagious (R₀)" value={r0} min={1.2} max={3} step={0.05} format={(v) => v.toFixed(2)} changed={Math.abs(r0 - 1.95) > 1e-9} onchange={(v) => ((r0 = v), later())} />
			<Slider label="How severe" value={hosp} min={0.3} max={3} step={0.02} format={(v) => `${v.toFixed(2)}×`} changed={Math.abs(hosp - 1.08) > 1e-9} onchange={(v) => ((hosp = v), later())} />
			<button class="btn" onclick={() => ((r0 = 1.95), (hosp = 1.08), load())} disabled={busy}>Back to the tuned values</button>
		</div>
	</Card>

	{#if err}<Card><div class="empty">{err}</div></Card>{/if}

	{#if data}
		{#each ORDER as key (key)}
			{@const v = data[key]}
			{@const m = v.score.mae}
			{@const n = v.naive_score.mae}
			<Card title={PANEL[key].title} sub={PANEL[key].sub}>
				{#snippet actions()}
					<span class="tag" class:pass={v.passed} class:fail={!v.passed}>{v.passed ? 'Passes' : 'Misses'}</span>
				{/snippet}
				<div class="vgrid">
					<LineChart
						dates={v.weeks}
						height={250}
						yMin={0}
						series={[
							{ id: 'obs', label: 'What happened', values: v.observed, color: '#f0efec' },
							{ id: 'model', label: 'Model', values: v.model, color: COLORS[key] },
							{ id: 'naive', label: 'Lazy guess (last week)', values: v.naive, color: '#898781', dashed: true, width: 1.5 }
						]}
					/>
					<div class="side">
						<div class="h">Checks</div>
						{#each v.checks.checks as c (c.name)}
							<div class="check">
								<span class="mark" class:ok={c.passed}>{c.passed ? '✓' : '✕'}</span>
								<span class="cn">{CHECK[c.name] ?? c.name}<small>{BAR[c.bar] ?? c.bar}</small></span>
								<b>{checkValue(c.name, c.value)}</b>
							</div>
						{/each}
						{#if m !== null && n !== null}
							<p class="miss">
								Typical weekly miss: <b>{num(m)}</b> for the model, <b>{num(n)}</b> for the lazy guess.
								{m < n ? 'The model does better.' : 'The lazy guess does better here.'}
							</p>
						{/if}
					</div>
				</div>
			</Card>
		{/each}

		<p class="muted note">
			Reading it honestly: the lazy guess has seen last week's real number, while the model sees nothing after its start
			date, and it was never tuned to the winter 2020–21 data at all. It comes in too low on all patients in hospital that
			winter because real patients stayed about 8.5 days for each admission, against the model's 6.8. Either stays were
			longer, or the hospital count includes patients the admissions data leaves out. The model keeps the published
			length of stay rather than being tuned to pass this test.
		</p>

		<More title="Error scores in detail" sub="Standard forecast-error measures for each panel, model against the lazy guess.">
			<table>
				<thead>
					<tr><th></th>{#each ORDER as key (key)}<th colspan="2">{PANEL[key].title}</th>{/each}</tr>
					<tr><th></th>{#each ORDER as key (key)}<th>model</th><th>lazy</th>{/each}</tr>
				</thead>
				<tbody>
					{#each SCORES as s (s.k)}
						<tr>
							<td>{s.label}</td>
							{#each ORDER as key (key)}
								{@const m = data[key].score[s.k]}
								{@const n = data[key].naive_score[s.k]}
								<td class:win={m !== null && n !== null && s.k !== 'bias' && Math.abs(m) < Math.abs(n)}>{m === null ? '–' : s.f(m)}</td>
								<td>{n === null ? '–' : s.f(n)}</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
			<p class="muted small">Green marks where the model's error is smaller. Bias is below zero when the model runs low.</p>
		</More>
	{:else if !err}
		<Card><div class="empty">Comparing with the real hospital data…</div></Card>
	{/if}
</div>

<style>
	.knobs {
		display: grid;
		grid-template-columns: 1fr 1fr auto;
		gap: 24px;
		align-items: end;
	}
	.vgrid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 300px;
		gap: 28px;
	}
	.h {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-3);
		margin-bottom: 8px;
	}
	.check {
		display: grid;
		grid-template-columns: 18px 1fr auto;
		gap: 8px;
		align-items: center;
		font-size: 12.5px;
		padding: 5px 0;
		border-bottom: 1px solid var(--line);
	}
	.mark {
		color: var(--serious);
		font-weight: 600;
	}
	.mark.ok {
		color: var(--good);
	}
	.cn {
		color: var(--text-2);
		display: flex;
		flex-direction: column;
	}
	.cn small {
		color: var(--text-3);
		font-size: 11px;
	}
	.check b {
		font-family: var(--mono);
		font-weight: 500;
		font-size: 12px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	th {
		text-align: right;
		color: var(--text-3);
		font-weight: 400;
		padding: 3px 0 3px 12px;
		font-size: 11.5px;
	}
	.miss {
		margin: 14px 0 0;
		font-size: 12.5px;
		line-height: 1.55;
		color: var(--text-2);
	}
	.miss b {
		color: var(--text-1);
		font-weight: 600;
	}
	.small {
		font-size: 11.5px;
		margin: 10px 0 0;
	}
	td {
		padding: 4px 0;
		color: var(--text-2);
		border-bottom: 1px solid var(--line);
	}
	td + td {
		text-align: right;
		padding-left: 12px;
		font-family: var(--mono);
		color: var(--text-1);
	}
	td.win {
		color: var(--good);
	}
	.note {
		font-size: 12.5px;
		line-height: 1.55;
		max-width: 820px;
		margin: 0;
	}
	@media (max-width: 1000px) {
		.vgrid,
		.knobs {
			grid-template-columns: 1fr;
		}
	}
</style>
