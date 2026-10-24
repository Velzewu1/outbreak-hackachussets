<script lang="ts">
	import { onMount } from 'svelte';
	import { Map as MLMap, Marker, setWorkerUrl, type GeoJSONSource } from "maplibre-gl";
	import type * as GeoJSON from "geojson";
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { app, type MapMetric } from '#lib/state.svelte.ts';
	import { heatColor, occupancyStatus, STATUS } from '#lib/colors.ts';
	import { num, pct } from '#lib/format.ts';

	setWorkerUrl(workerUrl);

	// CARTO watermarks tiles requested without a key; set VITE_CARTO_KEY in frontend/web/.env.
	const cartoKey: string | undefined = import.meta.env.VITE_CARTO_KEY;
	const basemapTiles = cartoKey
		? [`https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}@2x.png?key=${encodeURIComponent(cartoKey)}`]
		: ['a', 'b', 'c', 'd'].map((s) => `https://${s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png`);

	let el: HTMLDivElement;
	let map: MLMap | null = null;
	let ready = $state(false);
	let markers: { id: string; marker: Marker; el: HTMLElement }[] = [];
	let labels: Marker[] = [];
	let hoverPatch = $state<string | null>(null);

	const r = $derived(app.result!);
	const geo = $derived(r.geo);
	const t = $derived(Math.min(app.day, r.epi.dates.length - 1));

	const METRICS: { value: MapMetric; label: string; unit: string }[] = [
		{ value: 'prevalence', label: 'Infectious now', unit: '% of residents infectious' },
		{ value: 'attack_rate', label: 'Infected so far', unit: '% of residents ever infected' },
		{ value: 'inpatients', label: 'Hospitalised', unit: 'residents in hospital per 100k' },
		{ value: 'access_loss', label: 'Access lost', unit: '% of usual hospital care unavailable' }
	];

	function metricGrid(m: MapMetric): (number | null)[][] | null {
		const bp = r.epi.by_patch;
		if (m === 'prevalence') return bp.prevalence;
		if (m === 'attack_rate') return bp.attack_rate;
		if (m === 'inpatients' && bp.inpatients)
			return bp.inpatients.map((row) => row.map((v, p) => ((v ?? 0) / geo.patches[p].population) * 1e5));
		if (m === 'access_loss' && r.system) return r.system.access.map((row) => row.map((v) => 1 - (v ?? 1)));
		return null;
	}

	const grid = $derived(metricGrid(app.mapMetric) ?? metricGrid('prevalence')!);
	const gridMax = $derived(Math.max(1e-12, ...grid.flatMap((row) => row.map((v) => v ?? 0))));
	const fmt = (v: number) => (app.mapMetric === 'inpatients' ? num(v, 1) : pct(v, v < 0.1 ? 1 : 0));

	function patchFeatures() {
		return {
			type: 'FeatureCollection' as const,
			features: geo.patches.map((p, i) => {
				const v = grid[t]?.[i] ?? 0;
				return {
					type: 'Feature' as const,
					id: i,
					properties: {
						id: p.id,
						r: Math.sqrt(p.population) / 22,
						color: heatColor(0.08 + 0.92 * (v / gridMax)),
						sel: p.id === app.selectedPatch ? 1 : 0
					},
					geometry: { type: 'Point' as const, coordinates: [p.lon!, p.lat!] }
				};
			})
		};
	}

	function flowFeatures() {
		const sys = r.system;
		const feats: GeoJSON.Feature[] = [];
		if (!sys) return { type: 'FeatureCollection' as const, features: feats };
		const adm = r.epi.by_patch.new_hosp;
		geo.patches.forEach((p, i) => {
			geo.hospitals.forEach((h, j) => {
				const share = sys.shares[i]?.[j] ?? 0;
				const flow = (adm?.[t]?.[i] ?? 0) * share;
				if (share < 0.1 || h.lat === null) return;
				const focus = !app.selectedPatch || app.selectedPatch === p.id;
				feats.push({
					type: 'Feature',
					properties: { w: Math.min(8, 0.8 + flow * 1.1), o: focus ? 0.1 + share * 0.5 : 0.03 },
					geometry: {
						type: 'LineString',
						coordinates: [
							[p.lon!, p.lat!],
							[h.lon!, h.lat!]
						]
					}
				});
			});
		});
		return { type: 'FeatureCollection' as const, features: feats };
	}

	function hospitalState(j: number) {
		const sys = r.system!;
		const ward = sys.occupancy_ward[t]?.[j] ?? 0;
		const icu = sys.occupancy_icu[t]?.[j] ?? 0;
		const div = !!sys.on_diversion[t]?.[j];
		const occ = Math.max(ward, icu);
		return { ward, icu, div, occ, P: sys.operability[t]?.[j] ?? 100, status: occupancyStatus(occ, div) };
	}

	function buildMarkers() {
		markers.forEach((m) => m.marker.remove());
		labels.forEach((m) => m.remove());
		markers = [];
		labels = [];
		if (!map) return;
		const placed: { lat: number; lon: number }[] = [];
		for (const h of geo.hospitals) {
			if (h.lat === null) continue;
			// campuses a few hundred metres apart: put the second label on the other side
			const crowded = placed.some((q) => Math.abs(q.lat - h.lat!) < 0.006 && Math.abs(q.lon - h.lon!) < 0.008);
			placed.push({ lat: h.lat, lon: h.lon! });
			const e = document.createElement('button');
			e.className = crowded ? 'hm flip' : 'hm';
			e.onclick = (ev) => {
				ev.stopPropagation();
				app.selectedHospital = app.selectedHospital === h.id ? null : h.id;
			};
			const marker = new Marker({ element: e, anchor: crowded ? 'right' : 'left', offset: [crowded ? 6 : -6, 0] })
				.setLngLat([h.lon!, h.lat!])
				.addTo(map);
			markers.push({ id: h.id, marker, el: e });
		}
		for (const p of geo.patches) {
			const e = document.createElement('div');
			e.className = 'pl';
			e.textContent = p.id;
			labels.push(new Marker({ element: e, offset: [0, -18] }).setLngLat([p.lon!, p.lat!]).addTo(map));
		}
	}

	function paintMarkers() {
		if (!r.system) return;
		markers.forEach((m) => {
			const j = r.system!.hospitals.indexOf(m.id);
			const s = hospitalState(j);
			m.el.dataset.status = s.status;
			m.el.classList.toggle('div', s.div);
			m.el.classList.toggle('sel', app.selectedHospital === m.id);
			m.el.style.setProperty('--c', STATUS[s.status]);
			m.el.style.setProperty('--fill', `${Math.min(100, s.occ * 100)}%`);
			m.el.innerHTML = `<span class="ring"></span><span class="txt"><b>${m.id}</b><small>${Math.round(s.occ * 100)}%${s.div ? ' · div' : ''}</small></span>`;
			m.el.setAttribute('aria-label', `${m.id}: ${Math.round(s.occ * 100)}% occupied${s.div ? ', on diversion' : ''}`);
		});
	}

	function fit() {
		if (!map) return;
		const pts = [...geo.patches, ...geo.hospitals].filter((p) => p.lat !== null);
		if (!pts.length) return;
		const lons = pts.map((p) => p.lon!);
		const lats = pts.map((p) => p.lat!);
		map.fitBounds(
			[
				[Math.min(...lons), Math.min(...lats)],
				[Math.max(...lons), Math.max(...lats)]
			],
			{ padding: { top: 80, bottom: 80, left: 90, right: 150 }, duration: 0, maxZoom: 13 }
		);
	}

	onMount(() => {
		map = new MLMap({
			container: el,
			attributionControl: { compact: true },
			style: {
				version: 8,
				sources: {
					carto: {
						type: 'raster',
						tiles: basemapTiles,
						tileSize: 256,
						attribution: '© OpenStreetMap contributors © CARTO'
					}
				},
				layers: [
					{ id: 'bg', type: 'background', paint: { 'background-color': '#0e0e10' } },
					{ id: 'carto', type: 'raster', source: 'carto', paint: { 'raster-opacity': 0.9, 'raster-saturation': -0.4 } }
				]
			},
			center: [-71.085, 42.325],
			zoom: 11.4
		});
		map.on('load', () => {
			map!.addSource('flows', { type: 'geojson', data: flowFeatures() });
			map!.addSource('patches', { type: 'geojson', data: patchFeatures() });
			map!.addLayer({
				id: 'flows',
				type: 'line',
				source: 'flows',
				layout: { 'line-cap': 'round' },
				paint: { 'line-color': '#f0efec', 'line-width': ['get', 'w'], 'line-opacity': ['get', 'o'] }
			});
			map!.addLayer({
				id: 'halo',
				type: 'circle',
				source: 'patches',
				paint: {
					'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, ['*', ['get', 'r'], 0.8], 14, ['*', ['get', 'r'], 3]],
					'circle-color': ['get', 'color'],
					'circle-opacity': 0.16,
					'circle-blur': 0.6
				}
			});
			map!.addLayer({
				id: 'patches',
				type: 'circle',
				source: 'patches',
				paint: {
					'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, ['*', ['get', 'r'], 0.5], 14, ['*', ['get', 'r'], 1.9]],
					'circle-color': ['get', 'color'],
					'circle-opacity': 0.92,
					'circle-stroke-color': ['case', ['==', ['get', 'sel'], 1], '#f0efec', '#0e0e10'],
					'circle-stroke-width': ['case', ['==', ['get', 'sel'], 1], 2.5, 2]
				}
			});
			map!.on('mousemove', 'patches', (e) => {
				map!.getCanvas().style.cursor = 'pointer';
				hoverPatch = (e.features?.[0]?.properties?.id as string) ?? null;
			});
			map!.on('mouseleave', 'patches', () => {
				map!.getCanvas().style.cursor = '';
				hoverPatch = null;
			});
			map!.on('click', 'patches', (e) => {
				const id = e.features?.[0]?.properties?.id as string;
				app.selectedPatch = app.selectedPatch === id ? null : id;
			});
			buildMarkers();
			fit();
			ready = true;
		});
		return () => {
			markers.forEach((m) => m.marker.remove());
			map?.remove();
			map = null;
		};
	});

	// Rebuild markers and refit when the scenario's places change.
	let placesKey = '';
	$effect(() => {
		const key = geo.patches.map((p) => p.id).join() + '|' + geo.hospitals.map((h) => h.id).join();
		if (!ready || key === placesKey) return;
		placesKey = key;
		buildMarkers();
		fit();
	});

	// Repaint on every day, metric, selection or new run.
	$effect(() => {
		if (!ready || !map) return;
		void [t, app.mapMetric, app.selectedPatch, app.selectedHospital, r];
		(map.getSource('patches') as GeoJSONSource | undefined)?.setData(patchFeatures());
		(map.getSource('flows') as GeoJSONSource | undefined)?.setData(flowFeatures());
		paintMarkers();
	});

	const focusId = $derived(hoverPatch ?? app.selectedPatch);
	const focus = $derived.by(() => {
		const i = geo.patches.findIndex((p) => p.id === focusId);
		if (i < 0) return null;
		const p = geo.patches[i];
		const bp = r.epi.by_patch;
		const top = r.system
			? geo.hospitals
					.map((h, j) => ({ id: h.id, share: r.system!.shares[i][j], min: r.system!.travel[i][j] }))
					.sort((a, b) => b.share - a.share)
					.slice(0, 3)
			: [];
		return {
			p,
			prevalence: bp.prevalence[t]?.[i] ?? 0,
			attack: bp.attack_rate[t]?.[i] ?? 0,
			inpatients: bp.inpatients?.[t]?.[i] ?? null,
			access: r.system?.access[t]?.[i] ?? null,
			top
		};
	});
	const legendStops = [0, 0.25, 0.5, 0.75, 1];
