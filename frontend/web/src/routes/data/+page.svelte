<script lang="ts">
	import { rn, describeEvent } from '#lib/rn.svelte.ts';
	import { num, pct, fixed } from '#lib/format.ts';
	import Card from '#lib/components/Card.svelte';
	import More from '#lib/components/More.svelte';
	import Icon from '#lib/components/Icon.svelte';

	const r = $derived(rn.result!);
	const man = $derived(r.manifest as Record<string, unknown>);
	type Cross = { model_id: string; massgis_name: string; ccn: string; dph_facility_id: string; licensed_total_beds: number; icu_beds: number; baseline_fraction: number; review_status: string };
	const hosp = $derived(man.hospitals as { crosswalk?: Cross[]; excluded?: Record<string, string> } | undefined);
	const pop = $derived(man.population as Record<string, unknown> | undefined);
	const crosswalk = $derived([...(hosp?.crosswalk ?? [])].sort((a, b) => a.massgis_name.localeCompare(b.massgis_name)));

	const FILES = [
		{ name: 'hospital_week.csv', what: 'Every hospital, every week, before and after rerouting: demand, capacity, beds in use, scores.' },
		{ name: 'district_week.csv', what: 'Every tract, every week, both phases: access score, need and unmet need (people/week).' },
		{ name: 'reroute_week.csv', what: 'Every patient move: week, tract, from hospital, to hospital, amount.' },
		{ name: 'run.json', what: 'The whole run with its settings, events, provenance hashes and data manifest.' }
	];
	let busy = $state<string | null>(null);
	let failed = $state<string | null>(null);
	async function get(name: string) {
		busy = name;
		failed = null;
		try {
			await rn.download(name);
		} catch (e) {
			failed = `${name}: ${(e as Error).message}`;
		}
		busy = null;
	}

	const SETTINGS = $derived([
		['How contagious (R₀)', fixed(rn.params.r0, 1)],
		['Cases that need a bed (p_H)', pct(rn.params.p_h, 1)],
		['Infectious at the start', pct(rn.params.seed, 2)],
		['Distance decay (d₀)', `${fixed(rn.params.d0, 1)} km`],
		['Tracts rely on hospitals (α_D)', fixed(rn.params.alpha_d, 2)],
		['Hospitals rely on each other (α_H)', fixed(rn.params.alpha_h, 2)],
		['Weeks simulated', `${rn.params.weeks}`],
		['Nearest hospital beyond 10 km', rn.fallback ? 'on' : 'off'],
		['Poor-access threshold', `${r.threshold}`]
	]);
</script>

