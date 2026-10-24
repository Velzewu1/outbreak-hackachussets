<script lang="ts">
	import { rn, describeEvent, weekLabel } from '#lib/rn.svelte.ts';
	import { num, fixed } from '#lib/format.ts';
	import Card from '#lib/components/Card.svelte';
	import LineChart from '#lib/components/LineChart.svelte';
	import More from '#lib/components/More.svelte';

	const r = $derived(rn.result!);
	const v = $derived(rn.view!);
	const labels = $derived(r.scenario.map((_, i) => `W${i + 1}`));
	// with nothing picked, show the most stretched hospital this week
	const hid = $derived(
		rn.selectedHospital ?? [...v.hospitals].sort((a, b) => b.load / Math.max(1, b.capacity) - a.load / Math.max(1, a.capacity))[0]?.id ?? ''
	);
	const info = $derived(r.hospitals.find((h) => h.id === hid)!);
	const w = $derived(v.hospitals.find((h) => h.id === hid)!);
	const events = $derived(rn.events.filter((e) => e.hospital_id === hid));
	const active = $derived(events.filter((e) => v.events.includes(e.id)));
	const series = $derived(r.scenario.map((wk) => wk[rn.phase].hospitals.find((h) => h.id === hid)!));

	// one scale for every row, so bar lengths compare across hospitals
	const hi = $derived(Math.max(1, ...v.hospitals.map((h) => Math.max(h.load, h.capacity, r.hospitals.find((x) => x.id === h.id)?.beds ?? 0))));
	const rows = $derived([...v.hospitals].sort((a, b) => (r.hospitals.find((x) => x.id === b.id)?.beds ?? 0) - (r.hospitals.find((x) => x.id === a.id)?.beds ?? 0)));
	const bedsLabel = $derived(r.synthetic ? 'Beds (synthetic)' : 'Licensed beds');
</script>

