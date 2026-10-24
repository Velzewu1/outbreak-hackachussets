<script lang="ts">
	import { onMount } from 'svelte';
	import { Map as MLMap, Marker, setWorkerUrl, type GeoJSONSource } from 'maplibre-gl';
	import type * as GeoJSON from 'geojson';
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { rn, scoreColor, tractLabel, weekLabel } from '#lib/rn.svelte.ts';
	import type { RnGeo } from '#lib/rn-api.ts';
	import { num, fixed } from '#lib/format.ts';

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
	let hoverDistrict = $state<number | null>(null);
	let hoverHospital = $state<string | null>(null);
	let hoverAt = $state<[number, number]>([0, 0]);
	let mapW = $state(800);
	let mapH = $state(600);

	const r = $derived(rn.result!);
	const v = $derived(rn.view!);
	const geo = $derived(rn.geo[r.dataset] ?? null);
	const threshold = $derived(r.threshold);

	// A colour ramp MapLibre can draw from feature-state, sampled from the same scale as the legend.
	const SCORE_STOPS = Array.from({ length: 11 }, (_, i) => i * 10);
	const fillColor = ['interpolate', ['linear'], ['coalesce', ['feature-state', 'score'], 100], ...SCORE_STOPS.flatMap((s) => [s, scoreColor(s)])];
	const gradient = `linear-gradient(to right, ${SCORE_STOPS.map((s) => scoreColor(s)).join(', ')})`;

	const range = $derived.by(() => {
		const a = v.access.filter((x) => x !== null);
		return a.length ? { lo: Math.min(...a), hi: Math.max(...a) } : null;
	});
	const ejKnown = $derived(r.districts.some((d) => d.ej !== null));
	const maxBeds = $derived(Math.max(1, ...r.hospitals.map((h) => h.beds)));
	const sizeOf = (beds: number) => Math.round(10 + 18 * Math.sqrt(beds / maxBeds));

	function catchmentLines() {
		const feats: GeoJSON.Feature[] = [];
		const d = r.districts[rn.districtIndex(rn.selectedDistrict)];
		if (d) {
			for (const c of d.catchment) {
				const h = r.hospitals.find((x) => x.id === c.id);
				if (!h) continue;
				feats.push({
					type: 'Feature',
					properties: { w: 1 + c.share * 7 },
					geometry: { type: 'LineString', coordinates: [[d.lon, d.lat], [h.lon, h.lat]] }
				});
			}
		}
		return { type: 'FeatureCollection' as const, features: feats };
	}

	function paint() {
		if (!map || !geo) return;
		const sel = rn.districtIndex(rn.selectedDistrict);
		geo.features.forEach((f, i) => {
			map!.setFeatureState(
				{ source: 'districts', id: f.id as number },
				{
					score: v.access[i] ?? 100,
					sel: i === sel,
					hover: i === hoverDistrict,
					ej: rn.ejOverlay && r.districts[i]?.ej === true
				}
			);
		});
		(map.getSource('flows') as GeoJSONSource | undefined)?.setData(catchmentLines());
		for (const m of markers) {
			const h = v.hospitals.find((x) => x.id === m.id);
			m.el.style.setProperty('--c', scoreColor(h?.score));
			m.el.classList.toggle('closed', !!h?.closed);
			m.el.classList.toggle('sel', rn.selectedHospital === m.id);
			m.el.classList.toggle('over', !!h && h.load > h.capacity + 1e-6);
		}
	}

	function buildMarkers() {
		markers.forEach((m) => m.marker.remove());
		markers = [];
		if (!map) return;
		for (const h of r.hospitals) {
			const e = document.createElement('button');
			e.className = 'rh';
			const d = sizeOf(h.beds);
			e.style.width = e.style.height = `${d}px`;
			e.innerHTML = `<span class="dot"></span><span class="txt">${rn.hospitalName(h.id)}</span>`;
			e.setAttribute('aria-label', h.name);
			e.onclick = (ev) => {
				ev.stopPropagation();
				rn.selectedHospital = rn.selectedHospital === h.id ? null : h.id;
			};
			e.onmouseenter = () => {
				hoverHospital = h.id;
				const p = map!.project([h.lon, h.lat]);
				hoverAt = [p.x, p.y];
			};
			e.onmouseleave = () => (hoverHospital = null);
			const marker = new Marker({ element: e }).setLngLat([h.lon, h.lat]).addTo(map);
			markers.push({ id: h.id, marker, el: e });
		}
		placeNames();
	}

	// Put each hospital's name on the first side (right, left, above, below) that covers
	// no other circle or name. Redone after every zoom.
	type Box = [number, number, number, number];
	const overlap = (a: Box, b: Box) =>
		Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
	function placeNames() {
		if (!map) return;
		const circles: Box[] = markers.map((m) => {
			const c = map!.project(m.marker.getLngLat());
			const r2 = m.el.offsetWidth / 2;
			return [c.x - r2, c.y - r2, c.x + r2, c.y + r2];
		});
		const taken: Box[] = [...circles];
		markers.forEach((m, i) => {
			const c = map!.project(m.marker.getLngLat());
			const txt = m.el.querySelector('.txt') as HTMLElement;
			const w = txt.offsetWidth;
			const h = txt.offsetHeight;
			const g = m.el.offsetWidth / 2 + 4;
			const sides: [string, Box][] = [
				['right', [c.x + g, c.y - h / 2, c.x + g + w, c.y + h / 2]],
				['left', [c.x - g - w, c.y - h / 2, c.x - g, c.y + h / 2]],
				['top', [c.x - w / 2, c.y - g - h, c.x + w / 2, c.y - g]],
				['bottom', [c.x - w / 2, c.y + g, c.x + w / 2, c.y + g + h]]
			];
			let pick = sides[0];
			let least = Infinity;
			for (const s of sides) {
				const area = taken.filter((b) => b !== circles[i]).reduce((a, o) => a + overlap(o, s[1]), 0);
				if (area < least) [pick, least] = [s, area];
				if (area === 0) break;
			}
			m.el.dataset.side = pick[0];
			taken.push(pick[1]);
		});
	}

	function fit() {
		if (!map || !geo) return;
		let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
		const add = (p: number[]) => {
			x0 = Math.min(x0, p[0]);
			x1 = Math.max(x1, p[0]);
			y0 = Math.min(y0, p[1]);
			y1 = Math.max(y1, p[1]);
		};
		for (const f of geo.features) {
			const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
			for (const poly of polys) poly[0].forEach(add);
		}
		r.hospitals.forEach((h) => add([h.lon, h.lat]));
		if (!Number.isFinite(x0)) return;
		map.fitBounds(
			[
				[x0, y0],
				[x1, y1]
			],
			{ padding: { top: 70, bottom: 30, left: 30, right: 30 }, duration: 0, maxZoom: 13.5 }
		);
	}

	function setGeo(g: RnGeo) {
		const src = map?.getSource('districts') as GeoJSONSource | undefined;
		src?.setData(g);
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
					{ id: 'carto', type: 'raster', source: 'carto', paint: { 'raster-opacity': 0.75, 'raster-saturation': -0.6 } }
				]
			},
			center: [-71.06, 42.33],
			zoom: 11
		});
		map.on('load', () => {
			map!.addSource('districts', { type: 'geojson', data: geo ?? { type: 'FeatureCollection', features: [] } });
			map!.addSource('flows', { type: 'geojson', data: catchmentLines() });
			map!.addLayer({
				id: 'district-fill',
				type: 'fill',
				source: 'districts',
				paint: {
					// eslint-disable-next-line @typescript-eslint/no-explicit-any
					'fill-color': fillColor as any,
					// tracts near 100 stay see-through so the streets show; low scores are solid
					'fill-opacity': [
						'case',
						['boolean', ['feature-state', 'hover'], false],
						0.95,
						['interpolate', ['linear'], ['coalesce', ['feature-state', 'score'], 100], 40, 0.88, 100, 0.5]
					]
				}
			});
			map!.addLayer({
				id: 'district-line',
				type: 'line',
				source: 'districts',
				paint: { 'line-color': '#0b0b0c', 'line-width': 0.6, 'line-opacity': 0.9 }
			});
			map!.addLayer({
				id: 'district-ej',
				type: 'line',
				source: 'districts',
				paint: {
					'line-color': '#86b6ef',
					'line-width': 2,
					'line-dasharray': [2, 1.5],
					'line-opacity': ['case', ['boolean', ['feature-state', 'ej'], false], 1, 0]
				}
			});
			map!.addLayer({
				id: 'district-sel',
				type: 'line',
				source: 'districts',
				paint: {
					'line-color': '#f0efec',
					'line-width': ['case', ['boolean', ['feature-state', 'sel'], false], 2.5, 0]
				}
			});
			map!.addLayer({
				id: 'flows',
				type: 'line',
				source: 'flows',
				layout: { 'line-cap': 'round' },
				paint: { 'line-color': '#f0efec', 'line-width': ['get', 'w'], 'line-opacity': 0.8 }
			});
			map!.on('mousemove', 'district-fill', (e) => {
				map!.getCanvas().style.cursor = 'pointer';
				const id = e.features?.[0]?.id;
				hoverDistrict = typeof id === 'number' ? id : null;
				hoverAt = [e.point.x, e.point.y];
			});
			map!.on('mouseleave', 'district-fill', () => {
				map!.getCanvas().style.cursor = '';
				hoverDistrict = null;
			});
			map!.on('click', (e) => {
				const f = map!.queryRenderedFeatures(e.point, { layers: ['district-fill'] })[0];
				const d = typeof f?.id === 'number' ? r.districts[f.id] : null;
				rn.selectedDistrict = d && rn.selectedDistrict !== d.id ? d.id : null;
			});
			map!.on('zoomend', placeNames);
			ready = true;
		});
		return () => {
			markers.forEach((m) => m.marker.remove());
			map?.remove();
			map = null;
		};
	});

	// New dataset: new outlines, markers and view.
	let shownKey = '';
	$effect(() => {
		const key = `${r.dataset}|${geo ? geo.features.length : 0}|${r.hospitals.map((h) => h.id).join()}`;
		if (!ready || !geo || key === shownKey) return;
		shownKey = key;
		setGeo(geo);
		buildMarkers();
		fit();
		paint();
	});

	// Repaint on every week, phase, selection, hover or new run.
	$effect(() => {
		if (!ready) return;
		void [v, rn.selectedDistrict, rn.selectedHospital, hoverDistrict, rn.ejOverlay, geo];
		paint();
	});

	const tip = $derived.by(() => {
		if (hoverDistrict === null) return null;
		const d = r.districts[hoverDistrict];
		if (!d) return null;
		return {
			d,
			score: v.access[hoverDistrict],
			need: v.need[hoverDistrict],
			unmet: v.unmet[hoverDistrict],
			fallback: r.fallback_districts.includes(d.id)
		};
	});
	const htip = $derived.by(() => {
		if (!hoverHospital) return null;
		const h = r.hospitals.find((x) => x.id === hoverHospital);
		const w = v.hospitals.find((x) => x.id === hoverHospital);
		return h && w ? { h, w } : null;
	});
