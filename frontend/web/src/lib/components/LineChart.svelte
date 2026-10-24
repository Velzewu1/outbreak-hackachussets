<script lang="ts" module>
	export interface LineSeries {
		id: string;
		label: string;
		values: (number | null)[];
		color: string;
		dashed?: boolean;
		width?: number;
		area?: boolean;
		muted?: boolean; // thin, low-opacity (ensemble samples)
		hideInTooltip?: boolean;
	}
	export interface Band {
		lo: (number | null)[];
		hi: (number | null)[];
		color: string;
		opacity?: number;
	}
</script>

<script lang="ts">
	import { scaleLinear, scaleUtc } from 'd3-scale';
	import { area as d3area, line as d3line, curveMonotoneX } from 'd3-shape';
	import { parseDate, shortDate, num } from '#lib/format.ts';

	interface Props {
		dates: string[];
		series: LineSeries[];
		bands?: Band[];
		height?: number;
		yFormat?: (v: number) => string;
		yMin?: number;
		yMax?: number;
		refLine?: { value: number; label: string } | null;
		marker?: number | null;
		onscrub?: (i: number) => void;
		legend?: boolean;
		xTicks?: number;
	}

	let {
		dates,
		series,
		bands = [],
		height = 220,
		yFormat = (v: number) => num(v),
		yMin,
		yMax,
		refLine = null,
		marker = null,
		onscrub,
		legend = true,
		xTicks = 5
	}: Props = $props();

	let width = $state(600);
	let hover = $state<number | null>(null);
	let dragging = $state(false);

	const m = { top: 10, right: 14, bottom: 24, left: 46 };
	const iw = $derived(Math.max(10, width - m.left - m.right));
	const ih = $derived(Math.max(10, height - m.top - m.bottom));

	const times = $derived(dates.map((d) => parseDate(d) as Date));
	const x = $derived(
		scaleUtc()
			.domain([times[0] ?? new Date(), times[times.length - 1] ?? new Date()])
			.range([0, iw])
	);

	const extent = $derived.by(() => {
		let lo = Infinity,
			hi = -Infinity;
		const scan = (vs: (number | null)[]) => {
			for (const v of vs) {
				if (v === null || !Number.isFinite(v)) continue;
				if (v < lo) lo = v;
				if (v > hi) hi = v;
			}
		};
		series.forEach((s) => scan(s.values));
		bands.forEach((b) => {
			scan(b.lo);
			scan(b.hi);
		});
		if (refLine) scan([refLine.value]);
		if (!Number.isFinite(lo)) [lo, hi] = [0, 1];
		const low = yMin ?? Math.min(0, lo);
		const high = yMax ?? (hi > low ? hi : low + (Math.abs(hi) || 1));
		return [low, high];
	});
	const y = $derived(scaleLinear().domain(extent).nice(4).range([ih, 0]));

	const lineGen = $derived(
		d3line<number | null>()
			.defined((v) => v !== null && Number.isFinite(v))
			.x((_, i) => x(times[i]))
			.y((v) => y(v as number))
			.curve(curveMonotoneX)
	);
	const areaGen = $derived(
		d3area<number | null>()
			.defined((v) => v !== null && Number.isFinite(v))
			.x((_, i) => x(times[i]))
			.y0(ih)
			.y1((v) => y(v as number))
			.curve(curveMonotoneX)
	);
	function bandPath(b: Band) {
		const gen = d3area<number>()
			.defined((i) => b.lo[i] !== null && b.hi[i] !== null)
			.x((i) => x(times[i]))
			.y0((i) => y(b.lo[i] as number))
			.y1((i) => y(b.hi[i] as number))
			.curve(curveMonotoneX);
		return gen(dates.map((_, i) => i)) ?? '';
	}

	const yTicks = $derived(y.ticks(4));
	const xt = $derived(x.ticks(Math.max(4, Math.min(xTicks + 2, Math.floor(iw / 70)))));

	function indexAt(evt: PointerEvent) {
		const svg = (evt.currentTarget as SVGElement).getBoundingClientRect();
		const px = evt.clientX - svg.left - m.left;
		const t = x.invert(Math.max(0, Math.min(iw, px))).getTime();
		let best = 0;
		for (let i = 0; i < times.length; i++) {
			if (Math.abs(times[i].getTime() - t) < Math.abs(times[best].getTime() - t)) best = i;
		}
		return best;
	}

	function move(evt: PointerEvent) {
		hover = indexAt(evt);
		if (dragging && onscrub) onscrub(hover);
	}
	function down(evt: PointerEvent) {
		if (!onscrub) return;
		dragging = true;
		(evt.currentTarget as Element).setPointerCapture(evt.pointerId);
		onscrub(indexAt(evt));
	}

	const shown = $derived(series.filter((s) => !s.hideInTooltip && !s.muted));
	const legendItems = $derived(shown.length > 1 && legend ? shown : []);
	const tipLeft = $derived(hover === null ? 0 : m.left + x(times[hover]));
</script>

