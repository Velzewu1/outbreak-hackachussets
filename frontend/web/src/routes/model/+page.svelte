<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { num, pct, fixed, days } from '#lib/format.ts';
	import { COMPARTMENT, LABEL } from '#lib/colors.ts';
	import Card from '#lib/components/Card.svelte';

	const d = $derived(app.result!.describe);
	const disease = $derived(app.detail?.epi.disease ?? {});
	const pop = $derived(app.detail?.epi.population);

	const STEPS = [
		{ id: 'seir', name: 'SEIR', text: 'Infections, ward, ICU and deaths by neighborhood and age' },
		{ id: 'alloc', name: 'Allocation', text: 'Admissions to hospitals by beds · exp(−decay · drive minutes)' },
		{ id: 'fdna', name: 'FDNA', text: 'Operability from staff, beds and shared services' },
		{ id: 'reroute', name: 'Rerouting', text: 'Diversion with hysteresis; patients move to open hospitals' },
		{ id: 'equity', name: 'Equity', text: 'Share of usual care still open, weighted by vulnerability' }
	];

	const fmtValue = (v: unknown): string => {
		if (typeof v === 'number') return Math.abs(v) < 1 && v !== 0 ? fixed(v, 3) : fixed(v, 2);
		if (Array.isArray(v)) return v.map(fmtValue).join(' · ');
		if (v && typeof v === 'object')
			return Object.entries(v as Record<string, unknown>)
				.map(([k, x]) => `${k}: ${fmtValue(x)}`)
				.join(' · ');
		return String(v);
	};

	const ASSUMPTIONS = [
		['Populations', 'Boston neighborhoods from 2020 Census totals, rounded; age split approximate.'],
		['Places', 'Neighborhood centroids and hospital campuses are approximate coordinates.'],
		['Beds', 'MassGIS ICU and med-surg beds × 0.35, the share assumed to serve Boston residents; 75% filled by other patients.'],
		['Travel', 'Straight-line distance × 1.35 road factor at 24 km/h plus 5 minutes.'],
		['Mixing', 'Prem 2021 US age contacts; neighborhoods coupled by a 2 km distance kernel, 75% of time at home.'],
		['Vulnerability', 'Hand-set weights standing in for a social vulnerability index.'],
		['FDNA', 'Strengths and criticalities of dependency are illustrative (reference design), not measured.'],
		['Disease', 'covid_omicron preset with the Massachusetts fit (R₀ 1.95, severity 1.08×, 22% immune on 1 Dec 2021).']
	];

	const DATA = [
		['HHS daily COVID admissions, Massachusetts', 'Calibration and validation of the Omicron wave'],
		['COVID Tracking Project hospital census (CC BY 4.0)', 'Out-of-sample check, winter 2020–21'],
		['Prem et al. 2021 contact matrices', 'Age mixing'],
		['Google COVID-19 Community Mobility', 'Mobility-driven transmission scenario'],
		['MassGIS hospitals, CMS hospital general information', 'Bed counts and hospital identities'],
		['CDC PLACES', 'Optional comorbidity multiplier on severity']
	];
</script>

