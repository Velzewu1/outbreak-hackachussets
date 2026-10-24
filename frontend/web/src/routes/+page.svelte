<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { num, pct, shortDate, longDate } from '#lib/format.ts';
	import { COMPARTMENT, occupancyStatus, STATUS, STATUS_LABEL } from '#lib/colors.ts';
	import MapView from '#lib/components/MapView.svelte';
	import Sparkline from '#lib/components/Sparkline.svelte';

	const r = $derived(app.result!);
	const t = $derived(Math.min(app.day, r.epi.dates.length - 1));
	const city = $derived(r.epi.citywide);
	const s = $derived(r.epi.summary);
	const sys = $derived(r.system);

	const hospitals = $derived.by(() => {
		if (!sys) return [];
		return sys.hospitals
			.map((id, j) => {
				const ward = sys.occupancy_ward[t]?.[j] ?? 0;
				const icu = sys.occupancy_icu[t]?.[j] ?? 0;
				const div = !!sys.on_diversion[t]?.[j];
				const occ = Math.max(ward, icu);
				return { id, j, ward, icu, div, occ, status: occupancyStatus(occ, div), P: sys.operability[t]?.[j] ?? 100 };
			})
			.sort((a, b) => b.occ - a.occ);
	});
	const diverting = $derived(hospitals.filter((h) => h.div).length);
	const lostToday = $derived(sys ? sys.lost_person_days[t]?.reduce((a: number, v) => a + (v ?? 0), 0) ?? 0 : 0);
	const reff = $derived(r.epi.rates.r_eff?.[t] ?? null);
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
						“{app.detail?.title}” models {r.geo.patches.map((p) => p.id).join(', ')} as a single population, so there is
						nothing to place on a Boston map. Pick a hospital-system scenario for the map, or open the
						<a href="/epidemic">Epidemic</a> page for its curves.
					</p>
					<button class="btn" onclick={() => app.load('boston_city')}>Open Boston · 15 neighborhoods</button>
				</div>
			</div>
		{/if}
	</div>

	<aside class="side">
		<div class="when">
			<div class="d">{longDate(app.date)}</div>
			<div class="muted">Day {t + 1} · R<sub>eff</sub> {reff === null ? '–' : reff.toFixed(2)}</div>
		</div>

		<div class="today">
			<div class="kv">
				<span><i style:background={COMPARTMENT.I}></i>Infectious</span>
				<b>{num(city.infectious?.[t])}</b>
			</div>
			{#if city.inpatients}
				<div class="kv">
					<span><i style:background={COMPARTMENT.H}></i>In hospital</span>
					<b>{num(city.inpatients[t])}</b>
				</div>
				<div class="kv">
					<span><i style:background={COMPARTMENT.C}></i>In ICU</span>
					<b>{num(city.C?.[t])}</b>
				</div>
			{/if}
			{#if city.D}
				<div class="kv">
					<span><i style:background={COMPARTMENT.D}></i>Deaths so far</span>
					<b>{num(city.D[t])}</b>
				</div>
			{/if}
			{#if sys}
				<div class="kv">
					<span><i style:background={STATUS.critical}></i>Hospitals diverting</span>
					<b>{diverting} / {hospitals.length}</b>
				</div>
				<div class="kv">
					<span><i style:background="#f2a35e"></i>People without usual care</span>
					<b>{num(lostToday)}</b>
				</div>
			{/if}
		</div>

		<div class="spark">
			<div class="sl">Inpatients over the run</div>
			<Sparkline values={city.inpatients ?? city.infectious} color={COMPARTMENT.H} marker={t} height={44} />
		</div>

		{#if sys}
			<div class="block">
				<div class="bh">Hospitals today</div>
				{#each hospitals as h (h.id)}
					<button
						class="hrow"
						class:sel={app.selectedHospital === h.id}
						onclick={() => (app.selectedHospital = app.selectedHospital === h.id ? null : h.id)}
					>
						<span class="hid"><i style:background={STATUS[h.status]}></i>{h.id}</span>
						<span class="hbar"><span style:width="{Math.min(100, h.occ * 100)}%" style:background={STATUS[h.status]}></span></span>
						<span class="hv">{pct(h.occ)}</span>
					</button>
				{/each}
				<div class="foot muted">
					Bar: fuller of ward and ICU. {STATUS_LABEL.critical} when on diversion or over 100%.
				</div>
			</div>
		{/if}

		<div class="block">
			<div class="bh">Whole run</div>
			<div class="kv"><span>Ever infected</span><b>{pct(s.attack_rate, 1)}</b></div>
			{#if s.peak_inpatients}
				<div class="kv"><span>Peak inpatients</span><b>{num(s.peak_inpatients)} · {shortDate(s.peak_inpatients_date)}</b></div>
			{/if}
			{#if s.deaths !== undefined}<div class="kv"><span>Deaths</span><b>{num(s.deaths)}</b></div>{/if}
			{#if sys}
				<div class="kv"><span>Hospital-days diverting</span><b>{sys.summary.hospital_days_on_diversion}</b></div>
				<div class="kv"><span>Patients diverted</span><b>{num(sys.summary.diverted_patients)}</b></div>
				<div class="kv"><span>Person-days without usual care</span><b>{num(sys.summary.lost_access_person_days)}</b></div>
			{/if}
		</div>
	</aside>
</div>

<style>
	.mappage {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 300px;
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
		background:
			radial-gradient(circle at 1px 1px, #1c1c20 1px, transparent 0) 0 0 / 22px 22px,
			#0e0e10;
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
		padding: 18px;
		display: flex;
		flex-direction: column;
		gap: 18px;
	}
	.when .d {
		font-size: 18px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.when .muted {
		font-size: 12px;
		margin-top: 2px;
	}
	.today {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.kv {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 12.5px;
		color: var(--text-3);
		gap: 10px;
	}
	.kv span {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}
	.kv i {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}
	.kv b {
		color: var(--text-1);
		font-weight: 500;
		font-family: var(--mono);
		font-size: 12.5px;
		white-space: nowrap;
	}
	.today .kv b {
		font-size: 14px;
	}
	.sl,
	.bh {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-3);
		margin-bottom: 8px;
	}
	.block {
		border-top: 1px solid var(--line);
		padding-top: 14px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.hrow {
		all: unset;
		display: grid;
		grid-template-columns: 82px 1fr 42px;
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
		display: inline-flex;
		align-items: center;
		gap: 7px;
		color: var(--text-2);
	}
	.hid i {
		width: 7px;
		height: 7px;
		border-radius: 50%;
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
		font-size: 11px;
		line-height: 1.45;
		margin-top: 4px;
	}
	@media (max-width: 900px) {
		.mappage {
			grid-template-columns: 1fr;
			grid-template-rows: 60vh auto;
		}
		.side {
			border-left: 0;
			border-top: 1px solid var(--line);
		}
	}
</style>
