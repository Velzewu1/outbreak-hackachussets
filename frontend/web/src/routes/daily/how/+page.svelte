<script lang="ts">
	import { app } from '#lib/state.svelte.ts';
	import { num, pct, fixed, days } from '#lib/format.ts';
	import { COMPARTMENT, LABEL } from '#lib/colors.ts';
	import Card from '#lib/components/Card.svelte';
	import More from '#lib/components/More.svelte';

	const d = $derived(app.result!.describe);
	const disease = $derived(app.detail?.epi.disease ?? {});
	const pop = $derived(app.detail?.epi.population);

	const STEPS = [
		{ id: 'seir', name: 'It spreads', text: 'People catch it, fall sick, and some need a hospital bed. Tracked by neighborhood and age.' },
		{ id: 'alloc', name: 'Patients pick a hospital', text: 'Mostly large hospitals close to home, the way people really choose.' },
		{ id: 'fdna', name: 'Hospitals feel the strain', text: 'Staff off sick and full beds cut what each hospital can do. Shared services pass problems along.' },
		{ id: 'reroute', name: 'Full hospitals send patients on', text: 'A full hospital turns new patients away until it has room again.' },
		{ id: 'equity', name: 'Who loses out', text: 'How much of each neighborhood’s usual hospital care is still open.' }
	];
	// The stages a person moves through, in everyday words.
	const STAGE: Record<string, string> = {
		S: 'Can catch it',
		E: 'Caught it, not yet contagious',
		I: 'Contagious',
		A: 'Contagious, no symptoms',
		R: 'Recovered',
		V: 'Vaccinated',
		H: 'On a hospital ward',
		C: 'In intensive care',
		D: 'Died'
	};

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
		['People', 'Neighborhood populations from the 2020 Census, rounded. The age split is approximate.'],
		['Places', 'Neighborhood centres and hospital campuses are approximate locations.'],
		['Beds', 'About a third of each hospital’s beds are counted as serving Boston residents, and three quarters of those are already taken by other patients.'],
		['Travel', 'Straight-line distance, stretched by a third for real roads, at city driving speed plus 5 minutes.'],
		['Mixing', 'Published US contact rates between age groups. People spend most of their time near home and mix less with distant neighborhoods.'],
		['Vulnerability', 'Hand-set weights standing in for a social vulnerability index.'],
		['Hospital links', 'How strongly hospitals depend on staff, beds and shared services is illustrative, not measured.'],
		['Disease', 'Omicron, tuned to Massachusetts admissions: each case infects about 1.95 others at first, and 22% of people were already immune on 1 Dec 2021.']
	];

	const DATA = [
		['HHS daily COVID admissions, Massachusetts', 'Tuning and testing on the Omicron wave'],
		['COVID Tracking Project hospital counts (CC BY 4.0)', 'An independent test on winter 2020–21'],
		['Prem et al. 2021 contact matrices', 'How much age groups mix'],
		['Google COVID-19 Community Mobility', 'The lockdown-style scenario'],
		['MassGIS hospitals, CMS hospital information', 'Bed counts and which hospital is which'],
		['City of Boston neighborhood boundaries', 'The shapes on the map'],
		['CDC PLACES', 'Optional: more severe illness where chronic disease is common']
	];
</script>

