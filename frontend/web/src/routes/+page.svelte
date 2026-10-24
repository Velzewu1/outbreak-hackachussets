<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { num, pct, shortDate, longDate } from '#lib/format.ts';
	import { occupancyStatus, STATUS } from '#lib/colors.ts';
	import MapView from '#lib/components/MapView.svelte';

	const r = $derived(app.result!);
	const t = $derived(Math.min(app.day, r.epi.dates.length - 1));
	const city = $derived(r.epi.citywide);
	const s = $derived(r.epi.summary);
	const sys = $derived(r.system);
	const pop = $derived(r.geo.patches.reduce((a, p) => a + p.population, 0));

	const hospitals = $derived.by(() => {
		if (!sys) return [];
		return sys.hospitals
			.map((id, j) => {
				const ward = sys.occupancy_ward[t]?.[j] ?? 0;
				const icu = sys.occupancy_icu[t]?.[j] ?? 0;
				const div = !!sys.on_diversion[t]?.[j];
				const occ = Math.max(ward, icu);
				return { id, j, occ, div, status: occupancyStatus(occ, div) };
			})
			.sort((a, b) => b.occ - a.occ);
	});
	const full = $derived(hospitals.filter((h) => h.div).length);
	const sick = $derived(city.infectious?.[t] ?? 0);
	const inHospital = $derived(city.inpatients?.[t] ?? null);
	const reff = $derived(r.epi.rates.r_eff?.[t] ?? null);
	// Population-weighted share of usual hospital care still available today.
	const access = $derived.by(() => {
		if (!sys) return null;
		const row = sys.access[t] ?? [];
		return r.geo.patches.reduce((a, p, i) => a + (row[i] ?? 1) * p.population, 0) / pop;
	});

	// The neighborhood clicked on the map, with where its patients usually go.
	const hood = $derived.by(() => {
		const i = r.geo.patches.findIndex((p) => p.id === app.selectedPatch);
		if (i < 0) return null;
		const bp = r.epi.by_patch;
		return {
			p: r.geo.patches[i],
			sick: bp.prevalence[t]?.[i] ?? 0,
			infected: bp.attack_rate[t]?.[i] ?? 0,
			inHospital: bp.inpatients?.[t]?.[i] ?? null,
			access: sys?.access[t]?.[i] ?? null,
			go: sys
				? r.geo.hospitals
						.map((h, j) => ({ id: h.id, share: sys.shares[i][j], min: sys.travel[i][j] }))
						.filter((h) => h.share >= 0.05)
						.sort((a, b) => b.share - a.share)
				: []
		};
	});

	const trend = $derived(
		reff === null ? '' : reff > 1.05 ? 'growing' : reff < 0.95 ? 'shrinking' : 'holding steady'
	);
</script>

