<script lang="ts">
	import { rn, weekLabel } from '#lib/rn.svelte.ts';
	import { num } from '#lib/format.ts';
	import Icon from './Icon.svelte';
	import Segmented from './Segmented.svelte';
	import type { Phase } from '#lib/rn-api.ts';

	// One column per simulated week; its height is the need for a bed that week (people/week).
	const r = $derived(rn.result!);
	const need = $derived(r.epi.need);
	const unmet = $derived(r.scenario.map((w) => w[rn.phase].metrics.unmet_need_people));
	const hi = $derived(Math.max(1e-9, ...need));
	let playing = $state(false);
	let timer: ReturnType<typeof setInterval> | null = null;

	function stop() {
		playing = false;
		if (timer) clearInterval(timer);
		timer = null;
	}
	function toggle() {
		if (playing) return stop();
		if (rn.week >= rn.nWeeks - 1) rn.week = 0;
		playing = true;
		timer = setInterval(() => {
			if (rn.week >= rn.nWeeks - 1) return stop();
			rn.week += 1;
		}, 700);
	}
	function key(e: KeyboardEvent) {
		if ((e.target as HTMLElement).closest('input, select, textarea')) return;
		if (e.code === 'Space') {
			e.preventDefault();
			toggle();
		} else if (e.key === 'ArrowRight') rn.week = Math.min(rn.nWeeks - 1, rn.week + 1);
		else if (e.key === 'ArrowLeft') rn.week = Math.max(0, rn.week - 1);
	}
	const PHASES: { value: Phase; label: string }[] = [
		{ value: 'after', label: 'After rerouting' },
		{ value: 'before', label: 'Before rerouting' }
	];
</script>

<svelte:window onkeydown={key} />

<div class="weekbar">
	<button class="play" onclick={toggle} aria-label={playing ? 'Pause' : 'Play'} title="Space">
		<Icon name={playing ? 'pause' : 'play'} size={14} />
	</button>
	<div class="when">
		<div class="w">{weekLabel(rn.week)}</div>
		<div class="of">of {rn.nWeeks} simulated weeks</div>
	</div>
	<div class="weeks" role="listbox" aria-label="Week">
		{#each need as n, i (i)}
			<button
				role="option"
				aria-selected={i === rn.week}
				class:on={i === rn.week}
				onclick={() => (rn.week = i)}
				title="{weekLabel(i)}: {num(n)} people need a bed, {num(unmet[i])} can't get one nearby"
			>
				<span class="col"
					><i class="n" style:height="{(n / hi) * 100}%"></i><i class="u" style:height="{(Math.min(n, unmet[i]) / hi) * 100}%"></i></span
				>
				<span class="lab">{i + 1}</span>
			</button>
		{/each}
	</div>
	<div class="legend">
		<span><i class="n"></i>Need a bed</span>
		<span><i class="u"></i>Can't get one</span>
	</div>
	<Segmented options={PHASES} value={rn.phase} onchange={(p) => (rn.phase = p)} />
</div>

<style>
	.weekbar {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 8px 18px;
		border-top: 1px solid var(--line);
		background: rgb(11 11 12 / 0.92);
		backdrop-filter: blur(12px);
	}
	.play {
		width: 34px;
		height: 34px;
		border-radius: 50%;
		border: 1px solid var(--line-2);
		background: var(--text-1);
		color: var(--bg);
		display: grid;
		place-items: center;
		cursor: pointer;
		flex-shrink: 0;
	}
	.when {
		width: 132px;
		flex-shrink: 0;
	}
	.w {
		font-size: 13px;
		font-weight: 500;
	}
	.of {
		font-size: 11.5px;
		color: var(--text-3);
	}
	.weeks {
		flex: 1;
		display: flex;
		gap: 4px;
		min-width: 0;
		height: 40px;
	}
	.weeks button {
		all: unset;
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
		cursor: pointer;
		border-radius: 5px;
		padding: 2px 2px 0;
		min-width: 0;
	}
	.weeks button:hover {
		background: var(--hover);
	}
	.weeks button.on {
		background: var(--elev);
		box-shadow: inset 0 0 0 1px var(--line-2);
	}
	.col {
		flex: 1;
		position: relative;
	}
	.col i {
		position: absolute;
		bottom: 0;
		left: 18%;
		right: 18%;
		border-radius: 2px 2px 0 0;
	}
	.n {
		background: #3d3d44;
	}
	.on .n {
		background: #5a5a63;
	}
	.u {
		background: var(--critical);
	}
	.lab {
		font-size: 10px;
		text-align: center;
		color: var(--text-3);
		font-variant-numeric: tabular-nums;
		line-height: 12px;
	}
	.on .lab {
		color: var(--text-1);
	}
	.legend {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 11px;
		color: var(--text-3);
		flex-shrink: 0;
	}
	.legend i {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 2px;
		margin-right: 6px;
	}
	@media (max-width: 900px) {
		.legend,
		.of {
			display: none;
		}
		.when {
			width: auto;
		}
	}
	@media (max-width: 700px) {
		.weekbar {
			flex-wrap: wrap;
			gap: 8px 12px;
			padding: 8px 12px;
		}
		.weeks {
			order: 3;
			flex-basis: 100%;
		}
	}
</style>
