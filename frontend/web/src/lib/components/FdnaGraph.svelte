<script lang="ts">
	import type { SystemResult } from '#lib/api.ts';
	import { operabilityColor } from '#lib/colors.ts';

	interface Props {
		sys: SystemResult;
		t: number;
		selected?: string | null;
		onnode?: (node: string) => void;
	}
	let { sys, t, selected = null, onnode }: Props = $props();

	let width = $state(700);
	let hover = $state<string | null>(null);
	const rowH = 48;
	const top = 26;

	const hospitals = $derived(sys.hospitals);
	const shared = $derived(sys.nodes.filter((n) => !n.includes('.')));
	const height = $derived(top + hospitals.length * rowH + 10);
	const xs = $derived({ shared: 70, res: width * 0.42, hosp: width - 150 });

	const P = $derived(Object.fromEntries(sys.nodes.map((n, i) => [n, sys.node_operability[t]?.[i] ?? 100])));

	const pos = $derived.by(() => {
		const out: Record<string, { x: number; y: number; r: number; label: string }> = {};
		hospitals.forEach((h, i) => {
			const cy = top + i * rowH + rowH / 2;
			const local = sys.nodes.filter((n) => n.startsWith(`${h}.`) && !n.endsWith('.hospital'));
			local.forEach((n, k) => {
				out[n] = {
					x: xs.res,
					y: cy + (k - (local.length - 1) / 2) * 13,
					r: 4.5,
					label: n.split('.')[1]
				};
			});
			out[`${h}.hospital`] = { x: xs.hosp, y: cy, r: 9, label: h };
		});
		shared.forEach((n, k) => {
			const span = hospitals.length * rowH;
			out[n] = {
				x: xs.shared,
				y: top + ((k + 1) / (shared.length + 1)) * span,
				r: 9,
				label: n.replaceAll('_', ' ')
			};
		});
		return out;
	});

	function edgePath(a: { x: number; y: number }, b: { x: number; y: number }) {
		const mx = (a.x + b.x) / 2;
		return `M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`;
	}

	const focus = $derived(hover ?? selected);
	const related = $derived.by(() => {
		if (!focus) return null;
		const s = new Set([focus]);
		sys.edges.forEach((e) => {
			if (e.src === focus) s.add(e.dst);
			if (e.dst === focus) s.add(e.src);
		});
		return s;
	});
	const hoverEdges = $derived(focus ? sys.edges.filter((e) => e.src === focus || e.dst === focus) : []);
</script>

<div class="fdna" bind:clientWidth={width}>
	<svg {width} {height} role="img" aria-label="FDNA dependency graph">
		<text class="col" x={xs.shared} y="12" text-anchor="middle">shared</text>
		<text class="col" x={xs.res} y="12" text-anchor="middle">resources per hospital</text>
		<text class="col" x={xs.hosp} y="12" text-anchor="middle">hospital</text>
		{#each sys.edges as e (e.src + e.dst)}
			{@const a = pos[e.src]}
			{@const b = pos[e.dst]}
			{#if a && b}
				<path
					d={edgePath(a, b)}
					fill="none"
					stroke={P[e.src] < 95 ? operabilityColor(P[e.src]) : '#4a4a52'}
					stroke-width={0.6 + e.sod * 2.2}
					stroke-opacity={related ? (related.has(e.src) && related.has(e.dst) ? 0.95 : 0.06) : e.src.includes('.') ? 0.55 : 0.16}
				/>
			{/if}
		{/each}
		{#each Object.entries(pos) as [n, p] (n)}
			{@const isHosp = n.endsWith('.hospital')}
			<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
			<g
				class="node"
				class:dim={related && !related.has(n)}
				transform="translate({p.x},{p.y})"
				onpointerenter={() => (hover = n)}
				onpointerleave={() => (hover = null)}
				onclick={() => onnode?.(n)}
			>
				<circle r={p.r + 6} fill="transparent" />
				<circle
					r={p.r}
					fill={P[n] >= 95 ? '#2c2c30' : operabilityColor(P[n])}
					stroke={selected === n ? '#f0efec' : P[n] >= 95 ? '#5a5a62' : operabilityColor(P[n])}
					stroke-width={selected === n ? 2 : 1.5}
				/>
				{#if isHosp}
					<text x={p.r + 8} dy="0.32em" class="hl">{p.label}</text>
					<text x={p.r + 8} dy="1.6em" class="pv">{Math.round(P[n])}%</text>
				{:else if n.includes('.')}
					<text x={-p.r - 6} dy="0.32em" text-anchor="end" class="rl">{p.label}</text>
				{:else}
					<text x={-p.r - 8} dy="0.32em" text-anchor="end" class="hl">{p.label}</text>
					<text x={-p.r - 8} dy="1.6em" text-anchor="end" class="pv">{Math.round(P[n])}%</text>
				{/if}
			</g>
		{/each}
	</svg>
	<div class="info">
		{#if focus}
			<b>{focus}</b> operability {Math.round(P[focus])}%
			{#each hoverEdges as e (e.src + e.dst)}
				<span>· {e.src === focus ? `feeds ${e.dst}` : `fed by ${e.src}`} (SOD {e.sod}, COD {e.cod})</span>
			{/each}
		{:else}
			Hover a node to see its dependencies; click a node to plan a disruption. Edge width = strength of dependency (SOD).
		{/if}
	</div>
</div>

<style>
	svg {
		display: block;
		overflow: visible;
	}
	.col {
		fill: var(--text-3);
		font-size: 10.5px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}
	.node {
		cursor: pointer;
		transition: opacity 0.15s;
	}
	.node.dim {
		opacity: 0.25;
	}
	.hl {
		fill: var(--text-1);
		font-size: 12px;
		font-weight: 500;
	}
	.pv {
		fill: var(--text-3);
		font-size: 10.5px;
		font-family: var(--mono);
	}
	.rl {
		fill: var(--text-3);
		font-size: 10px;
	}
	.info {
		font-size: 12px;
		color: var(--text-3);
		margin-top: 8px;
		min-height: 18px;
		line-height: 1.5;
	}
	.info b {
		color: var(--text-1);
		font-weight: 500;
	}
</style>