<div class="page">
	<div class="page-head">
		<h1>Model</h1>
		<p>
			A what-if tool for research and demos: an epidemic wave drives hospital load, hospital disruption propagates
			through a dependency network, overloaded hospitals divert patients, and the map shows which neighborhoods lose
			access to care. Public aggregate data only; every assumption below is configurable.
		</p>
	</div>

	<Card title="Daily loop" sub="Each module reads the previous one's frozen snapshot. ICU strain feeds back into SEIR mortality the next day.">
		<div class="flow">
			{#each STEPS as s, i (s.id)}
				<div class="step">
					<span class="n">{i + 1}</span>
					<b>{s.name}</b>
					<span>{s.text}</span>
				</div>
				{#if i < STEPS.length - 1}<span class="arrow">→</span>{/if}
			{/each}
		</div>
		<div class="feedback"><span></span>FDNA ICU operability → SEIR death rate, one day later</div>
	</Card>

	<div class="grid-2">
		<Card title="Compartments" sub="People move along these arrows each day, in 4 substeps.">
			<div class="comps">
				{#each d.compartments as c, i (c)}
					<span class="comp" style:--c={COMPARTMENT[c] ?? '#888'}><b>{c}</b>{LABEL[c] ?? c}</span>
					{#if i < d.compartments.length - 1}<span class="sep"></span>{/if}
				{/each}
			</div>
			<pre class="eq">λ[p,a] = β(t) Σᵣ W[p,r] Σ_b C[a,b] I[r,b] / N[r,b]
S → E  λ            E → I  σ = 1 / latent period
I → H  p_hosp · γ   I → R  (1 − p_hosp) · γ
H → C  p_icu / LOS_ward      H → R  the rest
C → D  p_death_icu / LOS_icu C → R  the rest
γ = 1 / infectious period
R_eff = ρ(next-generation matrix, today's susceptibles)</pre>
		</Card>
		<Card title="Current scenario" sub={app.detail?.title}>
			<dl class="kv">
				<dt>Population</dt><dd>{num(d.population)} in {d.patches} {d.patches === 1 ? 'patch' : 'neighborhoods'} × {d.age_groups} ages</dd>
				<dt>Ages</dt><dd>{pop?.ages.join(' · ')}</dd>
				<dt>R₀</dt><dd>{fixed(d.r0, 2)}</dd>
				<dt>Transmission β₀</dt><dd>{fixed(d.transmission_rate, 4)} /day</dd>
				<dt>Incubation σ</dt><dd>{d.incubation_rate ? `${fixed(d.incubation_rate, 3)} /day` : '–'}</dd>
				<dt>Recovery γ</dt><dd>{d.recovery_rate ? `${fixed(d.recovery_rate, 3)} /day` : '–'}</dd>
				<dt>Generation time</dt><dd>{days(d.generation_time_days)}</dd>
				<dt>Doubling time (R₀)</dt><dd>{days(d.doubling_time_days)}</dd>
				{#each Object.entries(disease).filter(([k]) => !['r0', 'latent_period', 'infectious_period'].includes(k)) as [k, v] (k)}
					<dt>{k.replaceAll('_', ' ')}</dt><dd>{fmtValue(v)}</dd>
				{/each}
				{#if app.changeCount}<dt>Your changes</dt><dd>{app.changeCount} on top of the file</dd>{/if}
			</dl>
		</Card>
	</div>

	<div class="grid-2">
		<Card title="Assumptions in the Boston scenario" sub="Generated by seir/systems/make_boston.py from two CSV tables. Illustrative, not calibrated.">
			<dl class="kv wide">
				{#each ASSUMPTIONS as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}
			</dl>
		</Card>
		<Card title="Data">
			<dl class="kv wide">
				{#each DATA as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}
			</dl>
			{#if app.presets}
				<div class="h">Literature behind the disease presets</div>
				<ul class="refs">
					{#each Object.entries(app.presets.sources) as [k, url] (k)}
						<li><a href={url} target="_blank" rel="noreferrer">{k}</a></li>
					{/each}
				</ul>
			{/if}
		</Card>
	</div>

	<p class="muted disclaimer">
		Research and demonstration only. Not a forecast and not for operational or clinical decisions. Immunity is set at the
		start ({pct(typeof app.detail?.epi.seeding.immune_share === 'number' ? app.detail.epi.seeding.immune_share : 0)}
		here); admissions alone cannot separate immunity, R₀ and severity.
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
		min-width: 150px;
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
	.feedback {
		margin-top: 12px;
		font-size: 12px;
		color: var(--text-3);
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.feedback span {
		width: 40px;
		height: 10px;
		border: 1px dashed var(--accent);
		border-top: 0;
		border-radius: 0 0 8px 8px;
	}
	.comps {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: 14px;
	}
	.comp {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		color: var(--text-2);
		border: 1px solid var(--line-2);
		border-radius: 999px;
		padding: 3px 10px 3px 4px;
	}
	.comp b {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: var(--c);
		color: #fff;
		display: grid;
		place-items: center;
		font-size: 11px;
	}
	.sep {
		width: 10px;
		height: 1px;
		background: var(--line-2);
	}
	.eq {
		font-family: var(--mono);
		font-size: 12px;
		line-height: 1.8;
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
		grid-template-columns: 150px 1fr;
		gap: 6px 16px;
		margin: 0;
		font-size: 12.5px;
	}
	.kv.wide {
		grid-template-columns: 170px 1fr;
	}
	.kv dt {
		color: var(--text-3);
		text-transform: none;
	}
	.kv dd {
		margin: 0;
		color: var(--text-1);
		line-height: 1.5;
	}
	.h {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-3);
		margin: 18px 0 8px;
	}
	.refs {
		margin: 0;
		padding-left: 16px;
		font-size: 12px;
		line-height: 1.75;
		color: var(--text-2);
	}
	.refs a {
		color: var(--text-2);
		text-decoration-color: var(--line-2);
		text-underline-offset: 3px;
	}
	.refs a:hover {
		color: var(--text-1);
	}
	.disclaimer {
		font-size: 12px;
		max-width: 820px;
		line-height: 1.55;
		margin: 0;
	}
</style>
