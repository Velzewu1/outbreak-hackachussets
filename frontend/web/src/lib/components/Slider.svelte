<script lang="ts">
	interface Props {
		label: string;
		value: number;
		min: number;
		max: number;
		step?: number;
		format?: (v: number) => string;
		changed?: boolean;
		hint?: string;
		/** Shown under the label, for settings a newcomer needs explained. */
		help?: string;
		onchange: (v: number) => void;
	}
	let { label, value, min, max, step = 0.01, format = (v) => String(v), changed = false, hint, help, onchange }: Props =
		$props();
	let local = $state(0);
	$effect(() => {
		local = value;
	});
	const fill = $derived(((local - min) / (max - min)) * 100);
</script>

<label class="slider" title={hint}>
	<span class="row">
		<span class="name">{label}{#if changed}<i class="dot" aria-label="changed"></i>{/if}</span>
		<span class="val">{format(local)}</span>
	</span>
	{#if help}<span class="help">{help}</span>{/if}
	<input
		type="range"
		{min}
		{max}
		{step}
		bind:value={local}
		style:--fill="{fill}%"
		oninput={() => onchange(Number(local))}
	/>
</label>

<style>
	.slider {
		display: block;
		padding: 7px 0;
	}
	.row {
		display: flex;
		justify-content: space-between;
		font-size: 12.5px;
		margin-bottom: 6px;
	}
	.name {
		color: var(--text-2);
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: var(--accent);
	}
	.val {
		color: var(--text-1);
		font-family: var(--mono);
		font-size: 12px;
	}
	input {
		width: 100%;
		appearance: none;
		height: 4px;
		border-radius: 2px;
		background: linear-gradient(90deg, var(--accent) var(--fill), var(--line-2) var(--fill));
		outline: none;
		margin: 0;
	}
	input::-webkit-slider-thumb {
		appearance: none;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--text-1);
		border: 3px solid var(--bg);
		box-shadow: 0 0 0 1px var(--line-2);
		cursor: pointer;
	}
	input::-moz-range-thumb {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--text-1);
		border: 3px solid var(--bg);
		cursor: pointer;
	}
	input:focus-visible::-webkit-slider-thumb {
		box-shadow: 0 0 0 3px var(--accent-soft);
	}
	.help {
		display: block;
		font-size: 11.5px;
		color: var(--text-3);
		line-height: 1.4;
		margin: 2px 0 2px;
	}
</style>
