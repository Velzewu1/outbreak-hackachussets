<script lang="ts">
	import '../app.css';
	import favicon from '#lib/assets/favicon.svg';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { app } from '#lib/state.svelte.ts';
	import { rn } from '#lib/rn.svelte.ts';
	import Controls from '#lib/components/Controls.svelte';
	import RnControls from '#lib/components/RnControls.svelte';
	import Timeline from '#lib/components/Timeline.svelte';
	import WeekBar from '#lib/components/WeekBar.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	let bootError = $state<string | null>(null);
	let dailyError = $state<string | null>(null);

	// Two models share the site: the ResiliNet weekly pipeline (the main pages) and the
	// older daily cascade model under /daily. Each keeps its own state and controls.
	const daily = $derived(page.url.pathname === '/daily' || page.url.pathname.startsWith('/daily/'));

	const WEEKLY = [
		{
			group: 'Explore',
			items: [
				{ href: '/', label: 'Map', icon: 'map' },
				{ href: '/hospitals', label: 'Hospitals', icon: 'hospital' },
				{ href: '/tracts', label: 'Census tracts', icon: 'tracts' },
				{ href: '/scenario', label: 'Scenario lab', icon: 'lab' }
			]
		},
		{
			group: 'Behind the numbers',
			items: [
				{ href: '/validation', label: 'Tested on real data', icon: 'check' },
				{ href: '/data', label: 'Data and downloads', icon: 'data' },
				{ href: '/how', label: 'How it works', icon: 'book' }
			]
		}
	];
	const DAILY = [
		{
			group: 'Explore',
			items: [
				{ href: '/daily', label: 'Map', icon: 'map' },
				{ href: '/daily/spread', label: 'Spread', icon: 'pulse' },
				{ href: '/daily/hospitals', label: 'Hospitals', icon: 'hospital' }
			]
		},
		{
			group: 'Behind the numbers',
			items: [
				{ href: '/daily/outcomes', label: 'Range of outcomes', icon: 'spread' },
				{ href: '/daily/tested', label: 'Tested on real data', icon: 'check' },
				{ href: '/daily/how', label: 'How it works', icon: 'book' }
			]
		}
	];
	const nav = $derived(daily ? DAILY : WEEKLY);
	const open = $derived(daily ? app.controlsOpen : rn.controlsOpen);
	const changes = $derived(daily ? app.changeCount : rn.changeCount);

	onMount(() => {
		rn.init().catch((e) => (bootError = (e as Error).message));
	});
	// The daily model loads the first time one of its pages is opened.
	let dailyStarted = false;
	$effect(() => {
		if (!daily || dailyStarted) return;
		dailyStarted = true;
		app.init().catch((e) => (dailyError = (e as Error).message));
	});

	function toggleControls() {
		if (daily) app.controlsOpen = !app.controlsOpen;
		else rn.controlsOpen = !rn.controlsOpen;
	}
	const error = $derived(daily ? (dailyError ?? app.error) : (bootError ?? rn.error));
	const loading = $derived(daily ? app.loading : rn.loading);
	const ready = $derived(daily ? !!app.result : !!rn.result);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>ResiliNet · Boston hospital cascade</title>
</svelte:head>

