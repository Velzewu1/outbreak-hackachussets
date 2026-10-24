<script lang="ts">
	import { onMount } from 'svelte';
	import { Map as MLMap, Marker, setWorkerUrl, type GeoJSONSource } from 'maplibre-gl';
	import type * as GeoJSON from 'geojson';
	import { scaleLinear } from 'd3-scale';
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { app, type MapMetric } from '#lib/state.svelte.ts';
	import { heatColor, occupancyStatus, STATUS, STATUS_LABEL } from '#lib/colors.ts';
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
	let hoverAt = $state<[number, number]>([0, 0]);

	const r = $derived(app.result!);
	const geo = $derived(r.geo);
	const t = $derived(Math.min(app.day, r.epi.dates.length - 1));

	const METRICS: { value: MapMetric; label: string; what: string }[] = [
		{ value: 'inpatients', label: 'In hospital', what: 'Residents in hospital, per 100,000 people' },
		{ value: 'prevalence', label: 'Sick now', what: 'Share of residents who are infectious on this day' },
		{ value: 'attack_rate', label: 'Infected so far', what: 'Share of residents infected since the start' },
		{ value: 'access_loss', label: 'Lost hospital access', what: 'Share of usual hospital care that is closed or full' }
	];
	const available = $derived(
		METRICS.filter((m) => (m.value === 'inpatients' ? !!r.epi.by_patch.inpatients : m.value === 'access_loss' ? !!r.system : true))
	);
	const metric = $derived(available.find((m) => m.value === app.mapMetric) ?? available[0]);
	const per100k = $derived(metric.value === 'inpatients');

	function metricGrid(m: MapMetric): (number | null)[][] | null {
		const bp = r.epi.by_patch;
		if (m === 'prevalence') return bp.prevalence;
		if (m === 'attack_rate') return bp.attack_rate;
		if (m === 'inpatients' && bp.inpatients)
			return bp.inpatients.map((row) => row.map((v, p) => ((v ?? 0) / geo.patches[p].population) * 1e5));
		if (m === 'access_loss' && r.system) return r.system.access.map((row) => row.map((v) => 1 - (v ?? 1)));
		return null;
	}

	const grid = $derived(metricGrid(metric.value) ?? metricGrid('prevalence')!);
	// One continuous scale for the whole run, so a colour means the same thing on every day
	// and small real differences between neighborhoods still show.
	const scale = $derived.by(() => {
		const hi = Math.max(...grid.flatMap((row) => row.map((v) => v ?? 0)));
		return scaleLinear()
			.domain([0, hi > 0 ? hi : per100k ? 10 : 0.01])
			.nice(4)
			.clamp(true);
	});
	const colorOf = (v: number) => heatColor(0.1 + 0.8 * scale(v));
	const ticks = $derived(scale.ticks(4));
	const gradient = $derived(
		`linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map((x) => heatColor(0.1 + 0.8 * x)).join(', ')})`
	);
	const fmtTick = (v: number) => (per100k ? num(v) : pct(v, (ticks[1] ?? 1) - (ticks[0] ?? 0) < 0.01 ? 1 : 0));
	const fmt = (v: number) => (per100k ? num(v) : pct(v, 1));
	// Where today's neighborhoods sit on the scale, so a city that looks one colour explains itself.
	const today = $derived.by(() => {
		const row = (grid[t] ?? []).map((v) => v ?? 0);
		if (!row.length) return null;
		const lo = Math.min(...row);
		const hi = Math.max(...row);
		return { lo, hi, a: scale(lo), b: scale(hi), close: hi - lo < 0.1 * (scale.domain()[1] - scale.domain()[0]) };
	});

	function districtFeatures() {
		const fc = geo.districts;
		if (!fc) return { type: 'FeatureCollection' as const, features: [] };
		return {
			type: 'FeatureCollection' as const,
			features: fc.features.map((f) => {
				const i = f.id as number;
				const p = geo.patches[i];
				return {
					...f,
					properties: {
						patch: p.id,
						color: colorOf(grid[t]?.[i] ?? 0),
						sel: p.id === app.selectedPatch ? 1 : 0,
						hover: p.id === hoverPatch ? 1 : 0
					}
				};
			})
		};
	}

	// Patient flows only for the selected neighborhood: where its people usually go.
	function flowFeatures() {
		const feats: GeoJSON.Feature[] = [];
		const sys = r.system;
		const i = geo.patches.findIndex((p) => p.id === app.selectedPatch);
		if (!sys || i < 0) return { type: 'FeatureCollection' as const, features: feats };
		const p = geo.patches[i];
		const from = p.label ?? [p.lon!, p.lat!];
		geo.hospitals.forEach((h, j) => {
			const share = sys.shares[i]?.[j] ?? 0;
			if (share < 0.05 || h.lat === null) return;
			feats.push({
				type: 'Feature',
				properties: { w: 1 + share * 7 },
				geometry: { type: 'LineString', coordinates: [from, [h.lon!, h.lat!]] }
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
		return { div, occ, status: occupancyStatus(occ, div) };
	}

	function buildMarkers() {
		markers.forEach((m) => m.marker.remove());
		labels.forEach((m) => m.remove());
		markers = [];
		labels = [];
		if (!map) return;
		for (const p of geo.patches) {
			const e = document.createElement('div');
			e.className = 'pl';
			e.textContent = p.id.replace('-', '–\n');
			labels.push(new Marker({ element: e }).setLngLat(p.label ?? [p.lon!, p.lat!]).addTo(map));
		}
		for (const h of geo.hospitals) {
			if (h.lat === null) continue;
			const e = document.createElement('button');
			e.className = 'hm';
			e.innerHTML = `<span class="sq"></span><span class="txt">${h.id}</span>`;
			e.onclick = (ev) => {
				ev.stopPropagation();
				app.selectedHospital = app.selectedHospital === h.id ? null : h.id;
			};
			const marker = new Marker({ element: e }).setLngLat([h.lon!, h.lat!]).addTo(map);
			markers.push({ id: h.id, marker, el: e });
		}
	}

	// Keep names readable: nudge a neighborhood name off any hospital square, then put
	// each hospital's name on the first side (right, left, above, below) that covers
	// nothing already placed. Redone after every zoom.
	type Box = [number, number, number, number];
	const overlap = (a: Box, b: Box) =>
		Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
	// The candidate covering the least of what is already placed; ties go to the earlier one.
	function best<T>(cands: T[], box: (c: T) => Box, taken: Box[]): T {
		let pick = cands[0];
		let least = Infinity;
		for (const c of cands) {
			const b = box(c);
			const area = taken.reduce((a, o) => a + overlap(o, b), 0);
			if (area < least) [pick, least] = [c, area];
			if (area === 0) break;
		}
		return pick;
	}
	function placeNames() {
		if (!map) return;
		const squares: Box[] = markers.map((m) => {
			const c = map!.project(m.marker.getLngLat());
			return [c.x - 8, c.y - 8, c.x + 8, c.y + 8];
		});
		const taken: Box[] = [...squares];
		for (const l of labels) {
			const c = map!.project(l.getLngLat());
			const w = l.getElement().offsetWidth / 2 + 2;
			const h = l.getElement().offsetHeight / 2 + 1;
			// nearby spots, closest first
			const shifts: [number, number][] = [];
			for (const dx of [0, -0.5, 0.5, -1, 1, -1.5, 1.5]) for (const dy of [0, -1, 1]) shifts.push([dx * w, dy * (2 * h + 4)]);
			shifts.sort((p, q) => Math.hypot(...p) - Math.hypot(...q));
			const at = ([dx, dy]: [number, number]): Box => [c.x + dx - w, c.y + dy - h, c.x + dx + w, c.y + dy + h];
			const shift = best(shifts, at, taken);
			l.setOffset(shift);
			taken.push(at(shift));
		}
		markers.forEach((m, i) => {
			const c = map!.project(m.marker.getLngLat());
			const txt = m.el.querySelector('.txt') as HTMLElement;
			const w = txt.offsetWidth;
			const h = txt.offsetHeight;
			const sides: [string, Box][] = [
				['right', [c.x + 9, c.y - h / 2, c.x + 9 + w, c.y + h / 2]],
				['left', [c.x - 9 - w, c.y - h / 2, c.x - 9, c.y + h / 2]],
				['top', [c.x - w / 2, c.y - 9 - h, c.x + w / 2, c.y - 9]],
				['bottom', [c.x - w / 2, c.y + 9, c.x + w / 2, c.y + 9 + h]]
			];
			const [side, box] = best(sides, ([, b]) => b, taken.filter((b) => b !== squares[i]));
			m.el.dataset.side = side;
			taken.push(box);
		});
	}

	function paintMarkers() {
		if (!r.system) return;
		markers.forEach((m) => {
			const j = r.system!.hospitals.indexOf(m.id);
			const s = hospitalState(j);
			const name = geo.hospitals[j]?.name ?? m.id;
			m.el.classList.toggle('div', s.div);
			m.el.classList.toggle('sel', app.selectedHospital === m.id);
			m.el.style.setProperty('--c', STATUS[s.status]);
			m.el.title = `${name}: ${Math.round(s.occ * 100)}% of beds in use. ${STATUS_LABEL[s.status]}.`;
		});
	}

	function fit() {
		if (!map) return;
		const pts: number[][] = [];
		for (const f of geo.districts?.features ?? []) {
			const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
			for (const poly of polys) pts.push(...poly[0]);
		}
		for (const p of [...geo.patches, ...geo.hospitals]) if (p.lat !== null) pts.push([p.lon!, p.lat!]);
		if (!pts.length) return;
		const lons = pts.map((p) => p[0]);
		const lats = pts.map((p) => p[1]);
		map.fitBounds(
			[
				[Math.min(...lons), Math.min(...lats)],
				[Math.max(...lons), Math.max(...lats)]
			],
			{ padding: { top: 96, bottom: 24, left: 24, right: 24 }, duration: 0, maxZoom: 13 }
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
						attribution: '© OpenStreetMap contributors © CARTO · Boundaries: City of Boston'
					}
				},
				layers: [
					{ id: 'bg', type: 'background', paint: { 'background-color': '#0e0e10' } },
					{ id: 'carto', type: 'raster', source: 'carto', paint: { 'raster-opacity': 0.75, 'raster-saturation': -0.6 } }
				]
			},
			center: [-71.085, 42.325],
			zoom: 11.4
		});
		map.on('load', () => {
			map!.addSource('districts', { type: 'geojson', data: districtFeatures() });
			map!.addSource('flows', { type: 'geojson', data: flowFeatures() });
			map!.addLayer({
				id: 'district-fill',
				type: 'fill',
				source: 'districts',
				paint: { 'fill-color': ['get', 'color'], 'fill-opacity': ['case', ['==', ['get', 'hover'], 1], 0.92, 0.78] }
			});
			map!.addLayer({
				id: 'district-line',
				type: 'line',
				source: 'districts',
				paint: { 'line-color': '#0b0b0c', 'line-width': 1.2 }
			});
			map!.addLayer({
				id: 'district-sel',
				type: 'line',
				source: 'districts',
				filter: ['==', ['get', 'sel'], 1],
				paint: { 'line-color': '#f0efec', 'line-width': 2.5 }
			});
			map!.addLayer({
				id: 'flows',
				type: 'line',
				source: 'flows',
				layout: { 'line-cap': 'round' },
				paint: { 'line-color': '#f0efec', 'line-width': ['get', 'w'], 'line-opacity': 0.85 }
			});
			map!.on('mousemove', 'district-fill', (e) => {
				map!.getCanvas().style.cursor = 'pointer';
				hoverPatch = (e.features?.[0]?.properties?.patch as string) ?? null;
				hoverAt = [e.point.x, e.point.y];
			});
			map!.on('mouseleave', 'district-fill', () => {
				map!.getCanvas().style.cursor = '';
				hoverPatch = null;
			});
			map!.on('click', (e) => {
				const f = map!.queryRenderedFeatures(e.point, { layers: ['district-fill'] })[0];
				const id = (f?.properties?.patch as string | undefined) ?? null;
				app.selectedPatch = id && app.selectedPatch !== id ? id : null;
			});
			buildMarkers();
			fit();
			placeNames();
			map!.on('zoomend', placeNames);
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
		placeNames();
	});

	// Repaint on every day, metric, selection, hover or new run.
	$effect(() => {
		if (!ready || !map) return;
		void [t, scale, app.selectedPatch, app.selectedHospital, hoverPatch, r];
		(map.getSource('districts') as GeoJSONSource | undefined)?.setData(districtFeatures());
		(map.getSource('flows') as GeoJSONSource | undefined)?.setData(flowFeatures());
		paintMarkers();
	});

	const tip = $derived.by(() => {
		const i = geo.patches.findIndex((p) => p.id === hoverPatch);
		return i < 0 ? null : { id: geo.patches[i].id, value: grid[t]?.[i] ?? 0 };
	});
</script>

<div class="wrap">
	<div class="map" bind:this={el}></div>

	<div class="overlay tl">
		<div class="seg" role="tablist" aria-label="Colour neighborhoods by">
			{#each available as m (m.value)}
				<button role="tab" aria-selected={metric.value === m.value} class:on={metric.value === m.value} onclick={() => (app.mapMetric = m.value)}>{m.label}</button>
			{/each}
		</div>
		<p class="hint">Click a neighborhood to see where its patients go. Press play below to watch the wave.</p>
	</div>

	<div class="overlay br legend">
		<div class="lt">{metric.what}</div>
		<div class="bar" style:background={gradient}>
			{#if today}<span class="range" style:left="{today.a * 100}%" style:width="max(3px, {(today.b - today.a) * 100}%)"></span>{/if}
		</div>
		<div class="ticks">
			{#each ticks as v (v)}<span>{fmtTick(v)}</span>{/each}
		</div>
		{#if today}
			<div class="today">
				{#if today.close}
					Today all neighborhoods are close: {fmt(today.lo)} to {fmt(today.hi)}, marked by the white box.
				{:else}
					Today's neighborhoods run from {fmt(today.lo)} to {fmt(today.hi)}, marked by the white box.
				{/if}
			</div>
		{/if}
		{#if r.system}
			<div class="lt hosp">Hospital squares: how full their beds are</div>
			<div class="status">
				<span><i style:background={STATUS.good}></i>Normal</span>
				<span><i style:background={STATUS.warning}></i>85%+</span>
				<span><i style:background={STATUS.serious}></i>95%+</span>
				<span><i style:background={STATUS.critical}></i>Full</span>
			</div>
		{/if}
	</div>

	{#if tip}
		<div class="tip" style:left="{hoverAt[0] + 14}px" style:top="{hoverAt[1] + 14}px">
			<b>{tip.id}</b>
			<span>{metric.label}: {per100k ? `${num(tip.value)} per 100k` : pct(tip.value, 1)}</span>
		</div>
	{/if}
</div>

<style>
	.wrap {
		position: relative;
		width: 100%;
		height: 100%;
		min-height: 420px;
		background: #0e0e10;
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
		right: 14px;
	}
	.br {
		bottom: 30px;
		right: 14px;
	}
	.seg {
		display: inline-flex;
		flex-wrap: wrap;
		background: rgb(20 20 22 / 0.9);
		backdrop-filter: blur(10px);
		border: 1px solid var(--line-2);
		border-radius: 10px;
		padding: 3px;
		gap: 2px;
	}
	.seg button {
		border: 0;
		background: transparent;
		color: var(--text-2);
		font-size: 12.5px;
		padding: 7px 12px;
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
	.hint {
		margin: 8px 0 0 4px;
		font-size: 12px;
		color: var(--text-2);
		text-shadow: 0 1px 3px #000;
	}
	.legend {
		background: rgb(20 20 22 / 0.9);
		backdrop-filter: blur(10px);
		border: 1px solid var(--line-2);
		border-radius: 12px;
		padding: 12px 14px;
		font-size: 12px;
		color: var(--text-2);
		width: 268px;
	}
	.lt {
		color: var(--text-2);
		margin-bottom: 8px;
		line-height: 1.4;
	}
	.lt.hosp {
		margin: 12px 0 6px;
	}
	.bar {
		position: relative;
		height: 12px;
		border-radius: 3px;
	}
	.range {
		position: absolute;
		top: -3px;
		bottom: -3px;
		border: 1.5px solid #fff;
		border-radius: 3px;
		transform: translateX(-1.5px);
		box-sizing: content-box;
		transition:
			left 0.2s,
			width 0.2s;
	}
	.today {
		margin-top: 8px;
		font-size: 11.5px;
		line-height: 1.4;
		color: var(--text-3);
	}
	.ticks {
		display: flex;
		justify-content: space-between;
		margin-top: 4px;
		font-family: var(--mono);
		font-size: 10.5px;
		color: var(--text-3);
	}
	.status {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
	}
	.status i {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 3px;
		margin-right: 6px;
		vertical-align: -1px;
	}
	.tip {
		position: absolute;
		z-index: 3;
		pointer-events: none;
		background: rgb(20 20 22 / 0.95);
		border: 1px solid var(--line-2);
		border-radius: 8px;
		padding: 6px 9px;
		font-size: 12px;
		display: flex;
		flex-direction: column;
		gap: 2px;
		white-space: nowrap;
	}
	.tip span {
		color: var(--text-2);
	}
	/* A MapLibre marker: keep its absolute positioning, only drop the button chrome. */
	:global(.hm) {
		cursor: pointer;
		width: 11px;
		height: 11px;
		padding: 0;
		border: 0;
		background: none;
	}
	:global(.hm .sq) {
		position: absolute;
		inset: 0;
		border-radius: 3px;
		background: var(--c);
		box-shadow: 0 0 0 2px #0b0b0c;
	}
	:global(.hm.div .sq) {
		animation: alarm 1.2s ease-in-out infinite;
	}
	@keyframes alarm {
		50% {
			box-shadow: 0 0 0 2px #0b0b0c, 0 0 0 7px rgb(208 59 59 / 0.55);
		}
	}
	:global(.hm .txt) {
		position: absolute;
		top: 50%;
		left: calc(100% + 4px);
		transform: translateY(-50%);
		font-size: 11px;
		font-weight: 600;
		line-height: 16px;
		color: #f0efec;
		background: rgb(11 11 12 / 0.85);
		padding: 0 5px;
		border-radius: 4px;
		white-space: nowrap;
	}
	:global(.hm[data-side='left'] .txt) {
		left: auto;
		right: calc(100% + 4px);
	}
	:global(.hm[data-side='top'] .txt) {
		top: auto;
		bottom: calc(100% + 4px);
		left: 50%;
		transform: translateX(-50%);
	}
	:global(.hm[data-side='bottom'] .txt) {
		top: calc(100% + 4px);
		left: 50%;
		transform: translateX(-50%);
	}
	:global(.hm.div .txt) {
		color: #ff8a8a;
	}
	:global(.hm.sel .txt) {
		outline: 1.5px solid #f0efec;
	}
	:global(.pl) {
		font-size: 11px;
		line-height: 1.15;
		font-weight: 500;
		color: rgb(255 255 255 / 0.92);
		text-shadow: 0 0 3px #000, 0 1px 2px #000, 0 0 8px rgb(0 0 0 / 0.8);
		pointer-events: none;
		white-space: pre;
		text-align: center;
	}
	:global(.maplibregl-ctrl-attrib) {
		background: rgb(14 14 16 / 0.7) !important;
		color: var(--text-3);
	}
	:global(.maplibregl-ctrl-attrib a) {
		color: var(--text-3) !important;
	}
	@media (max-width: 900px) {
		.hint {
			display: none;
		}
	}
</style>
