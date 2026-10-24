<script lang="ts">
	interface Props {
		values: (number | null)[];
		color?: string;
		height?: number;
		max?: number;
		marker?: number | null;
		ref?: number | null;
		fill?: boolean;
	}
	let { values, color = 'var(--accent)', height = 32, max, marker = null, ref = null, fill = true }: Props = $props();
	let width = $state(120);
	const hi = $derived(max ?? Math.max(1e-9, ...values.map((v) => v ?? 0), ref ?? 0));
	const pts = $derived(
		values.map((v, i) => [(i / Math.max(1, values.length - 1)) * width, height - 2 - ((v ?? 0) / hi) * (height - 4)])
	);
	const d = $derived(pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(''));
</script>

<div class="spark" bind:clientWidth={width} style:height="{height}px">
	<svg {width} {height} aria-hidden="true">
		{#if fill && pts.length}
			<path d="{d}L{width},{height}L0,{height}Z" fill={color} fill-opacity="0.12" />
		{/if}
		{#if ref !== null}
			<line x1="0" x2={width} y1={height - 2 - (ref / hi) * (height - 4)} y2={height - 2 - (ref / hi) * (height - 4)} stroke="var(--text-3)" stroke-dasharray="2 3" />
		{/if}
		<path {d} fill="none" stroke={color} stroke-width="1.5" stroke-linejoin="round" />
		{#if marker !== null && pts[marker]}
			<circle cx={pts[marker][0]} cy={pts[marker][1]} r="3" fill={color} stroke="var(--panel)" stroke-width="2" />
		{/if}
	</svg>
</div>

<style>
	.spark {
		width: 100%;
	}
	svg {
		display: block;
		overflow: visible;
	}
</style>
