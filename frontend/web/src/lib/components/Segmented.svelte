<script lang="ts" generics="T extends string">
	interface Props {
		options: { value: T; label: string }[];
		value: T;
		onchange: (v: T) => void;
		size?: 'sm' | 'md';
	}
	let { options, value, onchange, size = 'sm' }: Props = $props();
</script>

<div class="seg {size}" role="tablist">
	{#each options as o (o.value)}
		<button role="tab" aria-selected={o.value === value} class:on={o.value === value} onclick={() => onchange(o.value)}
			>{o.label}</button
		>
	{/each}
</div>

<style>
	.seg {
		display: inline-flex;
		background: var(--bg);
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 2px;
		gap: 2px;
		flex-wrap: wrap;
	}
	button {
		border: 0;
		background: transparent;
		color: var(--text-3);
		font: inherit;
		font-size: 12px;
		padding: 4px 9px;
		border-radius: 6px;
		cursor: pointer;
		white-space: nowrap;
	}
	.md button {
		padding: 6px 12px;
		font-size: 12.5px;
	}
	button:hover {
		color: var(--text-1);
	}
	button.on {
		background: var(--elev);
		color: var(--text-1);
		box-shadow: 0 0 0 1px var(--line-2);
	}
</style>
