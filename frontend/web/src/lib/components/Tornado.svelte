<script lang="ts">
	import type { SensitivityRow } from '#lib/api.ts';

	interface Props {
		rows: SensitivityRow[];
		format: (v: number) => string;
		rel: number;
	}
	let { rows, format, rel }: Props = $props();
	const base = $derived(rows[0]?.metric_base ?? 0);
	const span = $derived(
		Math.max(1e-12, ...rows.flatMap((r) => [Math.abs(r.metric_low - base), Math.abs(r.metric_high - base)]))
	);
	const pos = (v: number) => 50 + ((v - base) / span) * 48;
	const name = (p: string) => p.split('.').pop()!.replaceAll('_', ' ');
</script>

<div class="tornado">
	<div class="head">
		<span></span>
		<span class="legend"
			><i class="lo"></i>input −{Math.round(rel * 100)}% <i class="hi"></i>input +{Math.round(rel * 100)}%</span
		>
		<span></span>
	</div>
	{#each rows as r (r.parameter)}
		{@const a = pos(r.metric_low)}
		{@const b = pos(r.metric_high)}
		<div class="row">
			<span class="lab" title={r.parameter}>{name(r.parameter)}</span>
			<span class="track">
				<span class="axis"></span>
				<span class="bar lo" style:left="{Math.min(a, 50)}%" style:width="{Math.abs(a - 50)}%"></span>
				<span class="bar hi" style:left="{Math.min(b, 50)}%" style:width="{Math.abs(b - 50)}%"></span>
			</span>
			<span class="val"
				>{format(r.metric_low)} → {format(r.metric_high)}{#if r.elasticity !== null}<em
						>ε {r.elasticity.toFixed(2)}</em
					>{/if}</span
			>
		</div>
	{/each}
	<div class="base">base {format(base)}</div>
</div>

<style>
	.head,
	.row {
		display: grid;
		grid-template-columns: 130px 1fr 170px;
		gap: 12px;
		align-items: center;
	}
	.head {
		margin-bottom: 8px;
	}
	.legend {
		font-size: 11.5px;
		color: var(--text-3);
		display: flex;
		gap: 6px;
		align-items: center;
		justify-content: center;
	}
	.legend i {
		width: 10px;
		height: 10px;
		border-radius: 2px;
		display: inline-block;
		margin-left: 8px;
	}
	.row {
		padding: 5px 0;
	}
	.lab {
		font-size: 12.5px;
		color: var(--text-2);
		text-transform: capitalize;
	}
	.track {
		position: relative;
		height: 14px;
	}
	.axis {
		position: absolute;
		left: 50%;
		top: -6px;
		bottom: -6px;
		width: 1px;
		background: var(--axis);
	}
	.bar {
		position: absolute;
		top: 0;
		bottom: 0;
		border-radius: 3px;
	}
	.lo,
	.legend .lo {
		background: #3987e5;
	}
	.hi,
	.legend .hi {
		background: #d95926;
	}
	.val {
		font-family: var(--mono);
		font-size: 11.5px;
		color: var(--text-1);
		text-align: right;
	}
	.val em {
		font-style: normal;
		color: var(--text-3);
		margin-left: 8px;
	}
	.base {
		text-align: center;
		font-size: 11.5px;
		color: var(--text-3);
		margin-top: 6px;
	}
</style>
