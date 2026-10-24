<script lang="ts">
	import { rn } from '#lib/rn.svelte.ts';
	import { fixed, num, pct } from '#lib/format.ts';
	import Card from '#lib/components/Card.svelte';
	import LineChart from '#lib/components/LineChart.svelte';
	import More from '#lib/components/More.svelte';

	const r = $derived(rn.result!);
	const labels = $derived(r.scenario.map((_, i) => `W${i + 1}`));
	const pop = $derived(r.districts.reduce((a, d) => a + d.population, 0));

	const STEPS = [
		{ name: 'The epidemic spreads', text: 'Every tract follows the same simulated curve: people catch it, become contagious, and recover. A share of them need a hospital bed.' },
		{ name: 'Patients head for nearby hospitals', text: 'Each tract sends its new patients to its five nearest hospitals within 10 km, more to closer ones.' },
		{ name: 'Strain spreads', text: 'A hospital with more patients than beds scores lower, drags close-by hospitals down a little, and lowers the access score of tracts that rely on it.' },
		{ name: 'Overflow is rerouted', text: 'New patients who did not fit are moved to any hospital with spare beds. Then every score is worked out again.' }
	];

	const UNITS = [
		['Beds', 'People in hospital beds at one time.'],
		['Need, unmet, sent elsewhere', 'People per week who newly need a bed. Not beds, and not deaths.'],
		['Scores', '0 to 100. 100 means fully able to cope; under 70 counts as poor access on these pages, a display choice and not a clinical standard.'],
		['Before / after rerouting', 'The same week of the same run, before and after overflow patients are moved.'],
		['No events', 'The same settings with no closures or bed cuts, used for every comparison.']
	];

	const LIMITS = [
		'The epidemic is simulated, not observed. Every tract shares one regional curve; a tract’s need differs only by its population and risk weight.',
		'Capacity is each hospital’s licensed beds, a stand-in for the staffed beds that matter on a given day.',
		'Which hospital a tract uses comes from straight-line distance, not real patient records or travel times.',
		'Rerouting moves only new patients. People already in a bed stay, even when their hospital closes; they are counted as stranded.',
		'Tested against real hospital data, the model predicts worse than “next week looks like this week”. Use it to explore what-ifs, not to forecast.'
	];
</script>