</script>

<div class="wrap">
	<div class="map" bind:this={el}></div>

	<div class="overlay tl">
		<div class="seg">
			{#each METRICS as m (m.value)}
				{#if m.value !== 'access_loss' || r.system}
					<button class:on={app.mapMetric === m.value} onclick={() => (app.mapMetric = m.value)}>{m.label}</button>
				{/if}
			{/each}
		</div>
	</div>

	<div class="overlay br legend">
		<div class="lt">Neighborhoods · {METRICS.find((m) => m.value === app.mapMetric)?.unit}</div>
		<div class="ramp">
			{#each legendStops as s (s)}<i style:background={heatColor(0.08 + 0.92 * s)}></i>{/each}
		</div>
		<div class="ends"><span>0</span><span>{fmt(gridMax)}</span></div>
		{#if r.system}
			<div class="lt" style="margin-top:10px">Hospitals · bed occupancy</div>
			<div class="status">
				<span><i style:background={STATUS.good}></i>&lt;85%</span>
				<span><i style:background={STATUS.warning}></i>85–95%</span>
				<span><i style:background={STATUS.serious}></i>95–100%</span>
				<span><i style:background={STATUS.critical}></i>full / diverting</span>
			</div>
			<div class="lt" style="margin-top:6px">Lines: usual patient flows (width = admissions/day)</div>
		{/if}
	</div>

	{#if focus}
		<div class="overlay tr card">
			<div class="ct">{focus.p.id}</div>
			<div class="cs">{num(focus.p.population)} residents · vulnerability ×{focus.p.vulnerability.toFixed(1)}</div>
			<dl>
				<dt>Infectious now</dt><dd>{pct(focus.prevalence, 2)}</dd>
				<dt>Ever infected</dt><dd>{pct(focus.attack, 1)}</dd>
				{#if focus.inpatients !== null}<dt>In hospital</dt><dd>{num(focus.inpatients, 1)}</dd>{/if}
				{#if focus.access !== null}<dt>Access to usual care</dt><dd>{pct(focus.access, 0)}</dd>{/if}
			</dl>
			{#if focus.top.length}
				<div class="cs" style="margin-top:8px">Usual hospitals</div>
				{#each focus.top as h (h.id)}
					<div class="hrow"><span>{h.id}</span><span>{pct(h.share)} · {Math.round(h.min)} min</span></div>
				{/each}
			{/if}
		</div>
	{/if}
</div>

<style>
	.wrap {
		position: relative;
		width: 100%;
		height: 100%;
		min-height: 420px;
		background:
			radial-gradient(circle at 1px 1px, #1c1c20 1px, transparent 0) 0 0 / 22px 22px,
			#0e0e10;
	}
	.map {
		position: absolute;
		inset: 0;
	}
	.overlay {
		position: absolute;
		z-index: 2;
	}
	.tl {
		top: 14px;
		left: 14px;
	}
	.br {
		bottom: 34px;
		right: 14px;
	}
	.tr {
		top: 14px;
		right: 14px;
	}
	.seg {
		display: flex;
		background: rgb(20 20 22 / 0.88);
		backdrop-filter: blur(10px);
		border: 1px solid var(--line-2);
		border-radius: 10px;
		padding: 3px;
		gap: 2px;
	}
	.seg button {
		border: 0;
		background: transparent;
		color: var(--text-3);
		font-size: 12px;
		padding: 6px 10px;
		border-radius: 7px;
		cursor: pointer;
	}
	.seg button.on {
		background: var(--text-1);
		color: var(--bg);
		font-weight: 500;
	}
	.seg button:not(.on):hover {
		color: var(--text-1);
	}
	.legend,
	.card {
		background: rgb(20 20 22 / 0.88);
		backdrop-filter: blur(10px);
		border: 1px solid var(--line-2);
		border-radius: 12px;
		padding: 10px 12px;
		font-size: 11.5px;
		color: var(--text-2);
	}
	.legend {
		width: 268px;
	}
	.lt {
		color: var(--text-3);
		margin-bottom: 6px;
	}
	.ramp {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		height: 8px;
		border-radius: 4px;
		overflow: hidden;
	}
	.ends {
		display: flex;
		justify-content: space-between;
		color: var(--text-3);
		margin-top: 4px;
		font-family: var(--mono);
		font-size: 10.5px;
	}
	.status {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
	}
	.status i {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-right: 5px;
	}
	.card {
		width: 250px;
	}
	.ct {
		font-size: 14px;
		font-weight: 600;
		color: var(--text-1);
	}
	.cs {
		color: var(--text-3);
		margin-top: 2px;
	}
	dl {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 4px 12px;
		margin: 10px 0 0;
	}
	dt {
		color: var(--text-3);
	}
	dd {
		margin: 0;
		color: var(--text-1);
		font-family: var(--mono);
		text-align: right;
	}
	.hrow {
		display: flex;
		justify-content: space-between;
		font-family: var(--mono);
		font-size: 11px;
		color: var(--text-2);
		margin-top: 3px;
	}
	:global(.hm) {
		all: unset;
		cursor: pointer;
		display: flex;
		align-items: center;
		gap: 6px;
	}
	:global(.hm .ring) {
		width: 12px;
		height: 12px;
		border-radius: 3px;
		background: var(--c);
		box-shadow: 0 0 0 2px #0e0e10, 0 0 0 3px rgb(255 255 255 / 0.25);
	}
	:global(.hm.flip) {
		flex-direction: row-reverse;
	}
	:global(.hm.flip .txt) {
		align-items: flex-end;
	}
	:global(.hm.div .ring) {
		animation: alarm 1.2s ease-in-out infinite;
	}
	@keyframes alarm {
		50% {
			box-shadow: 0 0 0 2px #0e0e10, 0 0 0 7px rgb(208 59 59 / 0.55);
		}
	}
	:global(.hm .txt) {
		display: flex;
		flex-direction: column;
		line-height: 1.1;
		background: rgb(14 14 16 / 0.82);
		padding: 2px 6px;
		border-radius: 5px;
	}
	:global(.hm .txt b) {
		font-size: 11px;
		color: #f0efec;
		font-weight: 600;
	}
	:global(.hm .txt small) {
		font-size: 10px;
		color: #c3c2b7;
		font-family: var(--mono);
	}
	:global(.hm.sel .txt) {
		outline: 1px solid #f0efec;
	}
	:global(.pl) {
		font-size: 10.5px;
		color: rgb(240 239 236 / 0.75);
		text-shadow: 0 1px 2px #000, 0 0 6px #000;
		pointer-events: none;
		white-space: nowrap;
	}
	:global(.maplibregl-ctrl-attrib) {
		background: rgb(14 14 16 / 0.7) !important;
		color: var(--text-3);
	}
	:global(.maplibregl-ctrl-attrib a) {
		color: var(--text-3) !important;
	}
</style>