<div class="mappage">
	<div class="mapcol">
		{#if r.geo.mappable}
			<MapView />
		{:else}
			<div class="nomap">
				<div>
					<h2>No map for this scenario</h2>
					<p>
						“{app.detail?.title}” treats {r.geo.patches.map((p) => p.id).join(', ')} as one population, so there is
						nothing to colour on a Boston map. Switch to the Boston scenario for the map, or see the
						<a href="/epidemic">Spread</a> page for this one's curves.
					</p>
					<button class="btn" onclick={() => app.load('boston_city')}>Open Boston · 15 neighborhoods</button>
				</div>
			</div>
		{/if}
	</div>

	<aside class="side">
		<div class="when">
			<div class="d">{longDate(app.date)}</div>
			<div class="muted">Day {t + 1} of {r.epi.dates.length}</div>
		</div>

		{#if hood}
			<div class="hood">
				<div class="hh">
					<b>{hood.p.id}</b>
					<button class="x" onclick={() => (app.selectedPatch = null)} aria-label="Back to the whole city">×</button>
				</div>
				<div class="muted small">{num(hood.p.population)} residents</div>
				<div class="kv"><span>Sick now</span><b>{pct(hood.sick, 1)}</b></div>
				<div class="kv"><span>Infected so far</span><b>{pct(hood.infected, 0)}</b></div>
				{#if hood.inHospital !== null}<div class="kv"><span>In hospital</span><b>{num(hood.inHospital)}</b></div>{/if}
				{#if hood.access !== null}<div class="kv"><span>Hospital care available</span><b>{pct(hood.access, 0)}</b></div>{/if}
				{#if hood.go.length}
					<div class="muted small go">Patients usually go to (lines on the map)</div>
					{#each hood.go as h (h.id)}
						<div class="kv"><span>{h.id} · {Math.round(h.min)} min away</span><b>{pct(h.share)}</b></div>
					{/each}
				{/if}
			</div>
		{/if}

		<p class="story">
			About <b>{num(sick)}</b> people ({pct(sick / pop, 1)} of the city) are sick and can pass it on{#if inHospital !== null}, and <b>{num(inHospital)}</b> are in hospital{/if}.
			{#if trend}The outbreak is <b>{trend}</b>: each case infects about {reff!.toFixed(1)} others.{/if}
			{#if sys}
				{#if full}<b class="bad">{full} of {hospitals.length} hospitals are full</b> and sending patients elsewhere.{:else}All {hospitals.length} hospitals are taking patients.{/if}
			{/if}
		</p>

		<div class="big">
			<div class="b">
				<span>Sick now</span>
				<b>{num(sick)}</b>
			</div>
			{#if inHospital !== null}
				<div class="b">
					<span>In hospital</span>
					<b>{num(inHospital)}</b>
				</div>
			{/if}
			{#if sys}
				<div class="b">
					<span>Hospitals full</span>
					<b class:bad={full > 0}>{full} of {hospitals.length}</b>
				</div>
				<div class="b">
					<span>Hospital care available</span>
					<b>{pct(access, 0)}</b>
				</div>
			{/if}
		</div>

		{#if sys}
			<div class="block">
				<div class="bh">How full each hospital is today</div>
				{#each hospitals as h (h.id)}
					<button
						class="hrow"
						class:sel={app.selectedHospital === h.id}
						title={r.geo.hospitals[h.j]?.name}
						onclick={() => (app.selectedHospital = app.selectedHospital === h.id ? null : h.id)}
					>
						<span class="hid">{h.id}</span>
						<span class="hbar"><span style:width="{Math.min(100, h.occ * 100)}%" style:background={STATUS[h.status]}></span></span>
						<span class="hv">{h.div ? 'full' : pct(h.occ)}</span>
					</button>
				{/each}
			</div>
		{/if}

		<div class="block">
			<div class="bh">Over the whole wave</div>
			<div class="kv"><span>Ever infected</span><b>{pct(s.attack_rate, 0)} of residents</b></div>
			{#if s.peak_inpatients}
				<div class="kv"><span>Most in hospital at once</span><b>{num(s.peak_inpatients)} on {shortDate(s.peak_inpatients_date)}</b></div>
			{/if}
			{#if s.deaths !== undefined}<div class="kv"><span>Deaths</span><b>{num(s.deaths)}</b></div>{/if}
			{#if sys}
				<div class="kv"><span>Patients sent to another hospital</span><b>{num(sys.summary.diverted_patients)}</b></div>
			{/if}
		</div>

		<p class="foot muted">An illustrative what-if for Boston, not a forecast. Change the assumptions with <b>What if…?</b> above.</p>
	</aside>
</div>

<style>
	.mappage {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 320px;
		height: 100%;
		min-height: 560px;
	}
	.mapcol {
		position: relative;
		min-height: 0;
	}
	.nomap {
		height: 100%;
		display: grid;
		place-items: center;
		padding: 30px;
		background: #0e0e10;
	}
	.nomap > div {
		max-width: 440px;
	}
	.nomap h2 {
		font-size: 17px;
		margin: 0 0 8px;
	}
	.nomap p {
		color: var(--text-3);
		font-size: 13px;
		line-height: 1.55;
		margin: 0 0 14px;
	}
	.side {
		border-left: 1px solid var(--line);
		overflow-y: auto;
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 18px;
	}
	.when .d {
		font-size: 19px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.when .muted {
		font-size: 12px;
		margin-top: 2px;
	}
	.story {
		margin: 0;
		font-size: 13.5px;
		line-height: 1.6;
		color: var(--text-2);
	}
	.story b {
		color: var(--text-1);
		font-weight: 600;
	}
	.bad {
		color: #ff8a8a !important;
	}
	.hood {
		background: var(--panel);
		border: 1px solid var(--line-2);
		border-radius: 12px;
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.hh {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 15px;
	}
	.x {
		all: unset;
		cursor: pointer;
		color: var(--text-3);
		font-size: 18px;
		line-height: 1;
		padding: 0 4px;
	}
	.x:hover {
		color: var(--text-1);
	}
	.small {
		font-size: 11.5px;
	}
	.go {
		margin-top: 6px;
	}
	.big {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px;
	}
	.b {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 10px;
		padding: 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.b span {
		font-size: 11.5px;
		color: var(--text-3);
	}
	.b b {
		font-size: 19px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.bh {
		font-size: 12px;
		color: var(--text-2);
		font-weight: 500;
		margin-bottom: 6px;
	}
	.block {
		border-top: 1px solid var(--line);
		padding-top: 16px;
		display: flex;
		flex-direction: column;
		gap: 7px;
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
		text-align: right;
	}
	.hrow {
		all: unset;
		display: grid;
		grid-template-columns: 70px 1fr 40px;
		gap: 10px;
		align-items: center;
		padding: 3px 6px;
		margin: 0 -6px;
		border-radius: 6px;
		cursor: pointer;
		font-size: 12px;
	}
	.hrow:hover,
	.hrow.sel {
		background: var(--hover);
	}
	.hid {
		color: var(--text-2);
	}
	.hbar {
		height: 6px;
		background: var(--line);
		border-radius: 3px;
		overflow: hidden;
	}
	.hbar span {
		display: block;
		height: 100%;
		border-radius: 3px;
	}
	.hv {
		text-align: right;
		font-family: var(--mono);
		color: var(--text-1);
	}
	.foot {
		font-size: 11.5px;
		line-height: 1.5;
		margin: auto 0 0;
	}
	@media (max-width: 900px) {
		.mappage {
			grid-template-columns: 1fr;
			grid-template-rows: 62vh auto;
		}
		.side {
			border-left: 0;
			border-top: 1px solid var(--line);
		}
	}
</style>