<div class="page">
	<div class="page-head">
		<h1>Hospitals</h1>
		<p>
			How many patients want a bed at each hospital, how many beds it has, and how well it is coping. Pick one to follow it
			week by week. {r.synthetic ? '' : 'Capacity is each hospital\'s licensed beds, a stand-in for staffed beds.'}
		</p>
	</div>

	<div class="grid-2">
		<Card title="{weekLabel(rn.week)}: patients wanting a bed vs beds" sub="Bar: patients wanting a bed (red past capacity). Tick: beds available this week.">
			<div class="loads">
				{#each rows as h (h.id)}
					<button class="lrow" class:sel={h.id === hid} onclick={() => (rn.selectedHospital = h.id)}>
						<span class="ln">{rn.hospitalName(h.id)}</span>
						<span class="track">
							<span class="fill" style:width="{(Math.min(h.load, h.capacity) / hi) * 100}%"></span>
							{#if h.load > h.capacity}
								<span class="overflow" style:left="{(h.capacity / hi) * 100}%" style:width="{((h.load - h.capacity) / hi) * 100}%"></span>
							{/if}
							<span class="cap" class:closed={h.closed} style:left="{(h.capacity / hi) * 100}%"></span>
						</span>
						<span class="lv" class:bad={h.closed || h.load > h.capacity}>{h.closed ? 'closed' : `${num(h.load)} / ${num(h.capacity)}`}</span>
					</button>
				{/each}
			</div>
		</Card>

		<Card title={info.name} sub="{weekLabel(rn.week)}, {rn.phase === 'after' ? 'after' : 'before'} rerouting">
			{#if active.length}
				{#each active as e (e.id)}
					{@const d = describeEvent(e, r.weeks)}
					<div class="event">Your event: {d.what} {rn.hospitalName(e.hospital_id)} · {d.when}</div>
				{/each}
			{:else if events.length}
				<div class="event quiet">Your event for this hospital isn't active this week.</div>
			{/if}
			<div class="kvs">
				<div class="kv"><span>{bedsLabel}</span><b>{num(info.beds)}</b></div>
				<div class="kv"><span>Beds available this week</span><b>{w.closed ? 'closed' : num(w.capacity)}</b></div>
				<div class="kv"><span>Usual patients (not from the epidemic)</span><b>{num(w.baseline)}</b></div>
				<div class="kv"><span>Epidemic patients from earlier weeks</span><b>{num(w.retained)}</b></div>
				<div class="kv"><span>New patients asking for a bed</span><b>{fixed(w.request, 1)} <small>people/week</small></b></div>
				<div class="kv strong"><span>Total wanting a bed</span><b>{num(w.load)}</b></div>
				<div class="kv"><span>Beds in use</span><b>{num(w.committed)}</b></div>
				<div class="kv"><span>New patients it took</span><b>{fixed(w.accepted, 1)}</b></div>
				<div class="kv"><span>Over capacity by</span><b class:bad={w.excess > 0}>{num(w.excess)}</b></div>
				{#if w.deficit > 0}
					<div class="kv"><span>Patients stranded by a closure</span><b class="bad">{num(w.deficit)}</b></div>
				{/if}
				<div class="kv strong"><span>Score on its own</span><b>{fixed(w.own, 1)} <small>/ 100</small></b></div>
				<div class="kv strong"><span>Score with its neighbours</span><b>{fixed(w.score, 1)} <small>/ 100</small></b></div>
			</div>
			<p class="muted small">
				The own score falls as patients outnumber beds. The second score also counts how much the hospital leans on nearby
				hospitals that are struggling. Scores never add or remove beds.
			</p>
		</Card>
	</div>

	<div class="grid-2">
		<Card title="Beds, week by week" sub="People in beds. The dashed line is the beds available.">
			<LineChart
				{labels}
				height={230}
				marker={rn.week}
				onscrub={(i) => (rn.week = i)}
				series={[
					{ id: 'load', label: 'Wanting a bed', values: series.map((h) => h.load), color: '#d95926' },
					{ id: 'committed', label: 'Beds in use', values: series.map((h) => h.committed), color: '#199e70' },
					{ id: 'cap', label: 'Beds available', values: series.map((h) => h.capacity), color: '#3987e5', dashed: true }
				]}
			/>
		</Card>
		<Card title="Scores, week by week" sub="0 to 100. Same scale as the map.">
			<LineChart
				{labels}
				height={230}
				yMin={0}
				yMax={100}
				marker={rn.week}
				onscrub={(i) => (rn.week = i)}
				yFormat={(x) => fixed(x, 0)}
				refLine={{ value: r.threshold, label: `${r.threshold}` }}
				series={[
					{ id: 'own', label: 'On its own', values: series.map((h) => h.own), color: '#9085e9' },
					{ id: 'score', label: 'With its neighbours', values: series.map((h) => h.score), color: '#d55181' }
				]}
			/>
		</Card>
	</div>

	<More title="Every hospital's numbers for {weekLabel(rn.week)}" sub="The same values the downloads contain">
		<div class="tablewrap">
			<table>
				<thead>
					<tr>
						<th>Hospital</th><th>Beds</th><th>Available</th><th>Usual</th><th>Earlier weeks</th><th>New asking</th><th>Wanting</th><th>In use</th><th>Over by</th><th>Stranded</th><th>Own</th><th>Score</th>
					</tr>
				</thead>
				<tbody>
					{#each rows as h (h.id)}
						<tr class:sel={h.id === hid} onclick={() => (rn.selectedHospital = h.id)}>
							<td>{rn.hospitalName(h.id)}</td>
							<td>{num(r.hospitals.find((x) => x.id === h.id)?.beds)}</td>
							<td>{h.closed ? 'closed' : num(h.capacity)}</td>
							<td>{num(h.baseline)}</td>
							<td>{num(h.retained)}</td>
							<td>{fixed(h.request, 1)}</td>
							<td>{num(h.load)}</td>
							<td>{num(h.committed)}</td>
							<td>{num(h.excess)}</td>
							<td>{num(h.deficit)}</td>
							<td>{fixed(h.own, 1)}</td>
							<td>{fixed(h.score, 1)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="muted small">Beds are people in beds. "New asking" is people per week. Scores are 0 to 100.</p>
	</More>
</div>

<style>
	.loads {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.lrow {
		all: unset;
		display: grid;
		grid-template-columns: 104px 1fr 92px;
		gap: 12px;
		align-items: center;
		padding: 6px 8px;
		border-radius: 7px;
		cursor: pointer;
		font-size: 12.5px;
	}
	.lrow:hover,
	.lrow.sel {
		background: var(--hover);
	}
	.lrow.sel {
		box-shadow: inset 0 0 0 1px var(--line-2);
	}
	.ln {
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.track {
		position: relative;
		height: 10px;
		background: var(--line);
		border-radius: 3px;
	}
	.fill {
		position: absolute;
		left: 0;
		top: 0;
		bottom: 0;
		background: #6d6d78;
		border-radius: 3px 0 0 3px;
	}
	.overflow {
		position: absolute;
		top: 0;
		bottom: 0;
		background: var(--critical);
		border-radius: 0 3px 3px 0;
	}
	.cap {
		position: absolute;
		top: -4px;
		bottom: -4px;
		width: 2px;
		margin-left: -1px;
		background: var(--text-1);
		border-radius: 1px;
	}
	.cap.closed {
		background: var(--critical);
	}
	.lv {
		text-align: right;
		font-family: var(--mono);
		font-size: 11.5px;
		color: var(--text-1);
		white-space: nowrap;
	}
	.bad {
		color: #ff8a8a !important;
	}
	.event {
		font-size: 12px;
		color: var(--text-2);
		background: rgb(208 59 59 / 0.08);
		border: 1px solid rgb(208 59 59 / 0.3);
		border-radius: 8px;
		padding: 6px 10px;
		margin-bottom: 10px;
	}
	.event.quiet {
		background: transparent;
		border-color: var(--line-2);
		color: var(--text-3);
	}
	.kvs {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.kv {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		font-size: 12.5px;
		color: var(--text-3);
	}
	.kv b {
		color: var(--text-1);
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}
	.kv small {
		color: var(--text-3);
		font-weight: 400;
	}
	.kv.strong span {
		color: var(--text-2);
	}
	.small {
		font-size: 11.5px;
		line-height: 1.5;
		margin: 12px 0 0;
	}
	.tablewrap {
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	th,
	td {
		text-align: right;
		padding: 6px 8px;
		border-bottom: 1px solid var(--line);
		white-space: nowrap;
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
	tbody tr {
		cursor: pointer;
	}
	tbody tr:hover,
	tbody tr.sel {
		background: var(--hover);
	}
</style>
