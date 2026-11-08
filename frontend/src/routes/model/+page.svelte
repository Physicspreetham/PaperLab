<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api.js';
	import { model, modelStore } from '$lib/modelStore.js';

	const FAMILIES = ['JEE Advanced', 'JEE Main', 'BITSAT', 'NEET', 'AP EAPCET', 'TS EAPCET', 'KCET', 'COMEDK UGET'];
	const MIXES = [
		{ key: 'adv', label: 'Advanced level', hint: 'mostly Hard', d: { Easy: 0, Medium: 2, Hard: 8 } },
		{ key: 'bal', label: 'Balanced', hint: 'Medium + Hard', d: { Easy: 1, Medium: 5, Hard: 5 } },
		{ key: 'med', label: 'Medium level', hint: 'JEE Main plus', d: { Easy: 2, Medium: 8, Hard: 2 } }
	];
	const VERIFY = {
		published: { tone: 'warn', text: 'Latest (2026) pattern and marking scheme as published by the exam body and reported by coaching institutes: please confirm against the official information bulletin. Every number can be corrected after the paper is created.' },
		official: { tone: 'ok', text: 'Verified: structure and marking scheme read from the official paper.' },
		quoted: { tone: 'warn', text: 'Structure verified from the official paper. Marking scheme quoted from the official instructions by a published source: please confirm.' },
		secondary: { tone: 'warn', text: 'Structure verified from the official paper. Marks come from published analyses (the archive copy has no instruction page): please confirm.' },
		confirm: { tone: 'warn', text: 'Structure verified from the official paper. Marks and negative marking are from published analyses: please confirm against the official paper. Every number can be corrected after the paper is created.' }
	};

	let mode = $state(null);
	let patterns = $state([]);
	let topics = $state([]);
	let facets = $state(null);
	let loadError = $state('');

	let family = $state('JEE Advanced');
	let year = $state(null);
	let paperNo = $state(1);
	let chapters = $state([]); // chapter codes; empty = whole syllabus
	let subs = $state({}); // chapter code -> chosen subtopic codes
	let mix = $state('adv');
	let diff = $state({ ...MIXES[0].d });
	let exams = $state([]);
	let institutes = $state([]);
	let excludeUsed = $state(true);
	let requireKey = $state(true);
	let title = $state('');
	let minutes = $state('');
	let avail = $state({});
	let usedCount = $state(0);
	let busy = $state(false);
	let msg = $state(null); // {ok, text}

	onMount(async () => {
		try {
			const [p, t, f] = await Promise.all([api.modelPatterns(), api.getTopics(), api.getSearchFacets()]);
			patterns = p.patterns;
			topics = t;
			facets = f;
		} catch (e) {
			loadError = e.message;
		}
	});

	const families = $derived(FAMILIES.filter((f) => patterns.some((p) => (p.family || 'JEE Advanced') === f)));
	const famList = $derived(patterns.filter((p) => (p.family || 'JEE Advanced') === family));
	const years = $derived([...new Set(famList.map((p) => p.year))].sort((a, b) => b - a));
	$effect(() => {
		if (years.length && !years.includes(year)) year = years[0];
	});
	const pattern = $derived(famList.find((p) => p.year === year && p.paper === paperNo) || famList.find((p) => p.year === year));
	$effect(() => {
		if (pattern) minutes = String(pattern.minutes);
	});

	// topic tree: module -> chapter -> week -> subtopic
	const kids = $derived.by(() => {
		const m = new Map();
		for (const t of topics) {
			const k = t.parent ?? '';
			if (!m.has(k)) m.set(k, []);
			m.get(k).push(t);
		}
		return m;
	});
	const modules = $derived(kids.get('') ?? []);
	const chapterSubs = (code) =>
		(kids.get(code) ?? []).flatMap((w) => [{ week: w.name }, ...(kids.get(w.code) ?? []).map((s) => ({ ...s }))]);

	const options = $derived({
		topics: chapters.flatMap((c) => (subs[c]?.length ? subs[c] : [c])),
		exams,
		institutes,
		difficulty: diff,
		exclude_used: excludeUsed,
		require_key: requireKey
	});
	const optKey = $derived(JSON.stringify([pattern?.id, options]));

	$effect(() => {
		void optKey;
		if (!pattern || mode !== 'auto') return;
		const snapshot = { pattern, options };
		let live = true;
		const t = setTimeout(() => {
			api
				.modelPreview(snapshot)
				.then((d) => {
					if (!live) return;
					avail = Object.fromEntries(d.sections.map((s) => [s.id, s.available]));
					usedCount = d.usedCount;
				})
				.catch(() => {});
		}, 250);
		return () => {
			live = false;
			clearTimeout(t);
		};
	});

	const toggleChapter = (c) => (chapters = chapters.includes(c) ? chapters.filter((x) => x !== c) : [...chapters, c]);
	const toggleModule = (m) => {
		const ids = (kids.get(m.code) ?? []).map((c) => c.code);
		chapters = ids.every((i) => chapters.includes(i)) ? chapters.filter((x) => !ids.includes(x)) : [...new Set([...chapters, ...ids])];
	};
	const toggleSub = (c, code) => {
		if (!chapters.includes(c)) chapters = [...chapters, c];
		const cur = subs[c] ?? [];
		subs = { ...subs, [c]: cur.includes(code) ? cur.filter((x) => x !== code) : [...cur, code] };
	};
	const toggle = (arr, v) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
	const pickMix = (m) => {
		mix = m.key;
		diff = { ...m.d };
	};

	const verify = $derived(pattern ? VERIFY[pattern.verified] : null);
	const shortSecs = $derived(pattern ? pattern.sections.filter((s) => avail[s.id] !== undefined && avail[s.id] < s.units) : []);

	async function create(mode) {
		if (!pattern || !mode || busy) return;
		busy = true;
		msg = null;
		try {
			const mins = Number(minutes) || pattern.minutes;
			const pat = { ...pattern, minutes: mins };
			let picks = [];
			let report = [];
			if (mode === 'auto') {
				const r = await api.modelGenerate({ pattern: pat, options, record: true });
				picks = r.sections;
				report = r.sections;
			}
			const described = await api.modelDescribe(pat);
			model.create({
				pattern: described,
				options,
				title: title.trim() || `${pattern.label} (Physics) — ${mode === 'auto' ? 'model paper' : 'manual paper'}`,
				picks
			});
			const short = report.filter((x) => x.items.length < x.wanted);
			if (short.length) {
				sessionStorage.setItem(
					'pl-model-note',
					`Paper created, but ${short.map((x) => `Section ${x.id.replace('S', '')} has ${x.items.length} of ${x.wanted}`).join('; ')}. Fill the rest by hand or loosen the filters.`
				);
			}
			await goto('/model/paper');
		} catch (e) {
			msg = { ok: false, text: e.message };
		} finally {
			busy = false;
		}
	}

	async function forgetUsed() {
		try {
			const r = await api.modelForgetUsed();
			usedCount = 0;
			msg = { ok: true, text: `Forgot ${r.cleared} used question${r.cleared === 1 ? '' : 's'}.` };
			optKeyBump();
		} catch (e) {
			msg = { ok: false, text: e.message };
		}
	}
	// re-run the availability preview after used questions are cleared
	function optKeyBump() {
		diff = { ...diff };
	}
