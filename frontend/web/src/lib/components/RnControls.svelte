<script lang="ts">
	import { rn } from '#lib/rn.svelte.ts';
	import { pct } from '#lib/format.ts';
	import type { Dataset, ParamKey } from '#lib/rn-api.ts';
	import Slider from './Slider.svelte';
	import Icon from './Icon.svelte';
	import RnEvents from './RnEvents.svelte';

	const P = $derived(rn.meta?.params);
	const d = $derived(rn.defaults);
	const changed = (k: ParamKey) => Math.abs(rn.params[k] - d[k]) > 1e-9;
	let more = $state(false);
	const MORE: ParamKey[] = ['seed', 'd0', 'alpha_d', 'alpha_h', 'weeks'];
	const moreChanges = $derived(MORE.filter(changed).length + (rn.fallback !== (rn.dataset === 'real') ? 1 : 0));
</script>

<aside class="controls">
	<div class="top">
		<h2><Icon name="sliders" /> What if…?</h2>
		{#if rn.changeCount}
			<button class="btn ghost" onclick={() => rn.reset()} title="Back to the default settings">
				<Icon name="reset" size={13} /> Undo all
			</button>
		{/if}
	</div>
	<p class="blurb">Change an assumption or close a hospital. Every page updates in about a second.</p>

	<section>
		<label class="field">
			<span>Data</span>
			<select class="input" value={rn.dataset} onchange={(e) => rn.setDataset((e.currentTarget as HTMLSelectElement).value as Dataset)}>
				{#each rn.meta?.datasets ?? [] as ds (ds.id)}
					<option value={ds.id}>{ds.title}</option>
				{/each}
			</select>
		</label>
		{#if rn.datasetInfo}<p class="blurb">{rn.datasetInfo.label}.</p>{/if}
	</section>

	{#if P}
		<section>
			<h4>Events</h4>
			<RnEvents />
		</section>

		<section>
			<h4>The epidemic</h4>
			<Slider label="How contagious" help="People one case infects when nobody is immune (R₀)." value={rn.params.r0} min={P.r0.min} max={P.r0.max} step={P.r0.step} format={(v) => v.toFixed(1)} changed={changed('r0')} onchange={(v) => rn.setParam('r0', v)} />
			<Slider label="Cases that need a bed" help="Share of people leaving the infectious stage who need a hospital bed (p_H)." value={rn.params.p_h} min={P.p_h.min} max={P.p_h.max} step={P.p_h.step} format={(v) => pct(v, 1)} changed={changed('p_h')} onchange={(v) => rn.setParam('p_h', v)} />
		</section>

		<button class="more" onclick={() => (more = !more)} aria-expanded={more}>
			<span>More settings</span>
			{#if moreChanges}<span class="count">{moreChanges} changed</span>{/if}
			<i class:open={more}></i>
		</button>

		{#if more}
			<section>
				<Slider label="Infectious at the start" hint="Initial infectious fraction" value={rn.params.seed} min={P.seed.min} max={P.seed.max} step={P.seed.step} format={(v) => pct(v, 2)} changed={changed('seed')} onchange={(v) => rn.setParam('seed', v)} />
				<Slider label="Weeks simulated" value={rn.params.weeks} min={P.weeks.min} max={P.weeks.max} step={P.weeks.step} format={(v) => `${Math.round(v)}`} changed={changed('weeks')} onchange={(v) => rn.setParam('weeks', Math.round(v))} />
			</section>
			<section>
				<h4>Hospitals and access</h4>
				<Slider label="Distance people will travel" help="How fast a hospital's pull fades with distance (d₀). Larger spreads patients wider." value={rn.params.d0} min={P.d0.min} max={P.d0.max} step={P.d0.step} format={(v) => `${v.toFixed(1)} km`} changed={changed('d0')} onchange={(v) => rn.setParam('d0', v)} />
				<Slider label="Tracts rely on their hospitals" help="How much a tract's access falls when its hospitals struggle (α_D)." value={rn.params.alpha_d} min={P.alpha_d.min} max={P.alpha_d.max} step={P.alpha_d.step} format={(v) => v.toFixed(2)} changed={changed('alpha_d')} onchange={(v) => rn.setParam('alpha_d', v)} />
				<Slider label="Hospitals rely on each other" help="How much a struggling hospital drags nearby ones down (α_H)." value={rn.params.alpha_h} min={P.alpha_h.min} max={P.alpha_h.max} step={P.alpha_h.step} format={(v) => v.toFixed(2)} changed={changed('alpha_h')} onchange={(v) => rn.setParam('alpha_h', v)} />
				<label class="check">
					<input type="checkbox" checked={rn.fallback} onchange={(e) => rn.setFallback((e.currentTarget as HTMLInputElement).checked)} />
					<span>
						Use the nearest hospital for tracts with none within {rn.meta?.radius_km ?? 10} km
						<small>One Revere tract needs this with the real data. Turn it off and the run stops with a message naming it.</small>
					</span>
				</label>
			</section>
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
		margin: 0 0 8px;
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
	.check {
		display: grid;
		grid-template-columns: 16px 1fr;
		gap: 8px;
		font-size: 12.5px;
		color: var(--text-2);
		margin-top: 10px;
		cursor: pointer;
		line-height: 1.4;
	}
	.check input {
		accent-color: var(--accent);
		margin: 2px 0 0;
	}
	.check small {
		display: block;
		font-size: 11.5px;
		color: var(--text-3);
		margin-top: 3px;
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
</style>
