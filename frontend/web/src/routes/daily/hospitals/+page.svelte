<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { api, type CriticalityRow } from '#lib/api.ts';
	import { num, pct } from '#lib/format.ts';
	import { COMPARTMENT, STATUS, STATUS_LABEL, heatColor, occupancyStatus } from '#lib/colors.ts';
	import Card from '#lib/components/Card.svelte';
	import Stat from '#lib/components/Stat.svelte';
	import LineChart from '#lib/components/LineChart.svelte';
	import Heatmap from '#lib/components/Heatmap.svelte';
	import BarList from '#lib/components/BarList.svelte';
	import FdnaGraph from '#lib/components/FdnaGraph.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import More from '#lib/components/More.svelte';

	const r = $derived(app.result!);
	const sys = $derived(r.system);
	const e = $derived(r.epi);
	const t = $derived(Math.min(app.day, e.dates.length - 1));
	const scrub = (i: number) => (app.day = i);

	let heatView = $state<'occ' | 'ward' | 'icu' | 'P'>('occ');
	const heatGrid = $derived.by(() => {
		if (!sys) return [];
		if (heatView === 'ward') return sys.occupancy_ward;
		if (heatView === 'icu') return sys.occupancy_icu;
		if (heatView === 'P') return sys.operability.map((row) => row.map((v) => 100 - (v ?? 100)));
		return sys.occupancy_ward.map((row, i) => row.map((v, j) => Math.max(v ?? 0, sys.occupancy_icu[i]?.[j] ?? 0)));
	});

	const hid = $derived(app.selectedHospital ?? sys?.hospitals[0] ?? '');
	const hj = $derived(sys ? sys.hospitals.indexOf(hid) : -1);
	const hgeo = $derived(r.geo.hospitals.find((h) => h.id === hid));
	const occOn = $derived(Number(app.systemValue('rerouting.occ_on') ?? 0.95));

	const hState = $derived.by(() => {
		if (!sys || hj < 0) return null;
		const ward = sys.occupancy_ward[t]?.[hj] ?? 0;
		const icu = sys.occupancy_icu[t]?.[hj] ?? 0;
		const div = !!sys.on_diversion[t]?.[hj];
		const occ = Math.max(ward, icu);
		const dd = sys.on_diversion.reduce((a, row) => a + (row[hj] ? 1 : 0), 0);
		return { ward, icu, div, occ, P: sys.operability[t]?.[hj] ?? 100, status: occupancyStatus(occ, div), divDays: dd };
	});

	// Access by neighborhood
	let accessView = $state<'today' | 'worst' | 'weighted'>('worst');
	const accessItems = $derived.by(() => {
		if (!sys) return [];
		return r.geo.patches
			.map((p, i) => {
				const col = sys.access.map((row) => row[i] ?? 1);
				const worst = Math.min(...col);
				const weighted = sys.weighted_loss.reduce((a, row) => a + (row[i] ?? 0), 0);
				const value = accessView === 'today' ? 1 - (col[t] ?? 1) : accessView === 'worst' ? 1 - worst : weighted;
				return { id: p.id, label: p.id, value, note: accessView === 'weighted' ? `×${p.vulnerability.toFixed(1)}` : undefined };
			})
			.sort((a, b) => b.value - a.value);
	});

	// Criticality sweep
	let crit = $state<CriticalityRow[] | null>(null);
	let critBusy = $state(false);
	let critErr = $state<string | null>(null);
	async function runCriticality() {
		critBusy = true;
		critErr = null;
		try {
			crit = (await api.criticality({ ...app.changes(), level: 0 })).rows;
		} catch (err) {
			critErr = (err as Error).message;
		} finally {
			critBusy = false;
		}
	}
	$effect(() => {
		void app.scenarioId;
		crit = null;
	});

	function knockout(node: string) {
		app.addEvent({ node, value: 0, start: Math.max(0, t - 7), end: Math.min(e.dates.length, t + 21) });
	}
</script>