<div class="chart" bind:clientWidth={width}>
	{#if legendItems.length}
		<div class="legend">
			{#each legendItems as s (s.id)}
				<span class="key"
					><i style:background={s.color} class:dashed={s.dashed}></i>{s.label}</span
				>
			{/each}
		</div>
	{/if}
	<svg
		{width}
		{height}
		role="img"
		aria-label={shown.map((s) => s.label).join(', ')}
		onpointermove={move}
		onpointerleave={() => ((hover = null), (dragging = false))}
		onpointerdown={down}
		onpointerup={() => (dragging = false)}
		class:scrub={!!onscrub}
	>
		<g transform="translate({m.left},{m.top})">
			{#each yTicks as t (t)}
				<line class="grid" x1="0" x2={iw} y1={y(t)} y2={y(t)} />
				<text class="tick" x="-8" y={y(t)} dy="0.32em" text-anchor="end">{yFormat(t)}</text>
			{/each}
			{#each xt as t (t.getTime())}
				<text class="tick" x={x(t)} y={ih + 16} text-anchor="middle"
					>{t.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })}</text
				>
			{/each}
			<line class="axis" x1="0" x2={iw} y1={ih} y2={ih} />

			{#each bands as b, i (i)}
				<path d={bandPath(b)} fill={b.color} fill-opacity={b.opacity ?? 0.14} />
			{/each}
			{#each series as s (s.id)}
				{#if s.area}
					<path d={areaGen(s.values) ?? ''} fill={s.color} fill-opacity="0.1" />
				{/if}
			{/each}
			{#if refLine}
				<line class="ref" x1="0" x2={iw} y1={y(refLine.value)} y2={y(refLine.value)} />
				<text class="reflabel" x={iw - 4} y={y(refLine.value) - 5} text-anchor="end"
					>{refLine.label}</text
				>
			{/if}
			{#each series as s (s.id)}
				<path
					d={lineGen(s.values) ?? ''}
					fill="none"
					stroke={s.color}
					stroke-width={s.muted ? 1 : (s.width ?? 2)}
					stroke-opacity={s.muted ? 0.28 : 1}
					stroke-dasharray={s.dashed ? '4 4' : undefined}
					stroke-linejoin="round"
					stroke-linecap="round"
				/>
			{/each}

			{#if marker !== null && marker !== undefined && times[marker]}
				<line class="marker" x1={x(times[marker])} x2={x(times[marker])} y1="0" y2={ih} />
			{/if}
			{#if hover !== null}
				<line class="cross" x1={x(times[hover])} x2={x(times[hover])} y1="0" y2={ih} />
				{#each shown as s (s.id)}
					{#if s.values[hover] !== null && s.values[hover] !== undefined}
						<circle
							cx={x(times[hover])}
							cy={y(s.values[hover] as number)}
							r="4"
							fill={s.color}
							stroke="var(--panel)"
							stroke-width="2"
						/>
					{/if}
				{/each}
			{/if}
		</g>
	</svg>
	{#if hover !== null}
		<div class="tip" style:left="{tipLeft}px" class:flip={tipLeft > width * 0.6}>
			<div class="tipdate">{shortDate(dates[hover])}</div>
			{#each shown as s (s.id)}
				<div class="tiprow">
					<i style:background={s.color}></i><span>{s.label}</span><b
						>{s.values[hover] === null ? '–' : yFormat(s.values[hover] as number)}</b
					>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.chart {
		position: relative;
		width: 100%;
		user-select: none;
	}
	svg {
		display: block;
		overflow: visible;
		touch-action: pan-y;
	}
	svg.scrub {
		cursor: ew-resize;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		margin: 0 0 6px 46px;
		font-size: 12px;
		color: var(--text-2);
	}
	.key {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.key i {
		width: 12px;
		height: 2px;
		border-radius: 1px;
		display: inline-block;
	}
	.key i.dashed {
		background: repeating-linear-gradient(90deg, currentColor 0 3px, transparent 3px 6px) !important;
	}
	.grid {
		stroke: var(--grid);
		stroke-width: 1;
	}
	.axis {
		stroke: var(--axis);
	}
	.tick {
		fill: var(--text-3);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}
	.ref {
		stroke: var(--text-3);
		stroke-dasharray: 2 4;
	}
	.reflabel {
		fill: var(--text-3);
		font-size: 11px;
	}
	.marker {
		stroke: var(--text-1);
		stroke-opacity: 0.35;
	}
	.cross {
		stroke: var(--text-2);
		stroke-opacity: 0.5;
	}
	.tip {
		position: absolute;
		top: 8px;
		transform: translateX(12px);
		background: var(--elev);
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 8px 10px;
		font-size: 12px;
		pointer-events: none;
		min-width: 150px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.4);
		z-index: 5;
	}
	.tip.flip {
		transform: translateX(calc(-100% - 12px));
	}
	.tipdate {
		color: var(--text-3);
		margin-bottom: 4px;
	}
	.tiprow {
		display: grid;
		grid-template-columns: 10px 1fr auto;
		align-items: center;
		gap: 8px;
		color: var(--text-2);
		line-height: 1.6;
	}
	.tiprow i {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}
	.tiprow b {
		color: var(--text-1);
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}
</style>
