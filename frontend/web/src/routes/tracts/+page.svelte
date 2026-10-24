<script lang="ts">
	import { rn, scoreColor, tractLabel, weekLabel } from '#lib/rn.svelte.ts';
	import { num, fixed, pct } from '#lib/format.ts';
	import Card from '#lib/components/Card.svelte';
	import LineChart from '#lib/components/LineChart.svelte';
	import Segmented from '#lib/components/Segmented.svelte';

	const r = $derived(rn.result!);
	const v = $derived(rn.view!);
	const b = $derived(rn.baseView!);
	const labels = $derived(r.scenario.map((_, i) => `W${i + 1}`));

	type Sort = 'access' | 'unmet' | 'name';
	let sort = $state<Sort>('access');
	let query = $state('');

	const rows = $derived.by(() => {
		const q = query.trim().toLowerCase();
		const all = r.districts.map((d, i) => ({ d, i, label: tractLabel(d), score: v.access[i], need: v.need[i], unmet: v.unmet[i] }));
		const hit = q ? all.filter((x) => x.label.toLowerCase().includes(q) || x.d.id.includes(q)) : all;
		if (sort === 'access') return hit.sort((a, c) => a.score - c.score || c.unmet - a.unmet);
		if (sort === 'unmet') return hit.sort((a, c) => c.unmet - a.unmet || a.score - c.score);
		return hit.sort((a, c) => a.label.localeCompare(c.label, undefined, { numeric: true }));
	});
	const below = $derived(v.metrics.districts_below_threshold);

	const sel = $derived.by(() => {
		let i = rn.districtIndex(rn.selectedDistrict);
		if (i < 0) i = rows[0]?.i ?? 0;
		return i;
	});
	const d = $derived(r.districts[sel]);
	const fallback = $derived(r.fallback_districts.includes(d.id));
	const ejKnown = $derived(r.districts.some((x) => x.ej !== null));
	const scoreOf = (id: string) => v.hospitals.find((h) => h.id === id)?.score ?? 100;
</script>

