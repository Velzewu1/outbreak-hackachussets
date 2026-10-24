<script lang="ts">
	import '../app.css';
	import favicon from '#lib/assets/favicon.svg';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { app } from '#lib/state.svelte.ts';
	import Controls from '#lib/components/Controls.svelte';
	import Timeline from '#lib/components/Timeline.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	let bootError = $state<string | null>(null);

	const NAV = [
		{ href: '/', label: 'Map', icon: 'map' },
		{ href: '/epidemic', label: 'Epidemic', icon: 'pulse' },
		{ href: '/hospitals', label: 'Hospitals', icon: 'hospital' },
		{ href: '/uncertainty', label: 'Uncertainty', icon: 'spread' },
		{ href: '/validation', label: 'Validation', icon: 'check' },
		{ href: '/model', label: 'Model', icon: 'book' }
	];

	onMount(() => {
		if (window.innerWidth < 1200) app.controlsOpen = false;
		app.init().catch((e) => (bootError = (e as Error).message));
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Outbreak · Boston hospital cascade</title>
</svelte:head>

<div class="shell" class:closed={!app.controlsOpen}>
	<nav class="rail">
		<a class="brand" href="/" aria-label="Home">
			<span class="logo"><i></i></span>
			<span class="bt"><b>Outbreak</b><small>Boston cascade</small></span>
		</a>
		<div class="links">
			{#each NAV as n (n.href)}
				<a href={n.href} class:on={page.url.pathname === n.href} title={n.label}>
					<Icon name={n.icon} /><span>{n.label}</span>
				</a>
			{/each}
		</div>
		<div class="foot">
			<span class="tag">Research demo</span>
			<span class="note">Public aggregate data. Every assumption is labelled.</span>
		</div>
	</nav>

	<div class="main">
		<header class="bar">
			<div class="scn">
				{#if app.detail}
					<b>{app.detail.title}</b>
					<span class="muted">{app.detail.kind === 'system' ? 'SEIR + hospital cascade' : 'SEIR only'}</span>
				{/if}
			</div>
			<div class="status">
				{#if app.error}
					<span class="err" title={app.error}>⚠ {app.error.slice(0, 90)}</span>
				{:else if app.loading}
					<span class="spin"></span><span class="muted">Simulating…</span>
				{:else if app.result}
					<span class="ok"></span><span class="muted">{app.nDays} days · {Math.round(app.lastRunMs)} ms</span>
				{/if}
				<button class="btn" class:primary={!app.controlsOpen} onclick={() => (app.controlsOpen = !app.controlsOpen)}>
					<Icon name="sliders" size={14} /> {app.controlsOpen ? 'Hide controls' : 'Controls'}
					{#if app.changeCount}<span class="badge">{app.changeCount}</span>{/if}
				</button>
			</div>
		</header>

		<main class="content">
			{#if bootError}
				<div class="boot">
					<h2>Can't reach the model API</h2>
					<p>Start it from the repository root, then reload this page:</p>
					<pre>pip install -r seir/requirements.txt -r frontend/api/requirements.txt
uvicorn main:app --app-dir frontend/api --port 8000</pre>
					<p class="muted">{bootError}</p>
				</div>
			{:else if !app.result}
				<div class="boot"><span class="spin"></span> Loading scenario…</div>
			{:else}
				{@render children()}
			{/if}
		</main>

		{#if app.result}<Timeline />{/if}
	</div>

	{#if app.controlsOpen}
		<div class="drawer"><Controls /></div>
	{/if}
</div>

<style>
	.shell {
		display: grid;
		grid-template-columns: 208px minmax(0, 1fr) 316px;
		height: 100vh;
		overflow: hidden;
	}
	.shell.closed {
		grid-template-columns: 208px minmax(0, 1fr);
	}
	.rail {
		border-right: 1px solid var(--line);
		display: flex;
		flex-direction: column;
		padding: 16px 12px;
		gap: 22px;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 10px;
		text-decoration: none;
		padding: 2px 6px;
	}
	.logo {
		width: 28px;
		height: 28px;
		border-radius: 8px;
		background: radial-gradient(circle at 50% 50%, var(--accent) 0 5px, transparent 6px),
			radial-gradient(circle at 50% 50%, transparent 0 9px, rgb(213 81 129 / 0.45) 10px 11px, transparent 12px),
			var(--elev);
		border: 1px solid var(--line-2);
		position: relative;
	}
	.logo i {
		position: absolute;
		inset: -3px;
		border-radius: 10px;
		border: 1px solid rgb(213 81 129 / 0.25);
		animation: pulse 2.8s ease-out infinite;
	}
	@keyframes pulse {
		0% {
			transform: scale(0.85);
			opacity: 1;
		}
		100% {
			transform: scale(1.35);
			opacity: 0;
		}
	}
	.bt {
		display: flex;
		flex-direction: column;
		line-height: 1.15;
	}
	.bt b {
		font-size: 14px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.bt small {
		color: var(--text-3);
		font-size: 11.5px;
	}
	.links {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.links a {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 10px;
		border-radius: 8px;
		color: var(--text-3);
		text-decoration: none;
		font-size: 13px;
		transition: background 0.12s, color 0.12s;
	}
	.links a:hover {
		color: var(--text-1);
		background: var(--hover);
	}
	.links a.on {
		color: var(--text-1);
		background: var(--elev);
		box-shadow: inset 0 0 0 1px var(--line-2);
	}
	.foot {
		margin-top: auto;
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 0 6px;
		align-items: flex-start;
	}
	.note {
		font-size: 11px;
		color: var(--text-3);
		line-height: 1.45;
	}
	.main {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}
	.bar {
		height: 54px;
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 18px 0 26px;
		border-bottom: 1px solid var(--line);
		gap: 16px;
	}
	.scn {
		display: flex;
		align-items: baseline;
		gap: 10px;
		font-size: 13.5px;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
	}
	.scn .muted {
		font-size: 12px;
	}
	.status {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
		flex-shrink: 0;
	}
	.err {
		color: var(--serious);
		max-width: 420px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ok {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--good);
	}
	.spin {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		border: 2px solid var(--line-2);
		border-top-color: var(--text-1);
		animation: spin 0.7s linear infinite;
		display: inline-block;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.badge {
		background: var(--accent);
		color: #fff;
		border-radius: 999px;
		font-size: 10.5px;
		padding: 0 6px;
		line-height: 16px;
	}
	.content {
		flex: 1;
		overflow: auto;
		min-height: 0;
		position: relative;
	}
	.drawer {
		border-left: 1px solid var(--line);
		overflow-y: auto;
		background: var(--bg);
	}
	.boot {
		padding: 60px 30px;
		color: var(--text-2);
		display: flex;
		flex-direction: column;
		gap: 10px;
		align-items: flex-start;
		max-width: 680px;
	}
	.boot h2 {
		margin: 0;
		font-size: 18px;
	}
	.boot p {
		margin: 0;
	}
	pre {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 10px;
		padding: 12px 14px;
		font-family: var(--mono);
		font-size: 12px;
		color: var(--text-1);
		white-space: pre-wrap;
	}
	@media (max-width: 1200px) {
		.shell,
		.shell.closed {
			grid-template-columns: 64px minmax(0, 1fr);
		}
		.bt,
		.links span,
		.foot {
			display: none;
		}
		.drawer {
			position: fixed;
			right: 0;
			top: 54px;
			bottom: 0;
			width: 316px;
			z-index: 30;
			box-shadow: -20px 0 40px rgb(0 0 0 / 0.5);
		}
	}
</style>
