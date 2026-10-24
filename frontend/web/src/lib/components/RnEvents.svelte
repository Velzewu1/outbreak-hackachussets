<script lang="ts">
	import { describeEvent, rn } from '#lib/rn.svelte.ts';
	import { pct } from '#lib/format.ts';
	import type { EventKind } from '#lib/rn-api.ts';
	import Icon from './Icon.svelte';
	import Slider from './Slider.svelte';

	// Close a hospital or cut its beds for a run of weeks. Weeks show 1-based; the engine's
	// end week is exclusive, so "weeks 3 to 5" is start 2, end 5.
	interface Props {
		compact?: boolean;
	}
	let { compact = false }: Props = $props();

	const hospitals = $derived(rn.result?.hospitals ?? []);
	const n = $derived(rn.nWeeks || Math.round(rn.params.weeks));
	let kind = $state<EventKind>('close_hospital');
	let hospital = $state('');
	let from = $state(1);
	let to = $state(8);
	let factor = $state(0.6);
	let busy = $state(false);

	$effect(() => {
		if (!hospitals.some((h) => h.id === hospital)) hospital = hospitals[0]?.id ?? '';
	});
	// start where the viewer is looking, run to the end
	let primed = false;
	$effect(() => {
		if (primed || !rn.result) return;
		primed = true;
		from = rn.week + 1;
		to = n;
	});
	$effect(() => {
		if (to > n) to = n;
		if (from > n) from = n;
		if (to < from) to = from;
	});

	async function add() {
		busy = true;
		await rn.addEvent({
			kind,
			hospital_id: hospital,
			start_week: from - 1,
			end_week: to >= n ? null : to,
			factor: kind === 'set_capacity' ? factor : null
		});
		busy = false;
	}
</script>

<div class="events" class:compact>
	{#each rn.events as e (e.id)}
		{@const d = describeEvent(e, n)}
		<div class="event">
			<Icon name="bolt" size={13} />
			<span>{d.what} <b>{rn.hospitalName(e.hospital_id)}</b> · {d.when}</span>
			<button class="x" onclick={() => rn.removeEvent(e.id)} aria-label="Remove"><Icon name="x" size={12} /></button>
		</div>
	{:else}
		<p class="none">No closures or bed cuts yet, so this is the baseline.</p>
	{/each}
	{#if rn.notice}<p class="notice">{rn.notice}</p>{/if}

	<div class="form">
		<div class="kinds" role="radiogroup" aria-label="Event">
			<button role="radio" aria-checked={kind === 'close_hospital'} class:on={kind === 'close_hospital'} onclick={() => (kind = 'close_hospital')}>Close a hospital</button>
			<button role="radio" aria-checked={kind === 'set_capacity'} class:on={kind === 'set_capacity'} onclick={() => (kind = 'set_capacity')}>Cut its beds</button>
		</div>
		<select class="input" bind:value={hospital} aria-label="Hospital">
			{#each hospitals as h (h.id)}<option value={h.id}>{h.name}</option>{/each}
		</select>
		{#if kind === 'set_capacity'}
			<Slider label="Beds left open" value={factor} min={0} max={1} step={0.05} format={(v) => pct(v)} onchange={(v) => (factor = v)} />
		{/if}
		<div class="row2">
			<label><span>From week</span><input class="input" type="number" min="1" max={n} bind:value={from} /></label>
			<label><span>Through week</span><input class="input" type="number" min={from} max={n} bind:value={to} /></label>
		</div>
		<button class="btn" onclick={add} disabled={!hospital || busy}>
			<Icon name="plus" size={13} /> Add {kind === 'close_hospital' ? 'closure' : 'bed cut'}
		</button>
	</div>
</div>

<style>
	.events {
		display: flex;
		flex-direction: column;
		gap: 6px;
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
	.none,
	.notice {
		font-size: 12px;
		color: var(--text-3);
		line-height: 1.5;
		margin: 0;
	}
	.notice {
		color: #ffb199;
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-top: 6px;
	}
	.kinds {
		display: grid;
		grid-template-columns: 1fr 1fr;
		background: var(--bg);
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 2px;
		gap: 2px;
	}
	.kinds button {
		border: 0;
		background: transparent;
		color: var(--text-3);
		font: inherit;
		font-size: 12px;
		padding: 6px 8px;
		border-radius: 6px;
		cursor: pointer;
	}
	.kinds button.on {
		background: var(--elev);
		color: var(--text-1);
		box-shadow: 0 0 0 1px var(--line-2);
	}
	.row2 {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px;
	}
	.row2 label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 11px;
		color: var(--text-3);
	}
	.compact .form {
		max-width: 420px;
	}
</style>
