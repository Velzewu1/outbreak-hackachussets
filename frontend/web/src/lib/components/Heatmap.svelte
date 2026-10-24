<script lang="ts">
	import { shortDate } from '#lib/format.ts';

	interface Props {
		rows: string[];
		dates: string[];
		values: (number | null)[][]; // [time][row]
		color: (v: number) => string; // v already normalised to 0..1
		max?: number;
		min?: number;
		format: (v: number) => string;
		marker?: number | null;
		selected?: string | null;
		flags?: (boolean | number)[][] | null; // [time][row] drawn as a thin top tick (e.g. diversion)
		rowHeight?: number;
		onrow?: (row: string) => void;
		onscrub?: (i: number) => void;
		legend?: string;
	}
	let {
		rows,
		dates,
		values,
		color,
		max,
		min = 0,
		format,
		marker = null,
		selected = null,
		flags = null,
		rowHeight = 18,
		onrow,
		onscrub,
		legend
	}: Props = $props();

	let width = $state(600);
	let canvas: HTMLCanvasElement | undefined = $state();
	let hover = $state<{ r: number; t: number } | null>(null);
	const labelW = 132;
	const plotW = $derived(Math.max(10, width - labelW));
	const height = $derived(rows.length * rowHeight);
	const hi = $derived(
		max ?? Math.max(1e-12, ...values.flatMap((row) => row.map((v) => (v === null ? 0 : v))))
	);

	$effect(() => {
		if (!canvas) return;
		const dpr = window.devicePixelRatio || 1;
		canvas.width = plotW * dpr;
		canvas.height = height * dpr;
		const ctx = canvas.getContext('2d')!;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, plotW, height);
		const n = dates.length;
		const cw = plotW / n;
		for (let t = 0; t < n; t++) {
			for (let r = 0; r < rows.length; r++) {
				const v = values[t]?.[r];
				ctx.fillStyle = v === null || v === undefined ? '#151518' : color((v - min) / (hi - min));
				ctx.fillRect(t * cw, r * rowHeight + 1, Math.ceil(cw) + 0.5, rowHeight - 2);
				if (flags?.[t]?.[r]) {
					ctx.fillStyle = '#ffffff';
					ctx.fillRect(t * cw, r * rowHeight + 1, Math.ceil(cw) + 0.5, 2);
				}
			}
		}
	});

	function at(evt: PointerEvent) {
		const rect = (evt.currentTarget as HTMLElement).getBoundingClientRect();
		const t = Math.floor(((evt.clientX - rect.left) / plotW) * dates.length);
		const r = Math.floor((evt.clientY - rect.top) / rowHeight);
		return { t: Math.max(0, Math.min(dates.length - 1, t)), r: Math.max(0, Math.min(rows.length - 1, r)) };
	}
</script>

<div class="heat" bind:clientWidth={width}>
	<div class="grid" style:grid-template-columns="{labelW}px 1fr">
		<div class="labels">
			{#each rows as r (r)}
				<button
					class="rl"
					class:sel={r === selected}
					style:height="{rowHeight}px"
					onclick={() => onrow?.(r)}
					disabled={!onrow}>{r}</button
				>
			{/each}
		</div>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="plot"
			style:height="{height}px"
			onpointermove={(e) => {
				hover = at(e);
				if (e.buttons === 1) onscrub?.(hover.t);
			}}
			onpointerdown={(e) => onscrub?.(at(e).t)}
			onpointerleave={() => (hover = null)}
		>
			<canvas bind:this={canvas} style:width="{plotW}px" style:height="{height}px"></canvas>
			{#if selected && rows.indexOf(selected) >= 0}
				<div class="selrow" style:top="{rows.indexOf(selected) * rowHeight}px" style:height="{rowHeight}px"></div>
			{/if}
			{#if marker !== null}
				<div class="mk" style:left="{((marker + 0.5) / dates.length) * plotW}px"></div>
			{/if}
			{#if hover}
				<div
					class="tip"
					class:flip={hover.t > dates.length * 0.6}
					style:left="{((hover.t + 0.5) / dates.length) * plotW}px"
					style:top="{hover.r * rowHeight}px"
				>
					<span>{rows[hover.r]} · {shortDate(dates[hover.t])}</span>
					<b>{values[hover.t]?.[hover.r] === null ? '–' : format(values[hover.t]?.[hover.r] as number)}</b>
					{#if flags?.[hover.t]?.[hover.r]}<em>on diversion</em>{/if}
				</div>
			{/if}
		</div>
	</div>
	<div class="foot" style:padding-left="{labelW}px">
		<span>{shortDate(dates[0])}</span>
		{#if legend}
			<span class="scale">
				<span>{format(min)}</span><i style:background="linear-gradient(90deg, {color(0)}, {color(0.5)}, {color(1)})"></i><span
					>{format(hi)}</span
				>
				<span class="lg">{legend}</span>
			</span>
		{/if}
		<span>{shortDate(dates[dates.length - 1])}</span>
	</div>
</div>

<style>
	.grid {
		display: grid;
	}
	.labels {
		display: flex;
		flex-direction: column;
	}
	.rl {
		all: unset;
		font-size: 12px;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		padding-right: 10px;
		cursor: pointer;
		display: flex;
		align-items: center;
	}
	.rl:disabled {
		cursor: default;
	}
	.rl.sel {
		color: var(--text-1);
		font-weight: 600;
	}
	.plot {
		position: relative;
		cursor: crosshair;
	}
	canvas {
		display: block;
		border-radius: 4px;
	}
	.selrow {
		position: absolute;
		left: -2px;
		right: -2px;
		border: 1px solid var(--text-1);
		border-radius: 4px;
		pointer-events: none;
	}
	.mk {
		position: absolute;
		top: -4px;
		bottom: -4px;
		width: 1px;
		background: var(--text-1);
		opacity: 0.6;
		pointer-events: none;
	}
	.tip {
		position: absolute;
		transform: translate(10px, -110%);
		background: var(--elev);
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 6px 9px;
		font-size: 12px;
		white-space: nowrap;
		pointer-events: none;
		display: flex;
		gap: 10px;
		z-index: 4;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.4);
	}
	.tip.flip {
		transform: translate(calc(-100% - 10px), -110%);
	}
	.tip span {
		color: var(--text-3);
	}
	.tip b {
		color: var(--text-1);
		font-weight: 500;
	}
	.tip em {
		color: var(--critical);
		font-style: normal;
	}
	.foot {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 11px;
		color: var(--text-3);
		margin-top: 8px;
		gap: 12px;
	}
	.scale {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.scale i {
		width: 90px;
		height: 6px;
		border-radius: 3px;
	}
	.lg {
		margin-left: 6px;
	}
</style>
