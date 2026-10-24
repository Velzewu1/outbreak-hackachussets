<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type ValidationSeries } from '#lib/api.ts';
	import { num, pct, fixed } from '#lib/format.ts';
	import { COMPARTMENT } from '#lib/colors.ts';
	import Card from '#lib/components/Card.svelte';
	import LineChart from '#lib/components/LineChart.svelte';
	import Slider from '#lib/components/Slider.svelte';

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
	const SCORES = [
		{ k: 'mae', label: 'Mean abs. error', f: (v: number) => num(v, 1) },
		{ k: 'rmse', label: 'RMSE', f: (v: number) => num(v, 1) },
		{ k: 'mape', label: 'Mean abs. % error', f: (v: number) => pct(v, 0) },
		{ k: 'log_rmse', label: 'Log RMSE', f: (v: number) => fixed(v, 3) },
		{ k: 'bias', label: 'Bias', f: (v: number) => num(v, 1) }
	];
	const checkValue = (name: string, v: number) =>
		name.startsWith('weeks') ? pct(v) : name.includes('offset') ? `${v > 0 ? '+' : ''}${v} wk` : pct(v, 0);
</script>

<div class="page">
	<div class="page-head">
		<h1>Validation</h1>
		<p>
			The epidemic layer against Massachusetts data. The Omicron wave was fitted to HHS weekly admissions; the winter
			2020–21 hospital census was never fitted, so it is an out-of-sample check. Each panel also scores a naive baseline
			(last week's value carried forward), which a useful model should beat over the whole wave without seeing any data
			week by week.
		</p>
	</div>

	<Card title="Try to break the Omicron fit" sub="Move the two fitted parameters away from their values and watch the pass bars respond.">
		<div class="knobs">
			<Slider label="R₀" value={r0} min={1.2} max={3} step={0.05} format={(v) => v.toFixed(2)} changed={Math.abs(r0 - 1.95) > 1e-9} onchange={(v) => ((r0 = v), later())} />
			<Slider label="Severity × (hosp scale)" value={hosp} min={0.3} max={3} step={0.02} format={(v) => `${v.toFixed(2)}×`} changed={Math.abs(hosp - 1.08) > 1e-9} onchange={(v) => ((hosp = v), later())} />
			<button class="btn" onclick={() => ((r0 = 1.95), (hosp = 1.08), load())} disabled={busy}>Back to the fit</button>
		</div>
	</Card>

	{#if err}<Card><div class="empty">{err}</div></Card>{/if}

	{#if data}
		{#each ORDER as key (key)}
			{@const v = data[key]}
			<Card title={v.label}>
				{#snippet actions()}
					<span class="tag" class:pass={v.passed} class:fail={!v.passed}>{v.passed ? 'PASS' : 'FAIL'}</span>
				{/snippet}
				<div class="vgrid">
					<LineChart
						dates={v.weeks}
						height={250}
						yMin={0}
						series={[
							{ id: 'obs', label: 'Observed', values: v.observed, color: '#f0efec' },
							{ id: 'model', label: 'Model', values: v.model, color: COLORS[key] },
							{ id: 'naive', label: 'Naive (last week)', values: v.naive, color: '#898781', dashed: true, width: 1.5 }
						]}
					/>
					<div class="side">
						<div class="h">Pass bars</div>
						{#each v.checks.checks as c (c.name)}
							<div class="check">
								<span class="mark" class:ok={c.passed}>{c.passed ? '✓' : '✕'}</span>
								<span class="cn">{c.name}<small>{c.bar}</small></span>
								<b>{checkValue(c.name, c.value)}</b>
							</div>
						{/each}
						<div class="h" style="margin-top:14px">Model vs naive</div>
						<table>
							<thead><tr><th></th><th>model</th><th>naive</th></tr></thead>
							<tbody>
								{#each SCORES as s (s.k)}
									{@const m = v.score[s.k]}
									{@const n = v.naive_score[s.k]}
									<tr>
										<td>{s.label}</td>
										<td class:win={m !== null && n !== null && s.k !== 'bias' && Math.abs(m) < Math.abs(n)}>{m === null ? '–' : s.f(m)}</td>
										<td>{n === null ? '–' : s.f(n)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			</Card>
		{/each}
		<p class="muted note">
			Reading it honestly: the naive baseline has seen last week's real number, while the model sees no data after its
			start date, and in the winter panels it was never fitted to the census at all. The all-inpatient census in winter 2020–21 comes out
			too low (FAIL): observed census per admission was about 8.5 days against the model's 6.8-day mean stay, either
			longer ward stays or patients the admissions series doesn't count (seir/docs/validation.md). The scenario keeps the
			literature value rather than tune to the test.
		</p>
	{:else if !err}
		<Card><div class="empty">Scoring against HHS and COVID Tracking Project data…</div></Card>
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
		padding: 3px 0;
	}
	td {
		padding: 4px 0;
		color: var(--text-2);
		border-bottom: 1px solid var(--line);
	}
	td + td {
		text-align: right;
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