<div class="page">
	<div class="page-head">
		<h1>Hospitals</h1>
		<p>
			Patients go to nearby hospitals with free beds. A hospital that is full, or short of staff, turns new patients
			away and they travel further. This page shows which hospitals fill up and which neighborhoods lose their usual
			hospital.
		</p>
	</div>

	{#if !sys}
		<Card>
			<div class="empty">
				This scenario models the epidemic only. <button class="btn" onclick={() => app.load('boston_city')}
					>Open Boston · 15 neighborhoods</button
				>
			</div>
		</Card>
	{:else}
		<Card>
			<div class="stats">
				<Stat label="ICU at its fullest" value={pct(sys.summary.peak_occupancy_icu)} tone={occupancyStatus(sys.summary.peak_occupancy_icu)} />
				<Stat label="Days a hospital was full" value={num(sys.summary.hospital_days_on_diversion)} hint="added up over hospitals" />
				<Stat label="Patients sent elsewhere" value={num(sys.summary.diverted_patients)} />
				<Stat label="Patients with no free bed" value={num(sys.summary.overflow_patients)} hint="placed over capacity" />
			</div>
		</Card>

		<Card title="How full each hospital is, day by day" sub="Rows are hospitals, columns are days; brighter is fuller. A white tick on top marks a day the hospital was full and turning patients away. Click a row for its details.">
			{#snippet actions()}
				<Segmented
					options={[
						{ value: 'occ', label: 'Ward or ICU' },
						{ value: 'ward', label: 'Ward' },
						{ value: 'icu', label: 'ICU' }
					]}
					value={heatView}
					onchange={(v) => (heatView = v)}
				/>
			{/snippet}
			<Heatmap
				rows={sys.hospitals}
				dates={e.dates}
				values={heatGrid}
				color={heatColor}
				max={heatView === 'P' ? 100 : Math.max(1, ...heatGrid.flat().map((v) => v ?? 0))}
				min={heatView === 'P' ? 0 : 0.7}
				format={heatView === 'P' ? (v) => `${v.toFixed(0)} pts` : (v) => pct(v)}
				marker={t}
				flags={sys.on_diversion}
				selected={hid}
				rowHeight={24}
				onrow={(h) => (app.selectedHospital = h)}
				onscrub={scrub}
				legend={heatView === 'P' ? 'operability lost' : 'beds in use'}
			/>
		</Card>

		<div class="grid-2">
			<Card title={hgeo?.name ?? hid} sub={hgeo ? `${num(hgeo.ward_beds)} ward and ${num(hgeo.icu_beds)} ICU beds for Boston residents (assumed)` : ''}>
				{#snippet actions()}
					{#if hState}
						<span class="tag"><i class="dot" style:background={STATUS[hState.status]}></i>{STATUS_LABEL[hState.status]}</span>
					{/if}
				{/snippet}
				{#if hState}
					<div class="stats mini">
						<Stat label="Ward beds in use" value={pct(hState.ward)} />
						<Stat label="ICU beds in use" value={pct(hState.icu)} />
						<Stat label="Days full" value={String(hState.divDays)} />
					</div>
				{/if}
				<LineChart
					dates={e.dates}
					height={190}
					marker={t}
					onscrub={scrub}
					yMin={0}
					yFormat={(v) => pct(v)}
					refLine={{ value: occOn, label: `full at ${pct(occOn)}` }}
					series={[
						{ id: 'ward', label: 'Ward beds in use', values: sys.occupancy_ward.map((row) => row[hj]), color: COMPARTMENT.H },
						{ id: 'icu', label: 'ICU beds in use', values: sys.occupancy_icu.map((row) => row[hj]), color: COMPARTMENT.C }
					]}
				/>
			</Card>
			<Card title="Who loses their usual hospital" sub="Share of a neighborhood's usual hospital care that is full, closed or short-staffed.">
				{#snippet actions()}
					<Segmented
						options={[
							{ value: 'worst', label: 'Worst day' },
							{ value: 'today', label: 'Today' }
						]}
						value={accessView === 'weighted' ? 'worst' : accessView}
						onchange={(v) => (accessView = v)}
					/>
				{/snippet}
				<BarList
					items={accessItems}
					format={(v) => pct(v, 0)}
					color="#f2a35e"
					selected={app.selectedPatch}
					onselect={(id) => (app.selectedPatch = app.selectedPatch === id ? null : id)}
				/>
			</Card>
		</div>

		<More title="What makes a hospital fail" sub="Hospitals depend on staff, beds and shared services. Knock a part out and watch the knock-on effects.">
			<Card title="Dependency network" sub="How much of each part is working on the selected day: grey is fine, amber to red is struggling. Click any part to knock it out for four weeks around this day.">
				<FdnaGraph {sys} {t} selected={app.events.at(-1)?.node ?? null} onnode={knockout} />
				{#if app.events.length}
					<div class="evs">
						{#each app.events as ev (ev.node)}
							<span class="tag"><Icon name="bolt" size={11} /> {ev.node} at {ev.value}% · days {ev.start}–{ev.end ?? 'end'}
								<button class="x" onclick={() => app.removeEvent(ev.node)} aria-label="Remove"><Icon name="x" size={10} /></button></span
							>
						{/each}
					</div>
				{/if}
			</Card>

			<div class="grid-2">
				<Card title={`How much of ${hid} is working`} sub="100 means fully working (operability). Below the line the hospital turns patients away.">
					<LineChart
						dates={e.dates}
						height={230}
						marker={t}
						onscrub={scrub}
						yMin={0}
						yMax={100}
						yFormat={(v) => `${v.toFixed(0)}`}
						refLine={{ value: Number(app.systemValue('rerouting.p_on') ?? 40), label: 'turns patients away' }}
						series={[
							{ id: 'P', label: `${hid} overall`, values: sys.operability.map((row) => row[hj]), color: '#c3c2b7', area: true },
							...['staff', 'icu', 'ward']
								.map((k) => `${hid}.${k}`)
								.filter((n) => sys.nodes.includes(n))
								.map((n, k) => ({
									id: n,
									label: n.split('.')[1],
									values: sys.node_operability.map((row) => row[sys.nodes.indexOf(n)]),
									color: ['#3987e5', '#d95926', '#9085e9'][k],
									width: 1.5
								}))
						]}
					/>
				</Card>
				<Card title="Patients sent elsewhere, per day" sub="Moved away from full hospitals, and placed where no bed was free.">
					<LineChart
						dates={e.dates}
						height={230}
						marker={t}
						onscrub={scrub}
						yMin={0}
						yFormat={(v) => num(v, 1)}
						series={[
							{ id: 'div', label: 'Sent elsewhere', values: sys.diverted_patients, color: '#d95926' },
							{ id: 'over', label: 'No free bed', values: sys.overflow, color: '#e66767', dashed: true }
						]}
					/>
				</Card>
			</div>

			<Card title="Which parts matter most" sub="Knock out each part for the whole run, one at a time, and rank by how much extra access to care is lost (weighted by neighborhood vulnerability).">
				{#snippet actions()}
					<button class="btn" class:primary={!crit} onclick={runCriticality} disabled={critBusy}>
						{critBusy ? 'Running…' : crit ? 'Re-run' : 'Rank the parts'}
					</button>
				{/snippet}
				{#if critErr}<div class="empty">{critErr}</div>{/if}
				{#if crit}
					<BarList
						items={crit.slice(0, 14).map((c) => ({ id: c.node, label: c.node, value: c.extra_loss }))}
						format={(v) => num(v)}
						color={STATUS.critical}
						onselect={(n) => knockout(n)}
					/>
					<p class="muted foot">Click a part to knock it out for four weeks around the selected day.</p>
				{:else if !critBusy}
					<div class="empty">One run per part, a few seconds in total.</div>
				{/if}
			</Card>
		</More>
	{/if}
</div>

<style>
	.mini {
		grid-template-columns: repeat(3, minmax(0, 1fr));
		margin-bottom: 14px;
	}
	.dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		display: inline-block;
	}
	.evs {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 10px;
	}
	.evs .tag {
		border-color: rgb(208 59 59 / 0.4);
	}
	.x {
		all: unset;
		cursor: pointer;
		display: inline-grid;
		place-items: center;
		color: var(--text-3);
	}
	.foot {
		font-size: 12px;
		margin: 8px 0 0;
	}
</style>