<div class="page">
	<div class="page-head">
		<h1>Data and downloads</h1>
		<p>Where every input comes from, what was assumed, and the files behind the numbers on these pages.</p>
	</div>

	<div class="banner" class:synthetic={r.synthetic}>
		<b>{r.mode}.</b>
		{r.mode_label}.
		{#if !r.synthetic}Bed counts are licensed beds, used as a stand-in for staffed beds. The epidemic is simulated, not observed.{/if}
	</div>

	<div class="grid-2">
		<Card title="Downloads" sub="For the run on screen now, including your settings and events">
			<div class="files">
				{#each FILES as f (f.name)}
					<button class="file" onclick={() => get(f.name)} disabled={busy !== null}>
						<span class="ic">{#if busy === f.name}<span class="spin"></span>{:else}<Icon name="download" />{/if}</span>
						<span class="ft"><b>{f.name}</b><small>{f.what}</small></span>
					</button>
				{/each}
			</div>
			{#if failed}<p class="err">Download failed: {failed}</p>{/if}
			<p class="muted small">Units: beds are people in beds; need and unmet need are people per week, not beds; scores are 0 to 100.</p>
		</Card>

		<Card title="This run" sub="Run IDs are content hashes: same inputs, same ID">
			<div class="kvs">
				<div class="kv"><span>Run</span><b class="mono">{r.run_id}</b></div>
				{#if r.base_run_id !== r.run_id}<div class="kv"><span>No-events run</span><b class="mono">{r.base_run_id}</b></div>{/if}
				<div class="kv"><span>Study area</span><b>{r.synthetic ? 'Synthetic city' : 'Suffolk County, MA'} · census tracts · 1-week steps</b></div>
				{#each SETTINGS as [k, val] (k)}
					<div class="kv"><span>{k}</span><b>{val}</b></div>
				{/each}
				<div class="kv">
					<span>Events</span>
					<b>
						{#each rn.events as e (e.id)}
							{@const d = describeEvent(e, r.weeks)}
							<span class="ev">{d.what} {rn.hospitalName(e.hospital_id)} · {d.when}</span>
						{:else}none{/each}
					</b>
				</div>
			</div>
		</Card>
	</div>

	{#if crosswalk.length}
		<Card title="Hospitals" sub="Adult acute hospitals in Suffolk County from MassGIS, matched to federal IDs by hand">
			<div class="tablewrap">
				<table>
					<thead>
						<tr><th>Hospital</th><th>Model ID</th><th>Federal ID (CCN)</th><th>Licensed beds</th><th>ICU beds</th><th>Usually occupied</th><th>Match</th></tr>
					</thead>
					<tbody>
						{#each crosswalk as h (h.model_id)}
							<tr>
								<td>{h.massgis_name}</td>
								<td class="mono">{h.model_id}</td>
								<td class="mono">{h.ccn}</td>
								<td>{num(h.licensed_total_beds)}</td>
								<td>{num(h.icu_beds)}</td>
								<td>{pct(h.baseline_fraction)}</td>
								<td>{h.review_status}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if hosp?.excluded}
				<h4>Left out, and why</h4>
				<ul class="excl">
					{#each Object.entries(hosp.excluded) as [id, why] (id)}<li>{why}</li>{/each}
				</ul>
			{/if}
		</Card>
	{/if}

	<div class="grid-2">
		{#if pop}
			<Card title="Census tracts" sub="MassGIS 2020 tract outlines with decennial Census counts">
				<div class="kvs">
					<div class="kv"><span>Population counts</span><b>{pop.population_vintage}</b></div>
					<div class="kv"><span>Tracts modeled</span><b>{pop.n_tracts_modeled} of {pop.n_tracts_total}</b></div>
					<div class="kv"><span>Left out (no residents)</span><b>{(pop.zero_pop_geometries as string[] | undefined)?.length ?? 0} tracts</b></div>
					<div class="kv"><span>Residents modeled</span><b>{num(r.districts.reduce((a, d) => a + d.population, 0))}</b></div>
					<div class="kv"><span>Environmental-justice flags</span><b>{r.districts.some((d) => d.ej !== null) ? 'present' : 'not available (shown as unknown)'}</b></div>
				</div>
			</Card>
		{/if}
		<Card title="Notes from the data" sub="Recorded by the data loader">
			<div class="notes">
				{#each ['capacity_note', 'observed_note', 'nearest_fallback_note'] as k (k)}
					{#if typeof man[k] === 'string'}<p>{man[k]}</p>{/if}
				{/each}
				{#if r.fallback_districts.length}<p>Tracts using the nearest hospital: <span class="mono">{r.fallback_districts.join(', ')}</span>.</p>{/if}
				{#if r.synthetic}<p>Generated data ({man.source}{man.seed ? `, seed ${man.seed}` : ''}). Nothing here is observed Boston data.</p>{/if}
				{#each r.warnings as w, i (i)}<p class="err">{w}</p>{/each}
			</div>
		</Card>
	</div>

	<More title="The raw data manifest" sub="Exactly what the loader reported">
		<pre>{JSON.stringify(man, null, 2)}</pre>
	</More>
</div>

<style>
	.banner {
		border: 1px solid rgb(250 178 25 / 0.4);
		background: rgb(250 178 25 / 0.07);
		border-radius: 12px;
		padding: 12px 16px;
		font-size: 13px;
		line-height: 1.55;
		color: var(--text-2);
	}
	.banner b {
		color: var(--warning);
	}
	.banner.synthetic {
		border-color: rgb(134 182 239 / 0.4);
		background: rgb(134 182 239 / 0.07);
	}
	.banner.synthetic b {
		color: #86b6ef;
	}
	.files {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.file {
		all: unset;
		display: grid;
		grid-template-columns: 30px 1fr;
		gap: 10px;
		align-items: center;
		border: 1px solid var(--line-2);
		border-radius: 10px;
		padding: 10px 12px;
		cursor: pointer;
	}
	.file:hover {
		background: var(--hover);
	}
	.file:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.ic {
		display: grid;
		place-items: center;
		color: var(--text-2);
	}
	.ft {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.ft b {
		font-family: var(--mono);
		font-size: 12.5px;
		font-weight: 500;
	}
	.ft small {
		font-size: 12px;
		color: var(--text-3);
		line-height: 1.4;
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
	.ev {
		display: block;
	}
	.tablewrap {
		overflow-x: auto;
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
	h4 {
		margin: 14px 0 6px;
		font-size: 12px;
		font-weight: 500;
		color: var(--text-2);
	}
	.excl {
		margin: 0;
		padding-left: 18px;
		font-size: 12px;
		color: var(--text-3);
		columns: 2;
		line-height: 1.6;
	}
	.notes p {
		margin: 0 0 8px;
		font-size: 12.5px;
		color: var(--text-2);
		line-height: 1.55;
	}
	.err {
		color: #ffb199 !important;
		font-size: 12px;
	}
	.small {
		font-size: 11.5px;
		line-height: 1.5;
		margin: 10px 0 0;
	}
	pre {
		margin: 0;
		background: var(--bg);
		border: 1px solid var(--line);
		border-radius: 10px;
		padding: 12px;
		font-family: var(--mono);
		font-size: 11.5px;
		color: var(--text-2);
		max-height: 420px;
		overflow: auto;
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
	@media (max-width: 900px) {
		.excl {
			columns: 1;
		}
	}
</style>