<div class="page">
	<div class="page-head">
		<h1>How it works</h1>
		<p>
			ResiliNet asks one question: when an epidemic fills hospitals, or a hospital closes, which neighbourhoods lose access to
			care? It steps through the outbreak one week at a time using real Suffolk County census tracts and hospitals, and every
			assumption can be changed with <b>What if…?</b>
		</p>
	</div>

	<Card title="Every simulated week, four steps" sub="Each step uses the result of the one before. Next week starts from where this one ended.">
		<div class="flow">
			{#each STEPS as s, i (s.name)}
				<div class="step">
					<span class="n">{i + 1}</span>
					<b>{s.name}</b>
					<span>{s.text}</span>
				</div>
				{#if i < STEPS.length - 1}<span class="arrow">→</span>{/if}
			{/each}
		</div>
		<p class="muted small pipe">
			In the code: data → separate → IL1 → SEIR → IL2 → FDNA → analysis → IL3 → results, the same pipeline the tests and the
			Streamlit app use.
		</p>
	</Card>

	<div class="grid-2">
		<Card title="Step 1 in this run: the epidemic" sub="New infections per week, across all {num(pop)} residents">
			<LineChart
				{labels}
				height={200}
				marker={rn.week}
				onscrub={(i) => (rn.week = i)}
				series={[{ id: 'inf', label: 'New infections', values: r.epi.new_infections, color: '#d55181', area: true }]}
			/>
			<p class="muted small">
				By the last week {pct(1 - (r.epi.susceptible.at(-1) ?? 1), 0)} of residents have been infected. Each case first infects
				about {fixed(rn.params.r0, 1)} others.
			</p>
		</Card>
		<Card title="…and the beds it needs" sub="People per week who newly need a hospital bed">
			<LineChart
				{labels}
				height={200}
				marker={rn.week}
				onscrub={(i) => (rn.week = i)}
				series={[
					{ id: 'need', label: 'Need a bed', values: r.epi.need, color: '#3987e5', area: true },
					{ id: 'unmet', label: "Can't get one", values: r.scenario.map((w) => w[rn.phase].metrics.unmet_need_people), color: '#d03b3b' }
				]}
			/>
			<p class="muted small">{pct(rn.params.p_h, 1)} of people leaving the contagious stage need a bed, and each stays about a week.</p>
		</Card>
	</div>

	<div class="grid-2">
		<Card title="What the numbers mean">
			<dl class="kv">
				{#each UNITS as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}
			</dl>
		</Card>
		<Card title="What it can't tell you">
			<ul class="limits">
				{#each LIMITS as l (l)}<li>{l}</li>{/each}
			</ul>
		</Card>
	</div>

	<More title="The maths" sub="Equations behind each step, with this run's settings">
		<div class="grid-2">
			<pre class="eq">SEIR (7 daily substeps per week, S+E+I+R = N)
  new admissions need  H_need[j] = p_H · risk[j] · (I → R flow)
Distance shares
  a[j,i] = exp(−d[j,i] / d₀),  k = 5 nearest within 10 km
  s[j,i] = a[j,i] / Σ a[j,·]
Hospital own score
  O[i] = 100 · min(1, C_eff[i] / requested load[i])
Hospital network score (hospitals within 5 km)
  P[i] = min( O[i],
              mean_m( α_H·P[m] + (1−α_H)·O[i] ),
              min_m( P[m] + β_H ) )
Tract access score
  SOD = α_D · Σ s·P + (1−α_D) · 100
  COD = min_i( P[i] + 100·(1 − s[j,i]) )
  A[j] = min(SOD, COD)</pre>
			<dl class="kv">
				<dt>R₀</dt><dd>{fixed(rn.params.r0, 2)}</dd>
				<dt>p_H</dt><dd>{fixed(rn.params.p_h, 3)}</dd>
				<dt>Infectious at start</dt><dd>{fixed(rn.params.seed, 4)}</dd>
				<dt>Latent / infectious</dt><dd>5 / 7 days</dd>
				<dt>Hospital stay</dt><dd>7 days</dd>
				<dt>d₀</dt><dd>{fixed(rn.params.d0, 1)} km</dd>
				<dt>α_D / α_H / β_H</dt><dd>{fixed(rn.params.alpha_d, 2)} / {fixed(rn.params.alpha_h, 2)} / 100</dd>
				<dt>Usual occupancy</dt><dd>75% of beds</dd>
				<dt>Poor access under</dt><dd>{r.threshold}</dd>
			</dl>
		</div>
		<p class="muted small">
			Scores are solved with all hospitals updated together until they change by less than 0.1 points; a run that does not
			settle stops with an error instead of showing numbers. Every run checks that people are conserved, that no hospital
			holds more than its beds, and that nothing moves when there is nothing to reroute. Rerouting first reserves each
			tract's usual hospitals, then moves the remainder to any hospital with spare beds, keeping track of where each patient
			came from.
		</p>
	</More>

	<p class="muted disclaimer">
		A research simulation. It models possible access under simple assumptions and is not for emergency dispatch, medical
		triage or hospital planning. The earlier daily model is still available under <a href="/daily">Daily</a>.
	</p>
</div>

<style>
	.flow {
		display: flex;
		align-items: stretch;
		gap: 10px;
		flex-wrap: wrap;
	}
	.step {
		flex: 1;
		min-width: 170px;
		background: var(--bg);
		border: 1px solid var(--line-2);
		border-radius: 10px;
		padding: 12px;
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 12px;
		color: var(--text-3);
		line-height: 1.45;
	}
	.step b {
		color: var(--text-1);
		font-size: 13px;
		font-weight: 600;
	}
	.n {
		font-family: var(--mono);
		font-size: 10.5px;
		color: var(--accent);
	}
	.arrow {
		align-self: center;
		color: var(--text-3);
	}
	.pipe {
		margin-top: 12px !important;
	}
	.eq {
		font-family: var(--mono);
		font-size: 12px;
		line-height: 1.7;
		color: var(--text-2);
		background: var(--bg);
		border: 1px solid var(--line);
		border-radius: 10px;
		padding: 12px 14px;
		margin: 0;
		overflow-x: auto;
	}
	.kv {
		display: grid;
		grid-template-columns: 180px 1fr;
		gap: 6px 16px;
		margin: 0;
		font-size: 12.5px;
	}
	.kv dt {
		color: var(--text-3);
	}
	.kv dd {
		margin: 0;
		color: var(--text-1);
		line-height: 1.5;
	}
	.limits {
		margin: 0;
		padding-left: 18px;
		font-size: 12.5px;
		line-height: 1.55;
		color: var(--text-2);
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.small {
		font-size: 12px;
		line-height: 1.55;
		margin: 8px 0 0;
	}
	.disclaimer {
		font-size: 12px;
		max-width: 820px;
		line-height: 1.55;
		margin: 0;
	}
</style>
