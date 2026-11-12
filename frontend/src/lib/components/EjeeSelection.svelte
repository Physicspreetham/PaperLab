<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	let { aiReady = false, onQueued = async () => {} } = $props();
	let facets = $state(null), rows = $state([]), total = $state(0), offset = $state(0);
	let busy = $state(false), loading = $state(true), error = $state(''), message = $state('');
	let sourceFind = $state(''), sources = $state([]), moduleId = $state(''), chapterId = $state(''), weekId = $state(''), topicId = $state('');
	let q = $state(''), model = $state(''), level = $state(''), section = $state(''), exam = $state(''), year = $state(''), status = $state('');
	let fav = $state(false), altered = $state(false), chosen = $state({}), name = $state(''), openPreview = $state(null);
	let appliedFilters = $state({}), existingPaper = $state(null);
	let requestVersion = 0;
	const PAGE = 30;
	const count = $derived(Object.keys(chosen).length);
	const nodes = $derived(facets?.nodes || []);
	const modules = $derived(nodes.filter(n => n.level === 'module'));
	function below(id,parent) {
		if (!parent) return true;
		const visited = new Set();
		while(id && !visited.has(id)) {
			if (String(id) === String(parent)) return true;
			visited.add(id); id = nodes.find(n => n.id === id)?.parent_id;
		}
		return false;
	}
	const chapters = $derived(nodes.filter(n => n.level === 'chapter' && below(n.id,moduleId)));
	const weeks = $derived(nodes.filter(n => n.level === 'week' && below(n.id,chapterId || moduleId)));
	const topics = $derived(nodes.filter(n => ['topic','subtopic'].includes(n.level) && below(n.id,weekId || chapterId || moduleId)));
	const sourceOptions = $derived((facets?.source || []).filter(s => label(s.value).toLowerCase().includes(sourceFind.toLowerCase())));
	const typeLabels = {objective:'Objective',subjective:'Subjective',jmain:'PYQ Mains',jadv:'PYQ Advanced',olympiad:'Olympiad',pyq:'PYQ'};
	function label(value) { return value === '__none__' ? 'Not tagged' : value; }
	function sourceToggle(value,checked) { sources = checked ? [...new Set([...sources,value])] : sources.filter(v => v !== value); }
	function filters() { return { source:sources, node_id:topicId || weekId || chapterId || moduleId || null,
		q, qtype:model, difficulty:level, type:section, exam, year, status, fav, altered }; }
	async function search(next = 0,apply = false) {
		const version = ++requestVersion; loading = true; error = '';
		const selectedFilters = apply ? filters() : appliedFilters;
		try {
			const data = await api.searchEjeeQuestions({filters:selectedFilters,offset:next,limit:PAGE});
			if (version !== requestVersion) return;
			if (data.source_token !== facets.source_token) throw new Error('The EJEE source changed. Reload this page before selecting more questions.');
			rows = data.items; total = data.total; offset = next; appliedFilters = selectedFilters; openPreview = null;
		} catch(e) { if(version === requestVersion) error = e.message; }
		finally { if(version === requestVersion) loading = false; }
	}
	function toggle(row,checked) {
		const next = {...chosen};
		if (checked) next[row.selection_key] = row; else delete next[row.selection_key];
		chosen = next; existingPaper = null;
	}
	function selectPage() {
		const next = {...chosen};
		for (const row of rows) if (row.ready && Object.keys(next).length < facets.max_selection) next[row.selection_key] = row;
		chosen = next;
	}
	function clearFilters() {
		sources=[];moduleId='';chapterId='';weekId='';topicId='';q='';model='';level='';section='';exam='';year='';status='';fav=false;altered=false;
		search(0,true);
	}
	async function start() {
		busy = true; error = ''; message = ''; existingPaper = null;
		try {
			const result = await api.importEjeeSelection({name:name.trim(),resource_ids:Object.values(chosen).map(r => r.id),
				source_token:facets.source_token,filters:appliedFilters});
			if (result.already_imported) {
				existingPaper = result.paper_id; message = 'These exact questions are already imported. No additional conversion was started.';
			} else {
				message = `${result.total} selected questions queued as “${result.chapter}”. Mapped solutions stay attached. Follow progress below.`;
				chosen = {}; await onQueued();
			}
		} catch(e) { error = e.message; } finally { busy = false; }
	}
	onMount(() => {
		let active = true;
		(async () => {
			try {
				const result = await api.getEjeeFilters(); if(!active) return; facets = result;
				await search(0,true);
			} catch(e) { if(active) {error = e.message; loading = false;} }
		})();
		return () => { active = false; requestVersion++; };
	});
