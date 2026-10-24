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
	let accessView = $state<'today' | 'worst' | 'weighted'>('weighted');
	const accessItems = $derived.by(() => {
		if (!sys) return [];
		return r.geo.patches
			.map((p, i) => {
				const col = sys.access.map((row) => row[i] ?? 1);
				const worst = Math.min(...col);
				const weighted = sys.weighted_loss.reduce((a, row) => a + (row[i] ?? 0), 0);
				const value = accessView === 'today' ? 1 - (col[t] ?? 1) : accessView === 'worst' ? 1 - worst : weighted;
				return { id: p.id, label: p.id, value, note: `×${p.vulnerability.toFixed(1)}` };
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
		<h1>Hospitals & cascade</h1>
		<p>
			Admissions go to hospitals by a gravity model over drive times. Each hospital's operability comes from an FDNA
			dependency graph (staff, beds, shared services); hospitals that are full or failing go on diversion and their
			patients reroute. Access is the share of a neighborhood's usual care that is still open.
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
				<Stat label="Peak ICU occupancy" value={pct(sys.summary.peak_occupancy_icu)} tone={occupancyStatus(sys.summary.peak_occupancy_icu)} />
				<Stat label="Hospital-days diverting" value={num(sys.summary.hospital_days_on_diversion)} />
				<Stat label="Patients diverted" value={num(sys.summary.diverted_patients)} />
				<Stat label="Placed over capacity" value={num(sys.summary.overflow_patients)} hint="overflow" />
				<Stat label="Person-days lost care" value={num(sys.summary.lost_access_person_days)} hint="without usual hospital" />
				<Stat label="Weighted access loss" value={num(sys.summary.weighted_access_loss)} hint="× vulnerability" />
			</div>
		</Card>

		<Card title="Hospital load over time" sub="Rows are hospitals, columns are days. A white tick on top marks a day on diversion.">
			{#snippet actions()}
				<Segmented
					options={[
						{ value: 'occ', label: 'Fuller of ward/ICU' },
						{ value: 'ward', label: 'Ward' },
						{ value: 'icu', label: 'ICU' },
						{ value: 'P', label: 'Operability lost' }
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
				legend={heatView === 'P' ? 'operability lost' : 'occupancy'}
			/>
		</Card>

		<div class="grid-2">
			<Card title={hgeo?.name ?? hid} sub={hgeo ? `${num(hgeo.ward_beds)} ward + ${num(hgeo.icu_beds)} ICU beds assumed for Boston residents · ${pct(hgeo.baseline_occupancy)} filled by other patients` : ''}>
				{#snippet actions()}
					{#if hState}
						<span class="tag"><i class="dot" style:background={STATUS[hState.status]}></i>{STATUS_LABEL[hState.status]}</span>
					{/if}
				{/snippet}
				{#if hState}
					<div class="stats mini">
						<Stat label="Ward" value={pct(hState.ward)} />
						<Stat label="ICU" value={pct(hState.icu)} />
						<Stat label="Operability" value={`${Math.round(hState.P)}%`} />
						<Stat label="Days diverting" value={String(hState.divDays)} />
					</div>
				{/if}
				<LineChart
					dates={e.dates}
					height={190}
					marker={t}
					onscrub={scrub}
					yMin={0}
					yFormat={(v) => pct(v)}
					refLine={{ value: occOn, label: `divert above ${pct(occOn)}` }}
					series={[
						{ id: 'ward', label: 'Ward occupancy', values: sys.occupancy_ward.map((row) => row[hj]), color: COMPARTMENT.H },
						{ id: 'icu', label: 'ICU occupancy', values: sys.occupancy_icu.map((row) => row[hj]), color: COMPARTMENT.C }
					]}
				/>
			</Card>
			<Card title="Operability" sub="FDNA output for the selected hospital (100 = fully working). Diversion starts when it drops below the threshold.">
				<LineChart
					dates={e.dates}
					height={248}
					marker={t}
					onscrub={scrub}
					yMin={0}
					yMax={100}
					yFormat={(v) => `${v.toFixed(0)}`}
					refLine={{ value: Number(app.systemValue('rerouting.p_on') ?? 40), label: 'diversion threshold' }}
					series={[
						{ id: 'P', label: `${hid} operability`, values: sys.operability.map((row) => row[hj]), color: '#c3c2b7', area: true },
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
		</div>

		<Card title="Dependency network (FDNA)" sub="Operability on the selected day. Grey nodes are fully working; amber to red nodes are degraded.">
			<FdnaGraph {sys} {t} selected={app.events.at(-1)?.node ?? null} onnode={knockout} />
			{#if app.events.length}
				<div class="evs">
					{#each app.events as ev (ev.node)}
						<span class="tag"><Icon name="bolt" size={11} /> {ev.node} capped at {ev.value}% · days {ev.start}–{ev.end ?? 'end'}
							<button class="x" onclick={() => app.removeEvent(ev.node)} aria-label="Remove"><Icon name="x" size={10} /></button></span
						>
					{/each}
				</div>
			{/if}
		</Card>

		<div class="grid-2">
			<Card title="Who loses access" sub="Usual hospital care that is closed, diverting or degraded. Right: the neighborhood's vulnerability weight.">
				{#snippet actions()}
					<Segmented
						options={[
							{ value: 'weighted', label: 'Weighted total' },
							{ value: 'worst', label: 'Worst day' },
							{ value: 'today', label: 'Today' }
						]}
						value={accessView}
						onchange={(v) => (accessView = v)}
					/>
				{/snippet}
				<BarList
					items={accessItems}
					format={accessView === 'weighted' ? (v) => num(v) : (v) => pct(v, 1)}
					color="#f2a35e"
					selected={app.selectedPatch}
					onselect={(id) => (app.selectedPatch = app.selectedPatch === id ? null : id)}
				/>
			</Card>
			<Card title="Rerouting" sub="Patients moved away from diverting hospitals, and patients placed above free capacity, per day.">
				<LineChart
					dates={e.dates}
					height={260}
					marker={t}
					onscrub={scrub}
					yMin={0}
					yFormat={(v) => num(v, 1)}
					series={[
						{ id: 'div', label: 'Diverted', values: sys.diverted_patients, color: '#d95926' },
						{ id: 'over', label: 'Over capacity', values: sys.overflow, color: '#e66767', dashed: true }
					]}
				/>
			</Card>
		</div>

		<Card title="Criticality" sub="Knock each FDNA node out for the whole run and rank by the extra vulnerability-weighted access loss it causes.">
			{#snippet actions()}
				<button class="btn" class:primary={!crit} onclick={runCriticality} disabled={critBusy}>
					{critBusy ? 'Running sweep…' : crit ? 'Re-run' : 'Rank nodes'}
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
				<p class="muted foot">Click a node to add a 4-week knockout around the selected day and watch the cascade.</p>
			{:else if !critBusy}
				<div class="empty">One run per node, a few seconds in total.</div>
			{/if}
		</Card>
	{/if}
</div>

<style>
	.mini {
		grid-template-columns: repeat(4, minmax(0, 1fr));
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
