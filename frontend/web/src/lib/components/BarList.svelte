<script lang="ts">
	interface Item {
		id: string;
		label: string;
		value: number;
		color?: string;
		note?: string;
	}
	interface Props {
		items: Item[];
		format: (v: number) => string;
		max?: number;
		selected?: string | null;
		onselect?: (id: string) => void;
		color?: string;
	}
	let { items, format, max, selected = null, onselect, color = 'var(--accent)' }: Props = $props();
	const hi = $derived(max ?? Math.max(1e-12, ...items.map((i) => Math.abs(i.value))));
</script>

<div class="bars">
	{#each items as it (it.id)}
		<button class="row" class:sel={it.id === selected} onclick={() => onselect?.(it.id)} disabled={!onselect}>
			<span class="lab">{it.label}</span>
			<span class="track">
				<span class="bar" style:width="{(Math.abs(it.value) / hi) * 100}%" style:background={it.color ?? color}></span>
			</span>
			<span class="val">{format(it.value)}{#if it.note}<em>{it.note}</em>{/if}</span>
		</button>
	{/each}
</div>

<style>
	.bars {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.row {
		all: unset;
		display: grid;
		grid-template-columns: minmax(90px, 34%) 1fr auto;
		align-items: center;
		gap: 10px;
		padding: 4px 6px;
		border-radius: 6px;
		cursor: pointer;
	}
	.row:disabled {
		cursor: default;
	}
	.row:hover:not(:disabled),
	.row.sel {
		background: var(--hover);
	}
	.lab {
		font-size: 12.5px;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.sel .lab {
		color: var(--text-1);
	}
	.track {
		height: 10px;
		display: block;
	}
	.bar {
		display: block;
		height: 100%;
		border-radius: 0 4px 4px 0;
		min-width: 2px;
	}
	.val {
		font-size: 12px;
		font-family: var(--mono);
		color: var(--text-1);
		text-align: right;
		min-width: 64px;
	}
	.val em {
		font-style: normal;
		color: var(--text-3);
		margin-left: 6px;
	}
</style>