</script>

<div class="wrap" bind:clientWidth={mapW} bind:clientHeight={mapH}>
	<div class="map" bind:this={el}></div>

	<div class="overlay tl">
		<div class="chip">
			<b>Access to hospital care</b>
			<span>{weekLabel(rn.week)} · {rn.phase === 'after' ? 'after rerouting' : 'before rerouting'}</span>
		</div>
		<p class="hint">Hover a tract for its numbers. Click one to see which hospitals it relies on.</p>
	</div>

	<div class="overlay br legend">
		<div class="lt">Access score of each census tract, 0 to 100. The scale is the same every week.</div>
		<div class="bar" style:background={gradient}>
			{#if range}
				<span class="range" style:left="{range.lo}%" style:width="max(3px, {range.hi - range.lo}%)"></span>
			{/if}
			<span class="thr" style:left="{threshold}%"></span>
		</div>
		<div class="ticks">
			{#each [0, 25, 50, threshold, 100] as t (t)}
				<span class:thrl={t === threshold} style:left="{t}%" style:transform="translateX({t === 0 ? 0 : t === 100 ? -100 : -50}%)">{t}</span>
			{/each}
		</div>
		{#if range}
			<div class="today">
				This week's tracts run from {fixed(range.lo, 0)} to {fixed(range.hi, 0)} (white box). Below {threshold} counts as poor access.
			</div>
		{/if}
		<div class="lt hosp">Circles are hospitals: size is beds, colour is the hospital's score on the same scale.</div>
		<label class="ej" class:off={!ejKnown} title={ejKnown ? '' : 'This dataset has no environmental-justice flags, so the outline is off. Scores are unaffected.'}>
			<input type="checkbox" bind:checked={rn.ejOverlay} disabled={!ejKnown} />
			<span>Outline environmental-justice tracts{#if !ejKnown}<em>&nbsp;(no data here)</em>{/if}</span>
		</label>
	</div>

	{#if tip}
		<div class="tip" class:flipx={hoverAt[0] > mapW * 0.55} class:flipy={hoverAt[1] > mapH * 0.6} style:left="{hoverAt[0]}px" style:top="{hoverAt[1]}px">
			<b>{tractLabel(tip.d)}</b>
			<span>Access score <em>{fixed(tip.score, 1)}</em></span>
			<span>Need a bed <em>{fixed(tip.need, 1)} people/week</em></span>
			<span>Can't get one <em>{fixed(tip.unmet, 1)} people/week</em></span>
			<span>Residents <em>{num(tip.d.population)}</em></span>
			<span>Environmental justice <em>{tip.d.ej === null ? 'unknown' : tip.d.ej ? 'yes' : 'no'}</em></span>
			{#if tip.fallback}<span class="warn">No hospital within {rn.meta?.radius_km ?? 10} km: assigned its nearest one</span>{/if}
		</div>
	{/if}
	{#if htip}
		<div class="tip" class:flipx={hoverAt[0] > mapW * 0.55} class:flipy={hoverAt[1] > mapH * 0.6} style:left="{hoverAt[0]}px" style:top="{hoverAt[1]}px">
			<b>{htip.h.name}</b>
			{#if htip.w.closed}<span class="warn">Closed this week</span>{/if}
			<span>Score <em>{fixed(htip.w.score, 1)}</em> (own {fixed(htip.w.own, 1)})</span>
			<span>Patients wanting a bed <em>{num(htip.w.load)}</em></span>
			<span>Beds available <em>{num(htip.w.capacity)}</em></span>
			{#if htip.w.excess > 0}<span class="warn">{num(htip.w.excess)} more than it has</span>{/if}
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
		pointer-events: none;
	}
	.br {
		bottom: 30px;
		right: 14px;
	}
	.chip {
		display: inline-flex;
		align-items: baseline;
		gap: 10px;
		background: rgb(20 20 22 / 0.9);
		backdrop-filter: blur(10px);
		border: 1px solid var(--line-2);
		border-radius: 10px;
		padding: 8px 12px;
		font-size: 12.5px;
	}
	.chip span {
		color: var(--text-3);
	}
	.hint {
		margin: 8px 0 0 4px;
		font-size: 12px;
		color: var(--text-2);
		text-shadow: 0 1px 3px #000;
	}
	.legend {
		background: rgb(20 20 22 / 0.92);
		backdrop-filter: blur(10px);
		border: 1px solid var(--line-2);
		border-radius: 12px;
		padding: 12px 14px;
		font-size: 12px;
		color: var(--text-2);
		width: 280px;
	}
	.lt {
		margin-bottom: 8px;
		line-height: 1.4;
	}
	.lt.hosp {
		margin: 12px 0 8px;
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
	.thr {
		position: absolute;
		top: -5px;
		bottom: -5px;
		width: 0;
		border-left: 1.5px dashed var(--text-2);
	}
	.ticks {
		position: relative;
		margin-top: 4px;
		font-family: var(--mono);
		font-size: 10.5px;
		color: var(--text-3);
		height: 14px;
	}
	.ticks span {
		position: absolute;
	}
	.ticks .thrl {
		color: var(--text-2);
	}
	.today {
		margin-top: 6px;
		font-size: 11.5px;
		line-height: 1.4;
		color: var(--text-3);
	}
	.ej {
		display: flex;
		gap: 8px;
		align-items: center;
		font-size: 12px;
		cursor: pointer;
	}
	.ej.off {
		color: var(--text-3);
		cursor: default;
	}
	.ej em {
		font-style: normal;
		color: var(--text-3);
	}
	.ej input {
		accent-color: var(--accent);
		margin: 0;
	}
	.tip {
		position: absolute;
		z-index: 3;
		pointer-events: none;
		background: rgb(20 20 22 / 0.96);
		border: 1px solid var(--line-2);
		border-radius: 8px;
		padding: 8px 10px;
		font-size: 12px;
		display: flex;
		flex-direction: column;
		gap: 3px;
		white-space: nowrap;
		min-width: 210px;
		transform: translate(16px, 16px);
	}
	.tip.flipx {
		transform: translate(calc(-100% - 16px), 16px);
	}
	.tip.flipy {
		transform: translate(16px, calc(-100% - 16px));
	}
	.tip.flipx.flipy {
		transform: translate(calc(-100% - 16px), calc(-100% - 16px));
	}
	.tip span {
		color: var(--text-3);
		display: flex;
		justify-content: space-between;
		gap: 14px;
	}
	.tip em {
		font-style: normal;
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
	.tip .warn {
		color: #ffb199;
	}
	/* A MapLibre marker: keep its absolute positioning, only drop the button chrome. */
	:global(.rh) {
		cursor: pointer;
		padding: 0;
		border: 0;
		background: none;
	}
	:global(.rh .dot) {
		position: absolute;
		inset: 0;
		border-radius: 50%;
		background: var(--c);
		box-shadow:
			0 0 0 1.5px rgb(240 239 236 / 0.85),
			0 0 0 3px #0b0b0c;
	}
	:global(.rh.over .dot) {
		box-shadow:
			0 0 0 1.5px #ff8a8a,
			0 0 0 3px #0b0b0c,
			0 0 0 7px rgb(208 59 59 / 0.35);
	}
	:global(.rh.closed .dot) {
		background: repeating-linear-gradient(45deg, #d03b3b 0 2px, transparent 2px 5px), #0b0b0c;
		box-shadow:
			0 0 0 1.5px #d03b3b,
			0 0 0 3px #0b0b0c;
	}
	:global(.rh.sel .dot) {
		box-shadow:
			0 0 0 2.5px #fff,
			0 0 0 4px #0b0b0c;
	}
	:global(.rh .txt) {
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
		pointer-events: none;
	}
	:global(.rh[data-side='left'] .txt) {
		left: auto;
		right: calc(100% + 4px);
	}
	:global(.rh[data-side='top'] .txt) {
		top: auto;
		bottom: calc(100% + 4px);
		left: 50%;
		transform: translateX(-50%);
	}
	:global(.rh[data-side='bottom'] .txt) {
		top: calc(100% + 4px);
		left: 50%;
		transform: translateX(-50%);
	}
	:global(.rh.closed .txt) {
		color: #ff8a8a;
		text-decoration: line-through;
	}
	:global(.rh.sel .txt) {
		outline: 1.5px solid #f0efec;
	}
	@media (max-width: 900px) {
		.hint {
			display: none;
		}
		.legend {
			width: 230px;
		}
	}
	@media (max-width: 700px) {
		.legend {
			width: 200px;
			padding: 10px 12px;
		}
		.today,
		.lt.hosp,
		.ej {
			display: none;
		}
	}
</style>