</script>

<section class="pl-card picker">
	<h2>Select questions from EJEE</h2>
	<p>Use EJEE's source and syllabus filters. Select individual questions across pages, then save the selection as one named collection. No textbook chapter mapping is required.</p>
	{#if error}<p class="pl-error" role="alert">{error}</p>{/if}
	{#if facets}
		<form onsubmit={e => {e.preventDefault(); search(0,true);}}>
			<details class="sources"><summary>Source — {sources.length ? `${sources.length} selected` : 'all sources'}</summary>
				<input class="pl-input" aria-label="Find EJEE source" type="search" bind:value={sourceFind} placeholder="Find a book, paper or source…" />
				<div class="source-list">{#each sourceOptions as option (option.value)}
					<label><input type="checkbox" checked={sources.includes(option.value)} onchange={e => sourceToggle(option.value,e.currentTarget.checked)} /><span>{label(option.value)}</span><small>({option.count})</small></label>
				{/each}</div>
				<button class="pl-btn" type="button" onclick={() => sources=[]}>Clear source filter</button>
			</details>
			<div class="filter-grid">
				<label>Module<select bind:value={moduleId} onchange={() => {chapterId='';weekId='';topicId='';}}><option value="">All modules</option>{#each modules as n}<option value={String(n.id)}>{n.name}</option>{/each}</select></label>
				<label>Chapter<select bind:value={chapterId} onchange={() => {weekId='';topicId='';}}><option value="">All chapters</option>{#each chapters as n}<option value={String(n.id)}>{n.name}</option>{/each}</select></label>
				<label>Week / unit<select bind:value={weekId} onchange={() => topicId=''}><option value="">All weeks</option>{#each weeks as n}<option value={String(n.id)}>{n.name}</option>{/each}</select></label>
				<label>Subtopic<select bind:value={topicId}><option value="">All subtopics</option>{#each topics as n}<option value={String(n.id)}>{n.name}</option>{/each}</select></label>
				<label>Model / question type<select bind:value={model}><option value="">All models</option>{#each facets.qtype as o}<option value={o.value}>{label(o.value)} ({o.count})</option>{/each}</select></label>
				<label>Level<select bind:value={level}><option value="">All levels</option>{#each facets.difficulty as o}<option value={o.value}>{label(o.value)}</option>{/each}</select></label>
				<label>Section<select bind:value={section}><option value="">All question sections</option>{#each facets.type as o}<option value={o.value}>{typeLabels[o.value] || label(o.value)}</option>{/each}</select></label>
				<label>Exam<select bind:value={exam}><option value="">All exams</option>{#each facets.exam as o}<option value={o.value}>{label(o.value)}</option>{/each}</select></label>
				<label>Year<select bind:value={year}><option value="">All years</option>{#each facets.year as o}<option value={o.value}>{label(o.value)}</option>{/each}</select></label>
				<label>Status<select bind:value={status}><option value="">All statuses</option>{#each facets.status as o}<option value={o.value}>{o.value === '__none__' ? 'Not attempted' : o.value}</option>{/each}</select></label>
			</div>
			<label class="search-label">Search question text / title<input class="pl-input" type="search" bind:value={q} maxlength="250" placeholder="Question words, title, tags…" /></label>
			<div class="actions filter-actions"><div class="filter-toggles"><label><input type="checkbox" bind:checked={fav} /> Favourites only</label><label><input type="checkbox" bind:checked={altered} /> Altered only</label></div>
				<div class="filter-buttons"><button class="pl-btn pl-btn-primary" disabled={loading}>Apply filters</button><button class="pl-btn" type="button" onclick={clearFilters}>Clear filters</button></div></div>
		</form>
	{/if}
	{#if loading}<p role="status">Reading EJEE questions…</p>{/if}
	{#if facets}
		<div class="selection-bar"><strong>{count} questions selected</strong><button class="pl-btn" disabled={!rows.length || loading} onclick={selectPage}>Select eligible questions on this page</button><button class="pl-btn" disabled={!count} onclick={() => chosen={}}>Clear selection</button></div>
		<p class="muted">{total.toLocaleString()} matching question cards · {rows.length ? offset+1 : 0}–{Math.min(offset+PAGE,total)} shown. Selections stay when you change filters or pages; linked continuation cards count as one question.</p>
		<div class="results" aria-busy={loading}>
			{#each rows as row (row.id)}
				<article class:chosen={!!chosen[row.selection_key]}>
					<label class="question-choice"><input type="checkbox" aria-label={`Select ${row.title}`} checked={!!chosen[row.selection_key]} disabled={!row.ready || busy || (count >= facets.max_selection && !chosen[row.selection_key])} onchange={e => toggle(row,e.currentTarget.checked)} />
						<span><strong>{row.title}</strong><small>{row.source || 'Unspecified source'}</small></span></label>
					<p class="path">{row.path}</p><p class="meta">{row.qtype || 'Model not tagged'} · {row.difficulty || 'Not graded'} · {row.solution_parts} solution image parts{row.answer ? ' · answer available' : ''}</p>
					{#if row.question}<p class="excerpt">{row.question}</p>{/if}
					{#if row.issue}<p class="pl-error">{row.issue}</p>{:else}
						<button class="pl-btn" onclick={() => openPreview = openPreview === row.id ? null : row.id}>{openPreview === row.id ? 'Hide image' : 'Preview question image'}</button>
						{#if openPreview === row.id}<img class="preview" src={`/api/ejee/questions/${row.id}/preview`} alt={`Source image for ${row.title}`} />{/if}
					{/if}
				</article>
			{/each}
			{#if !loading && !rows.length}<p>No questions match these filters.</p>{/if}
		</div>
		<div class="actions"><button class="pl-btn" disabled={loading || offset===0} onclick={() => search(Math.max(0,offset-PAGE))}>← Previous page</button><button class="pl-btn" disabled={loading || offset+PAGE>=total} onclick={() => search(offset+PAGE)}>Next page →</button></div>
		{#if count}
			<details class="basket"><summary>Review selected questions ({count})</summary>{#each Object.values(chosen) as row (row.selection_key)}<div class="basket-row"><span>{row.title} — {row.source}</span><button class="pl-btn" onclick={() => toggle(row,false)}>Remove</button></div>{/each}</details>
		{/if}
		<div class="collection"><label>Collection name<input class="pl-input" bind:value={name} maxlength="180" placeholder="e.g. Electrostatics — selected numerical questions" /></label>
			<p>Only your selected questions and their own mapped solutions will be converted. Diagrams and fresh PaperLab topic classification are included. The collection appears in the separate EJEE library, without changing the ordinary Archive.</p>
			<button class="pl-btn pl-btn-primary" disabled={!count || !name.trim() || busy || !aiReady} onclick={start}>{busy ? 'Preparing selection…' : `Process ${count} selected question${count===1 ? '' : 's'}`}</button>
			{#if !aiReady}<p class="pl-error">Configure the existing PaperLab Meta key to enable conversion.</p>{/if}
			{#if message}<p role="status">{message}</p>{/if}
			{#if existingPaper}<a href={`/ejee/library/${existingPaper}`}>Open existing collection →</a>{/if}
		</div>
	{/if}
</section>

<style>
	.picker { margin-top:22px; padding:22px; }
	h2 { margin:0 0 12px; }
	.sources,.basket { border:1px solid var(--pl-line); border-radius:10px; padding:14px; margin:18px 0; }
	summary { cursor:pointer; font-weight:600; line-height:1.5; text-align:left; }
	.source-list { max-height:240px; overflow:auto; margin:12px 0; }
	.source-list label { display:grid; grid-template-columns:18px minmax(0,1fr) auto; align-items:start; gap:10px; padding:8px 0; line-height:1.5; }
	.source-list label span { overflow-wrap:anywhere; }
	.source-list small { margin:0; line-height:1.5; text-align:right; }
	input[type=checkbox] { box-sizing:border-box; width:16px; height:16px; min-height:16px; padding:0; flex:none; margin:3px 0 0; }
	.filter-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
	.filter-grid label,.search-label,.collection label { display:grid; gap:8px; min-width:0; align-content:start; line-height:1.5; }
	select,input:not([type=checkbox]) { box-sizing:border-box; color:inherit; background-color:var(--pl-surface); border:1px solid var(--pl-line); border-radius:8px; padding:11px 12px; min-width:0; width:100%; height:46px; font:inherit; line-height:1.4; text-align:left; }
	select { appearance:none; padding-right:38px; text-overflow:ellipsis; white-space:nowrap; overflow:hidden; background-image:linear-gradient(45deg,transparent 50%,currentColor 50%),linear-gradient(135deg,currentColor 50%,transparent 50%); background-position:calc(100% - 18px) 50%,calc(100% - 13px) 50%; background-size:5px 5px; background-repeat:no-repeat; }
	.pl-btn { display:inline-flex; justify-content:center; align-items:center; min-height:44px; box-sizing:border-box; padding:10px 16px; font:inherit; font-weight:600; line-height:1.4; text-align:center; white-space:normal; }
	.search-label { margin-top:14px; }
	.actions,.selection-bar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:18px 0; }
	.actions label { display:flex; gap:8px; align-items:center; line-height:1.5; }
	.actions label input { margin:0; }
	.filter-actions { justify-content:space-between; }
	.filter-toggles { display:flex; flex-wrap:wrap; gap:12px 20px; align-items:center; }
	.filter-buttons { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
	.selection-bar strong { flex:1 0 100%; }
	.results { display:grid; gap:14px; }
	article { border:1px solid var(--pl-line); border-radius:10px; padding:16px; }
	article.chosen { border-color:var(--pl-accent); background:var(--pl-surface); }
	.question-choice { display:flex; align-items:flex-start; gap:12px; cursor:pointer; }
	.question-choice input { margin-top:5px; }
	small { display:block; opacity:.75; margin-top:4px; }
	.path,.meta,.muted { font-size:.86rem; opacity:.75; line-height:1.6; }
	.excerpt { font-size:.9rem; max-height:110px; overflow:auto; }
	.preview { display:block; max-width:100%; height:auto; margin-top:14px; background:white; border-radius:6px; }
	.collection { border-top:1px solid var(--pl-line); padding-top:20px; margin-top:24px; }
	.basket-row { display:flex; justify-content:space-between; gap:12px; align-items:center; padding:10px 0; }
	@media(max-width:650px) { .filter-grid { grid-template-columns:1fr; } .picker { padding:16px; } .filter-toggles,.filter-buttons { width:100%; } .selection-bar .pl-btn { width:100%; } .basket-row { align-items:flex-start; } .basket-row span { min-width:0; overflow-wrap:anywhere; } .basket-row .pl-btn { flex-shrink:0; } }
</style>
