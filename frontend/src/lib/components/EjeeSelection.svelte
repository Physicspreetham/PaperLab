<script>
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { pushState } from '$app/navigation';
	import { createViewerFullscreen, createWheelPager, sortByImportOrder } from '$lib/ejeeGallery.js';
	import EjeeHoverPreview from './EjeeHoverPreview.svelte';
	import { api } from '$lib/api.js';
	import EjeeImageViewer from './EjeeImageViewer.svelte';
	import EjeeImportCartButton from './EjeeImportCartButton.svelte';
	let { aiReady = false, onQueued = async () => {}, appendPaperId = null } = $props();
	let destination = $state(null);
	let facets = $state(null), rows = $state([]), total = $state(0), offset = $state(0);
	let busy = $state(false), loading = $state(true), error = $state(''), message = $state('');
	let sourceFind = $state(''), sources = $state([]), moduleId = $state(''), chapterId = $state(''), weekId = $state(''), topicIds = $state([]);
	let q = $state(''), model = $state(''), level = $state(''), section = $state(''), exam = $state(''), year = $state(''), status = $state('');
	let fav = $state(false), altered = $state(false), chosen = $state({}), name = $state(''), openPreview = $state(null);
	let appliedFilters = $state({}), existingPaper = $state(null);
	let requestVersion = 0, viewerGeneration = 0, historyOwned = false, closeRequested = false, fullscreen;
	let lastViewed = $state(null);
	const thumbnails = new Map();
	function thumbnailAnchor(node,id) { thumbnails.set(id,node); return {destroy(){thumbnails.delete(id);}}; }
	function openImage(id) {
		if(closeRequested) return;
		viewerGeneration++; openPreview=id; lastViewed=id;
		fullscreen?.enter();
		historyOwned=true; pushState('', {...$page.state,ejeeViewer:true});
	}
	function requestClose() {
		if(closeRequested) return; closeRequested=true;
		if(historyOwned && $page.state.ejeeViewer) window.history.back();
		else finishClose();
	}
	async function finishClose() {
		closeRequested=true;
		const id=openPreview; viewerGeneration++; historyOwned=false;
		lastViewed=id; openPreview=null; loading=false;
		await fullscreen?.leave(); await tick();
		await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
		const card=thumbnails.get(id);
		card?.querySelector('.thumbnail')?.focus({preventScroll:true});
		card?.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
		closeRequested=false;
	}
	$effect(()=>{const viewerState=$page.state.ejeeViewer;if(historyOwned && !viewerState) finishClose();});
	// Hover preview: a large non-modal panel beside the grid; wheel/arrow keys slide through questions.
	let hoverId = $state(null), hoverSide = $state('right');
	let hoverTimer, leaveTimer, suppressUntil = 0;
	const hoverPager = createWheelPager();
	const hoverIndex = $derived(rows.findIndex(r => r.id === hoverId));
	const hoverRow = $derived(openPreview || hoverIndex < 0 ? null : rows[hoverIndex]);
	function hoverEnter(row,node) {
		if (!row.ready || openPreview || performance.now() < suppressUntil) return;
		clearTimeout(leaveTimer); clearTimeout(hoverTimer);
		const show = () => {
			if (hoverId === null) { const r = node.getBoundingClientRect(); hoverSide = r.left + r.width/2 < window.innerWidth/2 ? 'right' : 'left'; }
			hoverId = row.id;
		};
		if (hoverId !== null) show(); else hoverTimer = setTimeout(show,150);
	}
	function hoverKeep() { clearTimeout(leaveTimer); }
	function hoverLeave() { clearTimeout(hoverTimer); clearTimeout(leaveTimer); leaveTimer = setTimeout(() => hoverId = null,250); }
	function hoverClose() { clearTimeout(hoverTimer); clearTimeout(leaveTimer); hoverId = null; }
	async function hoverMove(step) {
		let next = hoverIndex + step;
		if (next >= rows.length && rows.length < total) { await loadMore(); next = hoverIndex + step; }
		if (next < 0 || next >= rows.length) return;
		if (rows.length - next < 6) loadMore();
		hoverId = rows[next].id;
		suppressUntil = performance.now() + 400; // page scroll below must not re-trigger hover on another card
		const rect = thumbnails.get(hoverId)?.getBoundingClientRect();
		if (rect && (rect.top < 0 || rect.bottom > window.innerHeight)) thumbnails.get(hoverId).scrollIntoView({block:'center',behavior:'instant'});
	}
	function hoverWheel(event) {
		if (event.ctrlKey || event.metaKey) return;
		event.preventDefault();
		const step = hoverPager(event,performance.now());
		if (step) hoverMove(step);
	}
	function hoverFullscreen() { const id = hoverId; hoverClose(); if (id) openImage(id); }
	function thumbWheel(node) {
		const handler = event => { if (hoverId !== null && !openPreview) hoverWheel(event); };
		node.addEventListener('wheel',handler,{passive:false});
		return {destroy(){node.removeEventListener('wheel',handler);}};
	}
	function hoverKeydown(event) {
		if (hoverId === null || openPreview || event.ctrlKey || event.metaKey || event.altKey) return;
		if (['INPUT','TEXTAREA','SELECT'].includes(event.target?.tagName)) return;
		const row = hoverRow;
		if (event.key === 'ArrowRight') { event.preventDefault(); hoverMove(1); }
		else if (event.key === 'ArrowLeft') { event.preventDefault(); hoverMove(-1); }
		else if (event.key === 'Escape') { hoverClose(); }
		else if ((event.key === 'f' || event.key === 'F') && row) { event.preventDefault(); hoverFullscreen(); }
		else if ((event.key === 'c' || event.key === 'C') && row && !cannotSelect(row)) { event.preventDefault(); toggle(row,!chosen[row.selection_key]); }
	}
	$effect(() => { if (openPreview) hoverClose(); });
	const PAGE = 30;
	let reclassify = $state(false);
	let contentMode = $state('full');
	const count = $derived(Object.keys(chosen).length);
	const chosenOrdered = $derived(sortByImportOrder(Object.values(chosen),facets?.nodes || []));
	const previewRow = $derived(rows.find(r => r.id === openPreview));
	const previewIndex = $derived(rows.findIndex(r => r.id === openPreview));
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
	function toggleTopic(id, checked) { topicIds = checked ? [...topicIds, id] : topicIds.filter(value => value !== id); }
	function filters() { return { source:sources, node_ids:topicIds, node_id:weekId || chapterId || moduleId || null,
		q, qtype:model, difficulty:level, type:section, exam, year, status, fav, altered }; }
	async function search(next = 0,apply = false,previewEdge = null) {
		const viewerRequest=viewerGeneration;
		const version = ++requestVersion; loading = true; error = '';
		const selectedFilters = apply ? filters() : appliedFilters;
		try {
			const data = await api.searchEjeeQuestions({filters:selectedFilters,node_ids:selectedFilters.node_ids,offset:next,limit:PAGE});
			if (version !== requestVersion || (previewEdge && viewerRequest!==viewerGeneration)) return;
			if (data.source_token !== facets.source_token) throw new Error('The EJEE source changed. Reload this page before selecting more questions.');
			if (selectedFilters.node_ids?.length && !selectedFilters.node_ids.every(id => data.applied_node_ids?.includes(id))) {
				rows = []; total = 0; offset = 0; openPreview = null;
				appliedFilters = selectedFilters;
				throw new Error('The running PaperLab backend has not loaded the subtopic filter update. Reopen PaperLab from its launcher, then apply the filters again.');
			}
			if(apply) lastViewed=null;
			rows = data.items; total = data.total; offset = next; appliedFilters = selectedFilters; openPreview = previewEdge === 'first' ? data.items[0]?.id : previewEdge === 'last' ? data.items.at(-1)?.id : null;
		} catch(e) { if(version === requestVersion) error = e.message; }
		finally { if(version === requestVersion) loading = false; }
	}
	async function movePreview(step) {
		if (loading) return;
		const next = previewIndex + step;
		if (next >= rows.length && rows.length < total) await loadMore();
		if (next >= 0 && next < rows.length) openPreview = rows[next].id;
		else return;
		if (rows.length - next < 6) loadMore();
	}
	// Continuous scrolling: append the next batch instead of replacing the page.
	let loadingMore = $state(false), sentinel = null;
	async function loadMore() {
		if (loading || loadingMore || !facets || rows.length >= total) return;
		loadingMore = true; const version = requestVersion;
		try {
			const data = await api.searchEjeeQuestions({filters:appliedFilters,node_ids:appliedFilters.node_ids,offset:rows.length,limit:PAGE});
			if (version !== requestVersion) return;
			if (data.source_token !== facets.source_token) throw new Error('The EJEE source changed. Reload this page before selecting more questions.');
			const seen = new Set(rows.map(r => r.id));
			rows = [...rows, ...data.items.filter(r => !seen.has(r.id))]; total = data.total;
		} catch(e) { if (version === requestVersion) error = e.message; }
		finally { loadingMore = false; requestAnimationFrame(checkSentinel); }
	}
	function checkSentinel() { if (sentinel && sentinel.getBoundingClientRect().top < window.innerHeight + 700) loadMore(); }
	function sentinelAction(node) {
		sentinel = node;
		const io = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) loadMore(); }, {rootMargin:'700px'});
		io.observe(node);
		return {destroy(){io.disconnect(); sentinel = null;}};
	}
	function cannotSelect(row) { return !row.ready || busy || (count >= facets.max_selection && !chosen[row.selection_key]); }
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
	async function selectAllMatching() {
		busy = true; error = ''; message = '';
		try {
			const next = {...chosen};
			for (let from = 0; from < total && Object.keys(next).length < facets.max_selection; from += 100) {
				const data = await api.searchEjeeQuestions({filters:appliedFilters,node_ids:appliedFilters.node_ids,offset:from,limit:100});
				if (data.source_token !== facets.source_token) throw new Error('The EJEE source changed. Reload this page before selecting more questions.');
				for (const row of data.items) if (row.ready && Object.keys(next).length < facets.max_selection) next[row.selection_key] = row;
			}
			chosen = next; existingPaper = null;
			if (total > facets.max_selection) message = `Selection is limited to ${facets.max_selection} questions; the first ${facets.max_selection} eligible matches were added.`;
		} catch(e) { error = e.message; } finally { busy = false; }
	}
	function clearFilters() {
		sources=[];moduleId='';chapterId='';weekId='';topicIds=[];q='';model='';level='';section='';exam='';year='';status='';fav=false;altered=false;
		search(0,true);
	}
	async function start() {
		busy = true; error = ''; message = ''; existingPaper = null;
		try {
			const selection = {resource_ids:Object.values(chosen).map(r => r.id),
				source_token:facets.source_token,filters:appliedFilters,tagging_mode:reclassify ? 'paperlab' : 'source',
				content_mode:contentMode};
			const result = appendPaperId
				? await api.appendEjeeSelection(appendPaperId, selection)
				: await api.importEjeeSelection({name:name.trim(), ...selection});
			if (result.already_imported) {
				existingPaper = result.paper_id; message = appendPaperId
					? 'All selected questions are already in this collection.'
					: 'These exact questions are already imported. No additional conversion was started.';
			} else {
				message = ['failed', 'interrupted'].includes(result.status)
					? 'This batch already exists. Use Resume import in Import progress to continue.'
					: appendPaperId
					? `${result.total} new questions queued for "${result.chapter}".`
					: `${result.total} selected questions queued as "${result.chapter}". Mapped solutions stay attached. Follow progress below.`;
				if (result.skipped) message += ` ${result.skipped} already in the collection.`;
				chosen = {}; await onQueued();
			}
		} catch(e) { error = e.message; } finally { busy = false; }
	}
	onMount(() => {
		let active = true;
		window.addEventListener('keydown',hoverKeydown);
		fullscreen=createViewerFullscreen(document);
		const exited=()=>{if(openPreview && fullscreen.owns() && !document.fullscreenElement)requestClose();};
		document.addEventListener('fullscreenchange',exited);
		(async () => {
			try {
				const [result, paper] = await Promise.all([
					api.getEjeeFilters(), appendPaperId ? api.getPaper(appendPaperId, 'ejee') : null
				]);
				if(!active) return;
				facets = result; destination = paper;
				await search(0,true);
			} catch(e) { if(active) {error = e.message; loading = false;} }
		})();
		return () => { active = false; requestVersion++; viewerGeneration++; document.removeEventListener('fullscreenchange',exited); window.removeEventListener('keydown',hoverKeydown); clearTimeout(hoverTimer); clearTimeout(leaveTimer); fullscreen.leave(); };
	});
