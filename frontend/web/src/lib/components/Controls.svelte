<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { fixed, pct } from '#lib/format.ts';
	import Slider from './Slider.svelte';
	import Icon from './Icon.svelte';

	const preset = $derived(
		(app.epi['disease.preset'] as string | undefined) ?? (app.detail?.epi.disease.name as string) ?? 'custom'
	);
	const presetNames = $derived(Object.keys(app.presets?.diseases ?? {}));
	const immune = $derived(app.epiValue<number | Record<string, number>>('seeding.immune_share'));

	// Disruption builder
	const nodes = $derived(app.result?.system?.nodes ?? []);
	let evNode = $state('');
	let evValue = $state(0);
	let evStart = $state(20);
	let evEnd = $state(60);
	$effect(() => {
		if (!evNode && nodes.length) evNode = nodes.find((n) => n.endsWith('.hospital')) ?? nodes[0];
	});

	const ch = (p: string) => p in app.epi;
	const chs = (p: string) => p in app.system;
	const num = (p: string, fallback = 0) => Number(app.epiValue(p) ?? fallback);
	const snum = (p: string, fallback = 0) => Number(app.systemValue(p) ?? fallback);

	let more = $state(false);
	const BASIC = ['disease.preset', 'disease.r0', 'disease.hosp_scale', 'seeding.immune_share', 'rerouting.occ_on'];
	const advancedChanges = $derived(
		[...Object.keys(app.epi), ...Object.keys(app.system)].filter((k) => !BASIC.includes(k)).length +
			app.events.length +
			(app.seedScale !== 1 ? 1 : 0)
	);

	function nodeLabel(n: string) {
		const [h, part] = n.split('.');
		return part ? `${h} · ${part}` : n.replaceAll('_', ' ');
	}
</script>

