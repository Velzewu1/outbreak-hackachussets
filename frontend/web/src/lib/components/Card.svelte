<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title?: string;
		sub?: string;
		actions?: Snippet;
		children: Snippet;
		pad?: boolean;
		class?: string;
	}
	let { title, sub, actions, children, pad = true, class: cls = '' }: Props = $props();
</script>

<section class="card {cls}" class:pad>
	{#if title || actions}
		<header>
			<div>
				{#if title}<h3>{title}</h3>{/if}
				{#if sub}<p>{sub}</p>{/if}
			</div>
			{#if actions}<div class="actions">{@render actions()}</div>{/if}
		</header>
	{/if}
	{@render children()}
</section>

<style>
	.card {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		min-width: 0;
	}
	.card.pad {
		padding: 16px 18px 14px;
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 12px;
		margin-bottom: 12px;
	}
	h3 {
		margin: 0;
		font-size: 13px;
		font-weight: 600;
		color: var(--text-1);
		letter-spacing: 0.01em;
	}
	p {
		margin: 3px 0 0;
		font-size: 12px;
		color: var(--text-3);
		line-height: 1.45;
	}
	.actions {
		display: flex;
		gap: 6px;
		align-items: center;
		flex-shrink: 0;
	}
</style>
