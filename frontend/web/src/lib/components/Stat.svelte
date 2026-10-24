<script lang="ts">
	interface Props {
		label: string;
		value: string;
		hint?: string;
		tone?: 'default' | 'good' | 'warning' | 'serious' | 'critical';
		dot?: string;
	}
	let { label, value, hint, tone = 'default', dot }: Props = $props();
</script>

<div class="stat">
	<div class="label">
		{#if dot}<i style:background={dot}></i>{/if}
		{#if tone !== 'default'}<i class="tone {tone}"></i>{/if}
		{label}
	</div>
	<div class="value">{value}</div>
	{#if hint}<div class="hint">{hint}</div>{/if}
</div>

<style>
	.stat {
		min-width: 0;
	}
	.label {
		font-size: 12px;
		color: var(--text-3);
		display: flex;
		align-items: center;
		gap: 6px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.label i {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.tone.good { background: var(--good); }
	.tone.warning { background: var(--warning); }
	.tone.serious { background: var(--serious); }
	.tone.critical { background: var(--critical); }
	.value {
		font-size: 22px;
		font-weight: 600;
		color: var(--text-1);
		margin-top: 4px;
		letter-spacing: -0.01em;
	}
	.hint {
		font-size: 11.5px;
		color: var(--text-3);
		margin-top: 2px;
	}
</style>