<div class="page">
	<div class="page-head">
		<h1>How it works</h1>
		<p>
			A what-if tool for Boston: an outbreak fills hospital beds, strained hospitals start turning patients away, and the
			map shows which neighborhoods lose their usual care. It uses public data only and every assumption can be changed
			with <b>What if…?</b>
		</p>
	</div>

	<Card title="Every simulated day, five steps" sub="Each step uses the result of the one before.">
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
		<div class="feedback"><span></span>When intensive care is overstretched, more patients die the next day.</div>
	</Card>

	<div class="grid-2">
		<Card title="The stages a person moves through" sub="Everyone starts able to catch it. Most recover at home; some go to hospital.">
			<div class="comps">
				{#each d.compartments as c, i (c)}
					<span class="comp" style:--c={COMPARTMENT[c] ?? '#888'}><i></i>{STAGE[c] ?? LABEL[c] ?? c}</span>
					{#if i < d.compartments.length - 1}<span class="sep"></span>{/if}
				{/each}
			</div>
		</Card>
		<Card title="This scenario" sub={app.detail?.title}>
			<dl class="kv">
				<dt>People</dt><dd>{num(d.population)} in {d.patches === 1 ? 'one group' : `${d.patches} neighborhoods`}</dd>
				<dt>Age groups</dt><dd>{pop?.ages.join(' · ')}</dd>
				<dt>Each case infects at first</dt><dd>about {fixed(d.r0, 2)} others</dd>
				<dt>From one case to the next</dt><dd>{days(d.generation_time_days)}</dd>
				<dt>Cases double every</dt><dd>{days(d.doubling_time_days)} at the start</dd>
				<dt>Already immune</dt><dd>{pct(typeof app.detail?.epi.seeding.immune_share === 'number' ? app.detail.epi.seeding.immune_share : 0)}</dd>
				{#if app.changeCount}<dt>Your changes</dt><dd>{app.changeCount} setting{app.changeCount === 1 ? '' : 's'} changed</dd>{/if}
			</dl>
		</Card>
	</div>

	<More title="The maths and every disease setting" sub="For readers who want the equations and raw values.">
		<div class="grid-2">
			<pre class="eq">λ[p,a] = β(t) Σᵣ W[p,r] Σ_b C[a,b] I[r,b] / N[r,b]
S → E  λ            E → I  σ = 1 / latent period
I → H  p_hosp · γ   I → R  (1 − p_hosp) · γ
H → C  p_icu / LOS_ward      H → R  the rest
C → D  p_death_icu / LOS_icu C → R  the rest
γ = 1 / infectious period
R_eff = ρ(next-generation matrix, today's susceptibles)</pre>
			<dl class="kv">
				<dt>Transmission β₀</dt><dd>{fixed(d.transmission_rate, 4)} /day</dd>
				<dt>Incubation σ</dt><dd>{d.incubation_rate ? `${fixed(d.incubation_rate, 3)} /day` : '–'}</dd>
				<dt>Recovery γ</dt><dd>{d.recovery_rate ? `${fixed(d.recovery_rate, 3)} /day` : '–'}</dd>
				{#each Object.entries(disease).filter(([k]) => !['r0', 'latent_period', 'infectious_period'].includes(k)) as [k, v] (k)}
					<dt>{k.replaceAll('_', ' ')}</dt><dd>{fmtValue(v)}</dd>
				{/each}
			</dl>
		</div>
		<p class="muted small">
			Four substeps a day. Neighborhoods mix through a distance kernel (W), ages through contact matrix C. Hospitals are
			chosen in proportion to beds × exp(−decay × drive minutes). Hospital function comes from a functional dependency
			network (FDNA), and diversion switches on and off with hysteresis.
		</p>
	</More>

	<div class="grid-2">
		<Card title="What we assumed" sub="Made by seir/systems/make_boston.py from two tables. Illustrative, not tuned to Boston hospitals.">
			<dl class="kv wide">
				{#each ASSUMPTIONS as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}
			</dl>
		</Card>
		<Card title="Where the data comes from">
			<dl class="kv wide">
				{#each DATA as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}
			</dl>
			{#if app.presets}
				<div class="h">Research behind the disease settings</div>
				<ul class="refs">
					{#each Object.entries(app.presets.sources) as [k, url] (k)}
						<li><a href={url} target="_blank" rel="noreferrer">{k}</a></li>
					{/each}
				</ul>
			{/if}
		</Card>
	</div>

	<p class="muted disclaimer">
		For research and demonstration only: not a forecast, and not for real hospital or medical decisions. Hospital data
		alone cannot tell apart how contagious a disease is, how severe it is and how many people were already immune, so
		those three are partly assumptions.
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
		padding: 4px 11px 4px 9px;
	}
	.comp i {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--c);
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
		grid-template-columns: 180px 1fr;
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
	.small {
		font-size: 12px;
		line-height: 1.55;
		margin: 0;
	}
	.disclaimer {
		font-size: 12px;
		max-width: 820px;
		line-height: 1.55;
		margin: 0;
	}
</style>