</script>

<svelte:head><title>Model paper - PaperLab</title></svelte:head>

<div class="mp">
	<header class="head">
		<p class="eyebrow">ASSESSMENTS</p>
		<h1>Model paper</h1>
		<p class="pl-sub">
			Pick an exam and its pattern (JEE Advanced, JEE Main, BITSAT, NEET, EAPCET, KCET, COMEDK), then generate the Physics paper
			automatically or fill every section by hand.
		</p>
		{#if $modelStore}
			<p class="resume">
				You have a model paper in progress: <strong>{$modelStore.title || $modelStore.pattern.label}</strong>.
				<a href="/model/paper">Continue editing</a>
			</p>
		{/if}
	</header>

	<div class="mode-picker" role="group" aria-label="How to create your model paper">
		{#each [{ key: 'auto', label: 'Generate automatically' }, { key: 'manual', label: 'Build manually' }] as choice (choice.key)}
			<button type="button" class="pl-btn" class:chosen={mode === choice.key}
				aria-expanded={mode === choice.key} aria-controls="model-setup" disabled={busy}
				onclick={() => { mode = mode === choice.key ? null : choice.key; msg = null; }}>
				{choice.label} <span aria-hidden="true">{mode === choice.key ? '−' : '+'}</span>
			</button>
		{/each}
	</div>

	<div id="model-setup" class="setup">
	{#if mode}
	{#if loadError}
		<p class="pl-error" role="alert">Could not load: {loadError}</p>
	{:else if !pattern}
		<p class="pl-sub">Loading…</p>
	{:else}
		<section class="card">
			<h2>1 · Pattern</h2>
			<div class="row">
				<span class="label">Exam</span>
				<select bind:value={family} onchange={() => (paperNo = 1)} aria-label="Exam">
					{#each families as f (f)}<option value={f}>{f}</option>{/each}
				</select>
				<select bind:value={year} aria-label="Year">
					{#each years as y (y)}
						<option value={y}>{family === 'JEE Advanced' ? `${y} · ${y >= 2013 ? 'JEE Advanced' : 'IIT-JEE'}` : `${y} pattern (latest)`}</option>
					{/each}
				</select>
			</div>
			{#if family === 'JEE Advanced'}
				<div class="row">
					<span class="label">Paper</span>
					<div class="seg" role="group" aria-label="Paper">
						{#each [1, 2] as n (n)}
							<button type="button" class:on={pattern.paper === n} aria-pressed={pattern.paper === n} onclick={() => (paperNo = n)}>Paper {n}</button>
						{/each}
					</div>
				</div>
			{/if}
			<div class="preview">
				<header>
					<strong>{pattern.label} · Physics</strong>
					<span class="badge {verify.tone}">{verify.tone === 'ok' ? 'Official pattern' : 'Marks to confirm'}</span>
				</header>
				<p class="verify {verify.tone}">{verify.tone === 'ok' ? '✓' : '⚠'} {verify.text}</p>
				<table>
					<thead><tr><th>Section</th><th>Question type</th><th>Questions</th><th>Marks each</th><th>Negative</th><th>Max</th></tr></thead>
					<tbody>
						{#each pattern.sections as s (s.id)}
							<tr>
								<td>{s.id.replace('S', '')}</td>
								<td>{s.typeName}{#if s.sets && s.per}<small> · {s.sets} × {s.per}</small>{/if}{#if s.partial}<small> · partial marks</small>{/if}</td>
								<td>{s.n}</td>
								<td>{s.max && s.type === 'matrix' ? `${s.max / s.n} per question` : `+${s.c}`}</td>
								<td>{s.neg ? `−${s.neg}` : s.type === 'matrix' && s.negRow ? `−${s.negRow} per entry` : '—'}</td>
								<td>{s.max}</td>
							</tr>
						{/each}
					</tbody>
					<tfoot><tr><td colspan="2">Physics total</td><td>{pattern.questions}</td><td></td><td></td><td>{pattern.total}</td></tr></tfoot>
				</table>
			</div>
		</section>

		{#if mode === 'auto'}
		<section class="card">
			<h2>2 · What to draw from</h2>
			<div class="scope">
				<div class="scope-head">
					<strong>Chapters</strong>
					<span class="pl-sub">{chapters.length ? `${chapters.length} selected` : 'Whole syllabus'}</span>
					{#if chapters.length}<button type="button" class="link" onclick={() => { chapters = []; subs = {}; }}>Clear</button>{/if}
				</div>
				{#each modules as m (m.code)}
					{@const cs = kids.get(m.code) ?? []}
					{@const all = cs.length > 0 && cs.every((c) => chapters.includes(c.code))}
					<div class="module">
						<button type="button" class="mod" class:on={all} aria-pressed={all} onclick={() => toggleModule(m)}>{m.name}</button>
						<div class="chapters">
							{#each cs as c (c.code)}
								<div class="chapter">
									<label><input type="checkbox" checked={chapters.includes(c.code)} onchange={() => toggleChapter(c.code)} />{c.name}</label>
									<details>
										<summary>{subs[c.code]?.length ? `${subs[c.code].length} topics` : 'All topics'}</summary>
										<p class="pl-sub">Random picking uses only the topics you tick. Leave all unticked for the whole chapter.</p>
										{#each chapterSubs(c.code) as t, i (i)}
											{#if t.week}
												<p class="week">{t.week}</p>
											{:else}
												<label class="sub"><input type="checkbox" checked={!!subs[c.code]?.includes(t.code)} onchange={() => toggleSub(c.code, t.code)} />{t.name}</label>
											{/if}
										{/each}
									</details>
								</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>

			<div class="row">
				<span class="label">Level</span>
				<div class="seg" role="group" aria-label="Difficulty mix">
					{#each MIXES as m (m.key)}
						<button type="button" class:on={mix === m.key} aria-pressed={mix === m.key} title={m.hint} onclick={() => pickMix(m)}>{m.label}</button>
					{/each}
				</div>
			</div>
			<div class="diff">
				{#each ['Easy', 'Medium', 'Hard'] as d (d)}
					<label class="slider">
						<span>{d}</span>
						<input type="range" min="0" max="10" value={diff[d]} oninput={(e) => { mix = 'custom'; diff = { ...diff, [d]: Number(e.currentTarget.value) }; }} aria-label={`${d} weight`} />
						<b>{diff[d]}</b>
					</label>
				{/each}
				<small class="pl-sub">Higher weight = more likely to be picked. 0 leaves that level out. Questions with no difficulty set count as 1.</small>
			</div>

			{#if facets?.exams?.length}
				<div class="row">
					<span class="label">Exam</span>
					<div class="checks">
						{#each facets.exams as e (e.value)}
							<label><input type="checkbox" checked={exams.includes(e.value)} onchange={() => (exams = toggle(exams, e.value))} /> {e.value} <small class="pl-sub">({e.count})</small></label>
						{/each}
						<span class="pl-sub">{exams.length ? `${exams.length} chosen` : 'All exams'}</span>
					</div>
				</div>
			{/if}
			{#if facets?.institutes?.length}
				<div class="row">
					<span class="label">Institute</span>
					<div class="checks">
						{#each facets.institutes as ins (ins.key)}
							<label><input type="checkbox" checked={ins.raws.every((r) => institutes.includes(r))} onchange={() => {
								const on = ins.raws.every((r) => institutes.includes(r));
								institutes = on ? institutes.filter((r) => !ins.raws.includes(r)) : [...new Set([...institutes, ...ins.raws])];
							}} /> {ins.name} <small class="pl-sub">({ins.count})</small></label>
						{/each}
						<span class="pl-sub">{institutes.length ? 'Selected institutes only' : 'All institutes'}</span>
					</div>
				</div>
			{/if}
			<div class="row">
				<span class="label">Rules</span>
				<div class="checks">
					<label><input type="checkbox" bind:checked={excludeUsed} /> Skip questions already used in another model paper</label>
					{#if usedCount > 0}
						<span class="pl-sub">({usedCount} used so far)</span>
						<button type="button" class="link" onclick={forgetUsed}>Forget used</button>
					{/if}
					<label><input type="checkbox" bind:checked={requireKey} /> Only questions with an answer key</label>
				</div>
			</div>
		</section>

		<section class="card">
			<h2>3 · Questions available for each section</h2>
			<ul class="avail">
				{#each pattern.sections as s (s.id)}
					{@const a = avail[s.id]}
					<li class:low={a !== undefined && a < s.units}>
						<span>Section {s.id.replace('S', '')} · {s.typeName}</span>
						<span>needs {s.units}</span>
						<b>{a === undefined ? '…' : `${a.toLocaleString()} available`}</b>
					</li>
				{/each}
			</ul>
			{#if shortSecs.length}
				<p class="verify warn">⚠ Some sections have too few questions with these choices. Loosen the filters, or fill those sections by hand afterwards.</p>
			{/if}
		</section>

		{/if}

		<section class="card">
			<h2>{mode === 'auto' ? '4' : '2'} · Create</h2>
			<div class="row">
				<span class="label">Title</span>
				<input class="text" bind:value={title} placeholder={`${pattern.label} (Physics) — model paper`} aria-label="Title" />
			</div>
			<div class="row">
				<span class="label">Time (minutes)</span>
				<input class="num" inputmode="numeric" value={minutes} oninput={(e) => (minutes = e.currentTarget.value.replace(/\D/g, ''))} aria-label="Time in minutes" />
				<span class="pl-sub">The full official paper is 3 hours for Physics, Chemistry and Mathematics; Physics alone is about 60 minutes.</span>
			</div>
			<div class="go">
				<button type="button" class="pl-btn pl-btn-primary" disabled={busy} onclick={() => create(mode)}>{busy ? 'Working…' : mode === 'auto' ? 'Generate paper' : 'Create manual paper'}</button>
				<span class="pl-sub">{mode === 'auto' ? 'Auto picks random questions section by section, spread over chapters. You can swap any question afterwards.' : 'Create an empty paper, then choose questions for each section by hand.'}</span>
			</div>
			{#if msg}<p class={msg.ok ? 'pl-sub' : 'pl-error'} role="status">{msg.text}</p>{/if}
		</section>
	{/if}
	{/if}
	</div>
</div>

<style>
	.mode-picker {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
	}
	.mode-picker button {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 24px;
	}
	.mode-picker button.chosen {
		background: var(--pl-seal);
		border-color: var(--pl-seal);
		color: #fff;
	}
	.setup {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.mp {
		max-width: 980px;
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding-bottom: 48px;
	}
	.head h1 {
		font-size: 2rem;
		margin: 2px 0 6px;
	}
	.eyebrow {
		margin: 0;
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: var(--pl-ink-soft);
	}
	.resume {
		margin: 10px 0 0;
		padding: 8px 12px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-surface);
		font-size: 0.85rem;
	}
	.card {
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-lg);
		padding: 18px 20px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.card h2 {
		font-size: 0.8rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		margin: 0;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
	.label {
		width: 110px;
		font-size: 0.82rem;
		color: var(--pl-ink-soft);
		flex: none;
	}
	select,
	.text,
	.num {
		min-height: 36px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-paper);
		color: var(--pl-ink);
		padding: 0 10px;
		font: inherit;
	}
	.text {
		flex: 1;
		min-width: 240px;
	}
	.num {
		width: 90px;
	}
	.seg {
		display: inline-flex;
		gap: 2px;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		padding: 3px;
	}
	.seg button {
		border: none;
		background: none;
		border-radius: var(--pl-radius-pill);
		padding: 5px 14px;
		min-height: 0;
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
	}
	.seg button.on {
		background: var(--pl-surface);
		color: var(--pl-ink);
		box-shadow: var(--pl-shadow-sm);
	}
	.preview {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		padding: 12px 14px;
	}
	.preview header {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	.badge {
		font-size: 0.7rem;
		font-weight: 700;
		padding: 2px 9px;
		border-radius: 999px;
	}
	.badge.ok {
		background: var(--pl-pine-soft);
		color: var(--pl-pine, #234e3e);
	}
	.badge.warn {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.verify {
		margin: 8px 0;
		padding: 8px 12px;
		border-radius: var(--pl-radius-sm);
		font-size: 0.82rem;
	}
	.verify.ok {
		background: var(--pl-pine-soft);
	}
	.verify.warn {
		background: var(--pl-ochre-soft);
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}
	th,
	td {
		text-align: left;
		padding: 7px 8px;
		border-bottom: 1px solid var(--pl-line);
	}
	th {
		font-size: 0.7rem;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--pl-ink-soft);
	}
	tfoot td {
		font-weight: 700;
		border-bottom: none;
	}
	small {
		color: var(--pl-ink-soft);
	}
	.scope-head {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 6px;
	}
	.link {
		border: none;
		background: none;
		color: var(--pl-seal);
		min-height: 0;
		padding: 0;
		font-size: 0.8rem;
		text-decoration: underline;
	}
	.module {
		margin: 8px 0 12px;
	}
	.mod {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		background: none;
		color: var(--pl-ink);
		min-height: 0;
		padding: 4px 12px;
		font-size: 0.75rem;
		font-weight: 700;
		letter-spacing: 0.04em;
	}
	.mod.on {
		background: var(--pl-seal);
		border-color: var(--pl-seal);
		color: #fff;
	}
	.chapters {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
		gap: 8px;
		margin-top: 8px;
	}
	.chapter {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		padding: 8px 10px;
		font-size: 0.85rem;
	}
	.chapter label {
		display: flex;
		gap: 8px;
		align-items: center;
	}
	.chapter summary {
		cursor: pointer;
		font-size: 0.74rem;
		color: var(--pl-ink-soft);
		margin-top: 4px;
	}
	.week {
		margin: 8px 0 2px;
		font-size: 0.7rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--pl-ink-soft);
	}
	.sub {
		display: flex;
		gap: 8px;
		font-size: 0.78rem;
		padding: 2px 0;
	}
	.diff {
		display: grid;
		gap: 6px;
		padding-left: 122px;
	}
	.slider {
		display: grid;
		grid-template-columns: 70px 1fr 24px;
		align-items: center;
		gap: 10px;
		max-width: 420px;
		font-size: 0.85rem;
	}
	.checks {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 18px;
		align-items: center;
		font-size: 0.85rem;
	}
	.checks label {
		display: inline-flex;
		gap: 6px;
		align-items: center;
	}
	.avail {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.avail li {
		display: grid;
		grid-template-columns: 1fr 110px 150px;
		padding: 8px 0;
		border-bottom: 1px solid var(--pl-line);
		font-size: 0.88rem;
	}
	.avail li b {
		text-align: right;
	}
	.avail li.low b {
		color: var(--pl-seal);
	}
	.go {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
</style>