<aside class="controls">
	<div class="top">
		<h2><Icon name="sliders" /> What if…?</h2>
		{#if app.changeCount}
			<button class="btn ghost" onclick={() => app.reset()} title="Back to the scenario as written">
				<Icon name="reset" size={13} /> Undo all
			</button>
		{/if}
	</div>
	<p class="blurb">Change an assumption and every page updates in about a second.</p>

	<section>
		<label class="field">
			<span>Scenario</span>
			<select class="input" value={app.scenarioId} onchange={(e) => app.load((e.currentTarget as HTMLSelectElement).value)}>
				<optgroup label="With hospitals and a map">
					{#each app.scenarios.filter((s) => s.kind === 'system') as s (s.id)}
						<option value={s.id}>{s.title}</option>
					{/each}
				</optgroup>
				<optgroup label="Epidemic only">
					{#each app.scenarios.filter((s) => s.kind === 'epi') as s (s.id)}
						<option value={s.id}>{s.title}</option>
					{/each}
				</optgroup>
			</select>
		</label>
		{#if app.detail}<p class="blurb">{app.detail.blurb}</p>{/if}
	</section>

	{#if app.detail}
		<section>
			<label class="field">
				<span>Disease</span>
				<select class="input" value={preset} onchange={(e) => app.setEpi('disease.preset', (e.currentTarget as HTMLSelectElement).value)}>
					{#if !presetNames.includes(preset)}<option value={preset}>{preset.replaceAll('_', ' ')} (scenario)</option>{/if}
					{#each presetNames as p (p)}
						<option value={p}>{p.replaceAll('_', ' ')}</option>
					{/each}
				</select>
			</label>
			<Slider label="How contagious" help="People one case infects when nobody is immune (R₀)." value={num('disease.r0', 2)} min={0.5} max={8} step={0.05} format={(v) => v.toFixed(1)} changed={ch('disease.r0')} onchange={(v) => app.setEpi('disease.r0', v)} />
			<Slider label="How severe" help="How many cases need hospital care, relative to the disease's usual share." value={num('disease.hosp_scale', 1)} min={0.1} max={4} step={0.05} format={(v) => `${v.toFixed(1)}×`} changed={ch('disease.hosp_scale')} onchange={(v) => app.setEpi('disease.hosp_scale', v)} />
			{#if typeof immune === 'number'}
				<Slider label="Already immune" help="Share of people protected at the start, from vaccines or past infection." value={immune} min={0} max={0.9} step={0.01} format={(v) => pct(v)} changed={ch('seeding.immune_share')} onchange={(v) => app.setEpi('seeding.immune_share', v)} />
			{/if}
			{#if app.isSystem}
				<Slider label="Hospital is full at" help="Above this share of beds in use, a hospital sends new patients elsewhere." value={snum('rerouting.occ_on', 0.95)} min={0.8} max={1.2} step={0.01} format={(v) => pct(v)} changed={chs('rerouting.occ_on')} onchange={(v) => app.setSystem('rerouting.occ_on', v)} />
			{/if}
		</section>

		<button class="more" onclick={() => (more = !more)} aria-expanded={more}>
			<span>More settings</span>
			{#if advancedChanges}<span class="count">{advancedChanges} changed</span>{/if}
			<i class:open={more}></i>
		</button>

		{#if more}
			<section>
				<h4>Disease</h4>
				<Slider label="Days before infectious" hint="Latent period; incubation rate σ = 1/this" value={num('disease.latent_period', 3)} min={0.5} max={14} step={0.1} format={(v) => `${v.toFixed(1)} d`} changed={ch('disease.latent_period')} onchange={(v) => app.setEpi('disease.latent_period', v)} />
				<Slider label="Days infectious" hint="Infectious period; recovery rate γ = 1/this" value={num('disease.infectious_period', 5)} min={1} max={14} step={0.1} format={(v) => `${v.toFixed(1)} d`} changed={ch('disease.infectious_period')} onchange={(v) => app.setEpi('disease.infectious_period', v)} />
				<Slider label="Days on a ward" value={num('disease.los_ward', 5)} min={1} max={20} step={0.5} format={(v) => `${v.toFixed(1)} d`} changed={ch('disease.los_ward')} onchange={(v) => app.setEpi('disease.los_ward', v)} />
				<Slider label="Days in ICU" value={num('disease.los_icu', 9)} min={1} max={30} step={0.5} format={(v) => `${v.toFixed(1)} d`} changed={ch('disease.los_icu')} onchange={(v) => app.setEpi('disease.los_icu', v)} />
			</section>

			<section>
				<h4>Start and length</h4>
				<Slider label="Cases at the start" hint="Scales the exposed people on day 0" value={app.seedScale} min={0.1} max={10} step={0.1} format={(v) => `${v.toFixed(1)}×`} changed={app.seedScale !== 1} onchange={(v) => app.setSeedScale(v)} />
				<Slider label="Days simulated" value={num('sim.days', 120)} min={30} max={365} step={1} format={(v) => `${v}`} changed={ch('sim.days')} onchange={(v) => app.setEpi('sim.days', Math.round(v))} />
			</section>

			{#if app.isSystem}
				<section>
					<h4>Hospitals</h4>
					<Slider label="Always keep open" hint="This many hospitals never turn patients away" value={snum('rerouting.min_open', 1)} min={0} max={6} step={1} format={(v) => `${v} hosp.`} changed={chs('rerouting.min_open')} onchange={(v) => app.setSystem('rerouting.min_open', Math.round(v))} />
					<Slider label="Preference for the nearest" hint="Gravity model: share ∝ beds · exp(−decay · minutes)" value={snum('allocation.decay', 0.08)} min={0.01} max={0.3} step={0.005} format={(v) => `${fixed(v, 3)}/min`} changed={chs('allocation.decay')} onchange={(v) => app.setSystem('allocation.decay', v)} />
					<Slider label="Staff off sick" hint="Staff absent = this × catchment prevalence (+ fatigue)" value={snum('fdna.staff_absence_per_prevalence', 4)} min={0} max={20} step={0.5} format={(v) => v.toFixed(1)} changed={chs('fdna.staff_absence_per_prevalence')} onchange={(v) => app.setSystem('fdna.staff_absence_per_prevalence', v)} />
					<Slider label="Overstretched ICU raises deaths" hint="ICU deaths × (1 + this × (1 − ICU operability))" value={snum('fdna.icu_strain_mortality', 0.5)} min={0} max={2} step={0.05} format={(v) => v.toFixed(2)} changed={chs('fdna.icu_strain_mortality')} onchange={(v) => app.setSystem('fdna.icu_strain_mortality', v)} />
				</section>

				<section>
					<h4>Disruptions</h4>
					<p class="blurb">Knock out part of a hospital for some days, such as a staff strike or an oxygen shortage.</p>
					{#each app.events as e (e.node)}
						<div class="event">
							<Icon name="bolt" size={13} />
							<span><b>{nodeLabel(e.node)}</b> at {e.value}% · days {e.start}–{e.end ?? 'end'}</span>
							<button class="x" onclick={() => app.removeEvent(e.node)} aria-label="Remove"><Icon name="x" size={12} /></button>
						</div>
					{/each}
					<div class="evform">
						<select class="input" bind:value={evNode}>
							{#each nodes as n (n)}<option value={n}>{nodeLabel(n)}</option>{/each}
						</select>
						<div class="row3">
							<label><span>Working %</span><input class="input" type="number" min="0" max="100" bind:value={evValue} /></label>
							<label><span>From day</span><input class="input" type="number" min="0" bind:value={evStart} /></label>
							<label><span>To day</span><input class="input" type="number" min="0" bind:value={evEnd} /></label>
						</div>
						<button class="btn" onclick={() => app.addEvent({ node: evNode, value: Number(evValue), start: Number(evStart), end: Number(evEnd) || null })}>
							<Icon name="plus" size={13} /> Add disruption
						</button>
					</div>
				</section>
			{/if}
		{/if}
	{/if}
</aside>

<style>
	.controls {
		padding: 16px 18px 40px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.top {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 8px;
		min-height: 30px;
	}
	h2 {
		font-size: 13px;
		font-weight: 600;
		margin: 0;
		display: flex;
		align-items: center;
		gap: 8px;
	}
	section {
		padding: 12px 0;
		border-top: 1px solid var(--line);
	}
	section:first-of-type {
		border-top: 0;
		padding-top: 0;
	}
	h4 {
		margin: 0 0 6px;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-3);
		font-weight: 500;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 12.5px;
		color: var(--text-2);
		margin: 4px 0 8px;
	}
	.blurb {
		font-size: 12px;
		color: var(--text-3);
		line-height: 1.5;
		margin: 2px 0 6px;
	}
	.event {
		display: grid;
		grid-template-columns: 14px 1fr 20px;
		gap: 8px;
		align-items: center;
		font-size: 12px;
		color: var(--text-2);
		background: rgb(208 59 59 / 0.08);
		border: 1px solid rgb(208 59 59 / 0.3);
		border-radius: 8px;
		padding: 6px 8px;
		margin-bottom: 6px;
	}
	.event :global(svg) {
		color: var(--critical);
	}
	.event b {
		color: var(--text-1);
		font-weight: 500;
	}
	.x {
		all: unset;
		cursor: pointer;
		color: var(--text-3);
		display: grid;
		place-items: center;
	}
	.x:hover {
		color: var(--text-1);
	}
	.evform {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-top: 6px;
	}
	.row3 {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 6px;
	}
	.more {
		all: unset;
		display: flex;
		align-items: center;
		gap: 8px;
		cursor: pointer;
		font-size: 12.5px;
		color: var(--text-2);
		padding: 12px 0;
		border-top: 1px solid var(--line);
	}
	.more:hover {
		color: var(--text-1);
	}
	.more .count {
		font-size: 11px;
		color: var(--accent);
	}
	.more i {
		margin-left: auto;
		width: 7px;
		height: 7px;
		border-right: 1.5px solid currentColor;
		border-bottom: 1.5px solid currentColor;
		transform: rotate(45deg);
		transition: transform 0.15s;
	}
	.more i.open {
		transform: rotate(-135deg);
	}
	.row3 label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 11px;
		color: var(--text-3);
	}
</style>