<div class="page">
	<div class="page-head">
		<h1>Census tracts</h1>
		<p>
			Tracts are small census areas of a few thousand people. A tract's access score, 0 to 100, says how well the hospitals
			its residents usually use can still take them in. In {weekLabel(rn.week).toLowerCase()}, {below} of {r.districts.length}
			score under {r.threshold}.{#if r.synthetic}
				In this synthetic dataset the “tracts” are made-up districts.{/if}
		</p>
	</div>

	<div class="layout">
		<Card title="All tracts" sub="Click one for details. Need and unmet are people per week.">
			<div class="tools">
				<input class="input" type="search" placeholder="Search by area or tract number" bind:value={query} />
				<Segmented
					options={[
						{ value: 'access', label: 'Lowest access' },
						{ value: 'unmet', label: 'Most unmet' },
						{ value: 'name', label: 'A–Z' }
					]}
					value={sort}
					onchange={(s) => (sort = s)}
				/>
			</div>
			<div class="list">
				<table>
					<thead>
						<tr><th>Tract</th><th>Access</th><th>Need</th><th>Unmet</th></tr>
					</thead>
					<tbody>
						{#each rows as x (x.d.id)}
							<tr class:sel={x.i === sel} onclick={() => (rn.selectedDistrict = x.d.id)}>
								<td>{x.label}</td>
								<td><i class="sw" style:background={scoreColor(x.score)}></i><span class:bad={x.score < r.threshold}>{fixed(x.score, 1)}</span></td>
								<td>{fixed(x.need, 1)}</td>
								<td class:bad={x.unmet >= 0.05}>{fixed(x.unmet, 1)}</td>
							</tr>
						{:else}
							<tr><td colspan="4" class="muted">No tract matches “{query}”.</td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Card>

		<div class="col">
			<Card title={tractLabel(d)} sub="{weekLabel(rn.week)}, {rn.phase === 'after' ? 'after' : 'before'} rerouting · census tract {d.id}">
				<div class="stats">
					<div class="s"><span>Access score</span><b class:bad={v.access[sel] < r.threshold}><i class="sw" style:background={scoreColor(v.access[sel])}></i>{fixed(v.access[sel], 1)}</b>{#if rn.hasBaseline}<small>{fixed(b.access[sel], 1)} with no events</small>{/if}</div>
					<div class="s"><span>Need a bed</span><b>{fixed(v.need[sel], 1)}</b><small>people this week</small></div>
					<div class="s"><span>Can't get one</span><b class:bad={v.unmet[sel] >= 0.05}>{fixed(v.unmet[sel], 1)}</b><small>people this week</small></div>
					<div class="s"><span>Residents</span><b>{num(d.population)}</b><small>{r.synthetic ? 'synthetic' : 'Census 2020'}</small></div>
				</div>
				{#if fallback}
					<p class="note">No hospital is within {rn.meta?.radius_km ?? 10} km of this tract, so it is assigned its single nearest hospital. This is disclosed, not hidden.</p>
				{/if}
				<h4>Where its patients go</h4>
				<div class="tw"><table class="catch">
					<thead>
						<tr>
							<th>Hospital</th><th>Distance</th><th>Usual share</th><th>Hospital score</th>
							<th title="Hospital score + 100 × (1 − usual share). A tract's score can't go above the lowest of these ceilings, or above the share-weighted average of its hospitals' scores (softened by how much it relies on them, α_D).">Ceiling</th>
						</tr>
					</thead>
					<tbody>
						{#each d.catchment as c (c.id)}
							{@const p = scoreOf(c.id)}
							<tr>
								<td title={rn.hospitalName(c.id, false)}>{rn.hospitalName(c.id)}</td>
								<td>{fixed(c.km, 1)} km</td>
								<td>{pct(c.share)}</td>
								<td><i class="sw" style:background={scoreColor(p)}></i>{fixed(p, 1)}</td>
								<td>{fixed(Math.min(100, p + 100 * (1 - c.share)), 1)}</td>
							</tr>
						{/each}
					</tbody>
				</table></div>
				<p class="muted small">
					Shares come from distance alone (closer hospitals get more), not from real patient records.
					Accessibility index {fixed(d.access_index, 2)}. Environmental-justice status: {d.ej === null ? 'unknown' : d.ej ? 'yes' : 'no'}{ejKnown ? '' : ' (no flags in this dataset)'}.
				</p>
			</Card>

			<div class="grid-2">
				<Card title="Access score, week by week" sub="0 to 100, fixed scale">
					<LineChart
						{labels}
						height={200}
						yMin={0}
						yMax={100}
						marker={rn.week}
						onscrub={(i) => (rn.week = i)}
						yFormat={(x) => fixed(x, 0)}
						refLine={{ value: r.threshold, label: `${r.threshold}` }}
						series={[
							...(r.baseline ? [{ id: 'base', label: 'No events', values: r.baseline.map((w) => w[rn.phase].access[sel]), color: '#898781', dashed: true }] : []),
							{ id: 'access', label: r.baseline ? 'With your events' : 'Access score', values: r.scenario.map((w) => w[rn.phase].access[sel]), color: '#d95926' }
						]}
					/>
				</Card>
				<Card title="Can't get a bed, week by week" sub="People per week">
					<LineChart
						{labels}
						height={200}
						marker={rn.week}
						onscrub={(i) => (rn.week = i)}
						yFormat={(x) => fixed(x, x < 10 ? 1 : 0)}
						series={[
							...(r.baseline ? [{ id: 'base', label: 'No events', values: r.baseline.map((w) => w[rn.phase].unmet[sel]), color: '#898781', dashed: true }] : []),
							{ id: 'need', label: 'Need a bed', values: r.scenario.map((w) => w[rn.phase].need[sel]), color: '#3987e5' },
							{ id: 'unmet', label: "Can't get one", values: r.scenario.map((w) => w[rn.phase].unmet[sel]), color: '#d03b3b' }
						]}
					/>
				</Card>
			</div>
		</div>
	</div>
</div>

<style>
	.layout {
		display: grid;
		grid-template-columns: minmax(320px, 0.85fr) minmax(0, 1.4fr);
		gap: 16px;
		align-items: start;
	}
	.col {
		display: flex;
		flex-direction: column;
		gap: 16px;
		min-width: 0;
	}
	.tools {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-bottom: 8px;
	}
	.list {
		max-height: 620px;
		overflow-y: auto;
		margin: 0 -6px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12.5px;
		font-variant-numeric: tabular-nums;
	}
	th,
	td {
		padding: 6px 6px;
		border-bottom: 1px solid var(--line);
		text-align: right;
		white-space: nowrap;
	}
	th:first-child,
	td:first-child {
		text-align: left;
	}
	td:first-child {
		max-width: 210px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	th {
		color: var(--text-3);
		font-weight: 500;
		position: sticky;
		top: 0;
		background: var(--panel);
	}
	td {
		color: var(--text-2);
	}
	.list tbody tr {
		cursor: pointer;
	}
	.list tbody tr:hover,
	.list tbody tr.sel {
		background: var(--hover);
	}
	.list tbody tr.sel td:first-child {
		color: var(--text-1);
	}
	.sw {
		display: inline-block;
		width: 9px;
		height: 9px;
		border-radius: 2px;
		margin-right: 6px;
		box-shadow: 0 0 0 1px var(--line-2);
		vertical-align: 0;
	}
	.bad {
		color: #ff8a8a !important;
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 14px;
	}
	.s {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.s span {
		font-size: 12px;
		color: var(--text-3);
	}
	.s b {
		font-size: 21px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.s small {
		font-size: 11px;
		color: var(--text-3);
	}
	.note {
		margin: 0 0 12px;
		font-size: 12px;
		line-height: 1.5;
		color: var(--text-3);
		border-left: 2px solid var(--warning);
		padding-left: 10px;
	}
	h4 {
		margin: 4px 0 6px;
		font-size: 12px;
		color: var(--text-2);
		font-weight: 500;
	}
	.tw {
		overflow-x: auto;
	}
	.catch th[title] {
		text-decoration: underline dotted;
		cursor: help;
	}
	.small {
		font-size: 11.5px;
		line-height: 1.5;
		margin: 10px 0 0;
	}
	@media (max-width: 1100px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
		.stats {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
</style>