</script>

<section class="pl-card picker">
	<h2>{appendPaperId ? 'Add more questions' : 'Select questions from EJEE'}</h2>
	{#if appendPaperId}
		{#if destination}<p>Adding to <a href={`/ejee/library/${appendPaperId}`}>{destination.title}</a>. Select the additional questions below.</p>{/if}
	{:else}
		<p>Use EJEE's source and syllabus filters to select questions across pages and save them as a named collection.</p>
	{/if}
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
				<label>Module<select bind:value={moduleId} onchange={() => {chapterId='';weekId='';topicIds=[];}}><option value="">All modules</option>{#each modules as n}<option value={String(n.id)}>{n.name}</option>{/each}</select></label>
				<label>Chapter<select bind:value={chapterId} onchange={() => {weekId='';topicIds=[];}}><option value="">All chapters</option>{#each chapters as n}<option value={String(n.id)}>{n.name}</option>{/each}</select></label>
				<label>Week / unit<select bind:value={weekId} onchange={() => topicIds=[]}><option value="">All weeks</option>{#each weeks as n}<option value={String(n.id)}>{n.name}</option>{/each}</select></label>
				<details class="subtopics">
					<summary>Subtopics — {topicIds.length ? `${topicIds.length} selected` : 'All subtopics'}</summary>
					<div class="source-list">
						{#each topics as n (n.id)}
							<label><input type="checkbox" checked={topicIds.includes(n.id)} onchange={e => toggleTopic(n.id,e.currentTarget.checked)} /> <span>{n.name}</span></label>
						{/each}
						{#if !topics.length}<p>No subtopics in this selection.</p>{/if}
					</div>
					<button type="button" class="pl-btn" disabled={!topicIds.length} onclick={() => topicIds=[]}>Clear subtopics</button>
				</details>
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
		<div class="selection-bar"><strong>Import cart · {count} questions selected</strong><button class="pl-btn" disabled={!rows.length || loading} onclick={selectPage}>Select eligible questions on this page</button><button class="pl-btn" disabled={!rows.length || loading || busy || total <= rows.length} onclick={selectAllMatching}>Select all {Math.min(total, facets.max_selection).toLocaleString()} matching</button><button class="pl-btn" disabled={!count} onclick={() => chosen={}}>Clear selection</button></div>
		<p class="muted">Hover a thumbnail for a large preview; scroll the mouse wheel or use ← → to slide questions (C adds to cart, F opens fullscreen). Click a thumbnail for the full viewer.</p>
		<p class="muted">{total.toLocaleString()} matching question cards · {rows.length.toLocaleString()} loaded — more load automatically as you scroll. Selections stay when you change filters or pages; linked continuation cards count as one question.</p>
		<div class="results" aria-busy={loading}>
			{#each rows as row (row.id)}
				<article class:chosen={!!chosen[row.selection_key]} class:last-viewed={lastViewed===row.id} class:hovered={hoverId===row.id} use:thumbnailAnchor={row.id}>
					<div class="card-actions"><label class="question-choice"><input type="checkbox" aria-label={`Select ${row.title}`} checked={!!chosen[row.selection_key]} disabled={cannotSelect(row)} onchange={e => toggle(row,e.currentTarget.checked)} /><strong>{row.title}</strong></label>
						<EjeeImportCartButton selected={!!chosen[row.selection_key]} disabled={cannotSelect(row)} title={row.title} onToggle={() => toggle(row,!chosen[row.selection_key])} /></div>
					<button class="thumbnail" type="button" disabled={!row.ready} aria-label={`Open full image for ${row.title}`} use:thumbWheel onmouseenter={e => hoverEnter(row,e.currentTarget)} onmouseleave={hoverLeave} onclick={() => openImage(row.id)}>
						{#if row.ready}<img src={`/api/ejee/questions/${row.id}/preview?size=thumbnail&source_token=${encodeURIComponent(facets.source_token)}`} alt={`Thumbnail of ${row.title}`} loading="lazy" decoding="async" />{:else}<span>Image unavailable</span>{/if}
					</button>
					{#if lastViewed===row.id}<span class="last-viewed-label">Last viewed</span>{/if}
					<p class="card-source">{row.source || 'Unspecified source'}</p>
					{#if row.imported_in}<p class="imported">✓ Already in <a href={`/ejee/library/${row.imported_in.paper_id}`}>{row.imported_in.title}</a></p>{/if}
					<p class="path">{row.path}</p><p class="meta">{row.qtype || 'Model not tagged'} · {row.difficulty || 'Not graded'} · {row.solution_parts} solution parts</p>
					{#if row.issue}<p class="pl-error">{row.issue}</p>{/if}
				</article>
			{/each}
			{#if !loading && !rows.length}<p>No questions match these filters.</p>{/if}
		</div>
		<div use:sentinelAction class="more" aria-live="polite">{#if loadingMore}Loading more questions…{:else if rows.length && rows.length >= total}All {total.toLocaleString()} questions loaded.{/if}</div>
		{#if count}
			<details class="basket"><summary>Review import cart ({count})</summary>{#each chosenOrdered as row (row.selection_key)}<div class="basket-row"><span>{row.title} — {row.source}</span><button class="pl-btn" onclick={() => toggle(row,false)}>Remove</button></div>{/each}</details>
		{/if}
		<div class="collection">
			{#if !appendPaperId}<label>Collection name<input class="pl-input" bind:value={name} maxlength="180" placeholder="e.g. Electrostatics - selected numerical questions" /></label>{/if}
			<label>Transcribe
				<select class="pl-input" bind:value={contentMode} disabled={busy}>
					<option value="key">Questions + Key</option>
					<option value="full">Questions + Key + Solutions</option>
				</select>
			</label>
			<label><input type="checkbox" bind:checked={reclassify} /> Reclassify with PaperLab AI (optional; additional API usage)</label>
			<small>Original EJEE chapter, topics, tags and difficulty are kept by default.</small>
			{#if appendPaperId}<p>Questions already in this collection are skipped. New questions are added after processing finishes.</p>{/if}
			<button class="pl-btn pl-btn-primary" disabled={!count || (appendPaperId ? !destination : !name.trim()) || busy || !aiReady} onclick={start}>{busy ? 'Preparing selection…' : `Process ${count} selected question${count===1 ? '' : 's'}${appendPaperId ? ' and add to collection' : ''}`}</button>
			{#if !aiReady}<p class="pl-error">Configure the existing PaperLab Meta key to enable conversion.</p>{/if}
			{#if message}<p role="status">{message}</p>{/if}
			{#if existingPaper}<a href={`/ejee/library/${existingPaper}`}>Open existing collection →</a>{/if}
		</div>
	{/if}
</section>

{#if hoverRow && facets}
	<EjeeHoverPreview row={hoverRow} index={offset+hoverIndex} {total} sourceToken={facets.source_token}
		selected={!!chosen[hoverRow.selection_key]} disabled={cannotSelect(hoverRow)} neighbours={[rows[hoverIndex+1],rows[hoverIndex-1]]}
		onToggle={checked => toggle(hoverRow,checked)} onFullscreen={hoverFullscreen} onClose={hoverClose}
		onWheel={hoverWheel} onEnter={hoverKeep} onLeave={hoverLeave} />
{/if}

{#if previewRow}
	<EjeeImageViewer row={previewRow} index={offset+previewIndex} {total} sourceToken={facets.source_token} selected={!!chosen[previewRow.selection_key]} disabled={cannotSelect(previewRow)} navigating={loading || loadingMore} onToggle={checked => toggle(previewRow,checked)} onClose={requestClose} onMove={movePreview} onFullscreen={() => fullscreen?.enter()} />
{/if}

<style>
	.subtopics { border: 1px solid var(--pl-line); border-radius: 8px; padding: 10px; }
	.subtopics summary { cursor: pointer; }
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
	.results { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr)); gap:16px; }
	article { border:1px solid var(--pl-line); border-radius:10px; padding:16px; }
	article.last-viewed { outline:3px solid var(--pl-accent, var(--pl-seal)); outline-offset:3px; box-shadow:0 0 0 6px var(--pl-seal-soft); scroll-margin:80px 0; }
	.last-viewed-label { display:inline-block; margin-top:10px; padding:3px 8px; border-radius:5px; font-size:.75rem; font-weight:700; color:var(--pl-seal); background:var(--pl-seal-soft); }
	.more { min-height:40px; text-align:center; opacity:.7; padding:14px 0; }
	article.hovered { outline:2px solid var(--pl-seal); outline-offset:2px; }
	article.chosen { border-color:var(--pl-accent); background:var(--pl-surface); }
	.question-choice { display:flex; align-items:flex-start; gap:12px; cursor:pointer; }
	.question-choice input { margin-top:5px; }
	small { display:block; opacity:.75; margin-top:4px; }
	.path,.meta,.muted { font-size:.86rem; opacity:.75; line-height:1.6; }
	.card-actions { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
	.question-choice strong { font-size:.95rem; overflow-wrap:anywhere; }
	.thumbnail { display:flex; align-items:center; justify-content:center; width:100%; height:210px; padding:10px; margin-top:12px; border:1px solid var(--pl-line); border-radius:8px; background:white; cursor:zoom-in; }
	.thumbnail img { display:block; max-width:100%; max-height:100%; object-fit:contain; }
	.thumbnail:disabled { cursor:default; opacity:.5; }
	.imported { font-size:.8rem; margin:4px 0; color:var(--pl-seal); }
	.card-source { font-size:.85rem; font-weight:600; overflow-wrap:anywhere; }
	.path { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
	.collection { border-top:1px solid var(--pl-line); padding-top:20px; margin-top:24px; }
	.basket-row { display:flex; justify-content:space-between; gap:12px; align-items:center; padding:10px 0; }
	@media(max-width:650px) { .filter-grid { grid-template-columns:1fr; } .picker { padding:16px; } .filter-toggles,.filter-buttons { width:100%; } .selection-bar .pl-btn { width:100%; } .basket-row { align-items:flex-start; } .basket-row span { min-width:0; overflow-wrap:anywhere; } .basket-row .pl-btn { flex-shrink:0; } }
</style>