<div class="shell" class:closed={!open}>
	<nav class="rail">
		<a class="brand" href="/" aria-label="Home">
			<span class="logo"><i></i></span>
			<span class="bt"><b>ResiliNet</b><small>Boston hospital cascade</small></span>
		</a>
		<div class="models" role="tablist" aria-label="Model">
			<a href="/" role="tab" aria-selected={!daily} class:on={!daily} title="The weekly ResiliNet pipeline">Weekly</a>
			<a href="/daily" role="tab" aria-selected={daily} class:on={daily} title="The earlier daily cascade model">Daily</a>
		</div>
		<div class="links">
			{#each nav as g (g.group)}
				<div class="group">{g.group}</div>
				{#each g.items as n (n.href)}
					<a href={n.href} class:on={page.url.pathname === n.href} title={n.label}>
						<Icon name={n.icon} /><span>{n.label}</span>
					</a>
				{/each}
			{/each}
		</div>
		<div class="foot">
			<span class="tag">Research simulation</span>
			<span class="note">
				{#if daily}
					The earlier daily model: an illustrative what-if built from public data, not a forecast.
				{:else}
					Models possible access under simple assumptions. Not for emergency dispatch, triage or hospital planning.
				{/if}
			</span>
		</div>
	</nav>

	<div class="main">
		<header class="bar">
			<div class="scn">
				{#if daily}
					{#if app.detail}
						<b>{app.detail.title}</b>
						<span class="tag">Daily model</span>
						{#if app.changeCount}<span class="muted">· your changes applied</span>{/if}
					{/if}
				{:else if rn.result}
					<b>{rn.datasetInfo?.title ?? rn.result.dataset}</b>
					<span class="tag mode" class:synthetic={rn.result.synthetic} title={rn.result.mode_label}>{rn.result.mode}</span>
					{#if rn.events.length}<span class="muted">· {rn.events.length} event{rn.events.length > 1 ? 's' : ''}</span>{/if}
					{#if rn.changeCount - rn.events.length > 0}<span class="muted">· settings changed</span>{/if}
				{/if}
			</div>
			<div class="status">
				{#if error && ready}
					<span class="err" title={error}>⚠ {error.slice(0, 90)}</span>
				{:else if loading}
					<span class="spin"></span><span class="muted">Updating…</span>
				{/if}
				<button class="btn" class:primary={!open} onclick={toggleControls}>
					<Icon name="sliders" size={14} /> {open ? 'Close' : 'What if…?'}
					{#if changes}<span class="badge">{changes}</span>{/if}
				</button>
			</div>
		</header>

		<main class="content">
			{#if error && !ready}
				<div class="boot">
					<h2>Can't reach the model API</h2>
					<p>Start it from the repository root, then reload this page:</p>
					<pre>pip install -r requirements.txt -r seir/requirements.txt -r frontend/api/requirements.txt
uvicorn main:app --app-dir frontend/api --port 8000</pre>
					<p class="muted">{error}</p>
				</div>
			{:else if !ready}
				<div class="boot"><span class="spin"></span> {daily ? 'Loading scenario…' : 'Running the weekly model…'}</div>
			{:else}
				{@render children()}
			{/if}
		</main>

		{#if daily && app.result}<Timeline />{:else if !daily && rn.result && page.url.pathname !== '/validation'}<WeekBar />{/if}
	</div>

	{#if open}
		<div class="drawer">{#if daily}<Controls />{:else}<RnControls />{/if}</div>
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
	.models {
		display: grid;
		grid-template-columns: 1fr 1fr;
		background: var(--bg);
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 2px;
		gap: 2px;
		margin: -8px 0 -10px;
	}
	.models a {
		text-align: center;
		font-size: 12px;
		color: var(--text-3);
		text-decoration: none;
		padding: 5px 6px;
		border-radius: 6px;
	}
	.models a:hover {
		color: var(--text-1);
	}
	.models a.on {
		background: var(--elev);
		color: var(--text-1);
		box-shadow: 0 0 0 1px var(--line-2);
	}
	.mode {
		color: var(--warning);
		border-color: rgb(250 178 25 / 0.4);
	}
	.mode.synthetic {
		color: #86b6ef;
		border-color: rgb(134 182 239 / 0.4);
	}
	.links {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.group {
		font-size: 11px;
		color: var(--text-3);
		padding: 14px 10px 6px;
	}
	.group:first-child {
		padding-top: 0;
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
		.group,
		.foot {
			display: none;
		}
		.models {
			grid-template-columns: 1fr;
			margin: 0;
		}
		.models a {
			font-size: 10px;
			padding: 4px 0;
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
