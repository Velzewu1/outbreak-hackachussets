<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { longDate } from '#lib/format.ts';
	import Icon from './Icon.svelte';

	let width = $state(400);
	let raf = 0;
	let last = 0;
	const SPEED = 9; // days per second

	const series = $derived(app.result ? (app.result.epi.citywide.inpatients ?? app.result.epi.citywide.infectious) : []);
	const hi = $derived(Math.max(1e-9, ...series.map((v) => v ?? 0)));
	const d = $derived(
		series
			.map((v, i) => `${i ? 'L' : 'M'}${((i / Math.max(1, series.length - 1)) * width).toFixed(1)},${(26 - ((v ?? 0) / hi) * 22).toFixed(1)}`)
			.join('')
	);
	const diversion = $derived(
		app.result?.system ? app.result.system.on_diversion.map((row) => row.some(Boolean)) : []
	);

	function tick(now: number) {
		if (!app.playing) return;
		const dt = (now - last) / 1000;
		if (dt >= 1 / SPEED) {
			last = now;
			if (app.day >= app.nDays - 1) {
				app.playing = false;
				return;
			}
			app.day += 1;
		}
		raf = requestAnimationFrame(tick);
	}

	function toggle() {
		if (app.playing) {
			app.playing = false;
			cancelAnimationFrame(raf);
			return;
		}
		if (app.day >= app.nDays - 1) app.day = 0;
		app.playing = true;
		last = performance.now();
		raf = requestAnimationFrame(tick);
	}

	function scrub(e: PointerEvent) {
		const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
		const f = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		app.day = Math.round(f * (app.nDays - 1));
	}

	function key(e: KeyboardEvent) {
		if ((e.target as HTMLElement).closest('input, select, textarea')) return;
		if (e.code === 'Space') {
			e.preventDefault();
			toggle();
		} else if (e.key === 'ArrowRight') app.day = Math.min(app.nDays - 1, app.day + (e.shiftKey ? 7 : 1));
		else if (e.key === 'ArrowLeft') app.day = Math.max(0, app.day - (e.shiftKey ? 7 : 1));
	}
</script>

<svelte:window onkeydown={key} />

<div class="timeline">
	<button class="play" onclick={toggle} aria-label={app.playing ? 'Pause' : 'Play'} title="Space">
		<Icon name={app.playing ? 'pause' : 'play'} size={14} />
	</button>
	<div class="when">
		<div class="date">{longDate(app.date)}</div>
		<div class="day">day {app.day + 1} of {app.nDays}</div>
	</div>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="track"
		bind:clientWidth={width}
		onpointerdown={(e) => {
			(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
			scrub(e);
		}}
		onpointermove={(e) => e.buttons === 1 && scrub(e)}
	>
		<svg {width} height="28" aria-hidden="true">
			{#each diversion as on, i (i)}
				{#if on}
					<rect
						x={(i / Math.max(1, diversion.length - 1)) * width - 1}
						y="0"
						width={Math.max(2, width / diversion.length)}
						height="28"
						fill="var(--critical)"
						fill-opacity="0.18"
					/>
				{/if}
			{/each}
			<path d="{d}L{width},28L0,28Z" fill="var(--accent)" fill-opacity="0.12" />
			<path {d} fill="none" stroke="var(--accent)" stroke-width="1.5" />
		</svg>
		<div class="head" style:left="{(app.day / Math.max(1, app.nDays - 1)) * 100}%"></div>
	</div>
	<div class="legend">
		<span><i class="a"></i>{app.result?.epi.citywide.inpatients ? 'Inpatients' : 'Infectious'}</span>
		{#if diversion.some(Boolean)}<span><i class="c"></i>Any hospital diverting</span>{/if}
	</div>
</div>

<style>
	.timeline {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 10px 18px;
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
		width: 128px;
		flex-shrink: 0;
	}
	.date {
		font-size: 13px;
		font-weight: 500;
	}
	.day {
		font-size: 11.5px;
		color: var(--text-3);
		font-variant-numeric: tabular-nums;
	}
	.track {
		position: relative;
		flex: 1;
		height: 28px;
		cursor: ew-resize;
		touch-action: none;
	}
	svg {
		display: block;
	}
	.head {
		position: absolute;
		top: -4px;
		bottom: -4px;
		width: 2px;
		margin-left: -1px;
		background: var(--text-1);
		border-radius: 1px;
		box-shadow: 0 0 0 3px rgb(240 239 236 / 0.08);
		pointer-events: none;
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
	.legend .a {
		background: var(--accent);
	}
	.legend .c {
		background: rgb(208 59 59 / 0.5);
	}
	@media (max-width: 800px) {
		.legend {
			display: none;
		}
		.when {
			width: auto;
		}
	}
</style>
