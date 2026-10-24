<script lang="ts">
	import type { Snippet } from 'svelte';

	// A folded section for the technical charts: closed by default, rendered only when opened.
	interface Props {
		title?: string;
		sub?: string;
		children: Snippet;
	}
	let { title = 'Technical detail', sub = '', children }: Props = $props();
	let open = $state(false);
</script>

<section class="more" class:open>
	<button class="head" onclick={() => (open = !open)} aria-expanded={open}>
		<span class="t">
			<b>{title}</b>
			{#if sub}<small>{sub}</small>{/if}
		</span>
		<i></i>
	</button>
	{#if open}<div class="body">{@render children()}</div>{/if}
</section>

<style>
	.more {
		border: 1px dashed var(--line-2);
		border-radius: 14px;
	}
	.more.open {
		border-style: solid;
	}
	.head {
		all: unset;
		box-sizing: border-box;
		width: 100%;
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 14px 18px;
		cursor: pointer;
	}
	.head:hover b {
		color: var(--text-1);
	}
	.t {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	b {
		font-size: 13px;
		font-weight: 500;
		color: var(--text-2);
	}
	small {
		font-size: 12px;
		color: var(--text-3);
	}
	i {
		margin-left: auto;
		width: 7px;
		height: 7px;
		border-right: 1.5px solid var(--text-3);
		border-bottom: 1.5px solid var(--text-3);
		transform: rotate(45deg);
		transition: transform 0.15s;
	}
	.open i {
		transform: rotate(-135deg);
	}
	.body {
		padding: 0 16px 16px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
</style>
