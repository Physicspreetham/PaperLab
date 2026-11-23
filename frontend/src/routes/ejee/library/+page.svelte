<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	let papers = $state([]), loading = $state(true), error = $state('');
	const books = $derived([...new Set(papers.map(p => p.book))]);
	let orderError = $state('');
	// Merge: tick two or more collections, name the new one, optionally remove the originals.
	let picked = $state([]), mergeTitle = $state(''), removeOriginals = $state(false), merging = $state(false), mergeError = $state(''), mergeResult = $state(null);
	const pickedPapers = $derived(papers.filter(p => picked.includes(p.id)));
	const pickedQuestions = $derived(pickedPapers.reduce((n, p) => n + p.questions, 0));
	function pick(id, checked) { picked = checked ? [...picked, id] : picked.filter(v => v !== id); mergeResult = null; }
	let removing = $state(null), removeError = $state('');
	async function removeCollection(paper) {
		if (!window.confirm(`Delete "${paper.title}" (${paper.questions} questions)? Its files are kept in the library trash.`)) return;
		removing = paper.id; removeError = '';
		try {
			await api.deleteEjeeCollection(paper.id);
			papers = papers.filter(p => p.id !== paper.id);
			picked = picked.filter(id => id !== paper.id);
		} catch(e) { removeError = `Could not delete "${paper.title}": ${e.message}`; } finally { removing = null; }
	}
	async function merge() {
		const note = removeOriginals ? ' The original collections will be removed (kept in the library trash).' : ' The original collections are kept.';
		if (!window.confirm(`Merge ${picked.length} collections (${pickedQuestions} questions) into "${mergeTitle.trim()}"?${note}`)) return;
		merging = true; mergeError = ''; mergeResult = null;
		try {
			const result = await api.mergeEjeeCollections(picked, mergeTitle.trim(), removeOriginals);
			mergeResult = {...result, title: mergeTitle.trim()};
			picked = []; mergeTitle = ''; removeOriginals = false;
			papers = await api.getImportedTextbooks();
		} catch(e) { mergeError = e.message; } finally { merging = false; }
	}
	// Move within the same book heading; the full order is saved on the server.
	async function move(paper, step) {
		const group = papers.filter(p => p.book === paper.book);
		const target = group[group.indexOf(paper) + step];
		if (!target) return;
		const previous = papers, next = [...papers];
		const a = next.indexOf(paper), b = next.indexOf(target);
		[next[a], next[b]] = [next[b], next[a]];
		papers = next; orderError = '';
		try { await api.reorderEjeeCollections(next.map(p => p.id)); }
		catch(e) { papers = previous; orderError = e.message; }
	}
	onMount(async () => {
		try { papers = await api.getImportedTextbooks(); }
		catch(e) { error = e.message; }
		finally { loading = false; }
	});
</script>

<svelte:head><title>EJEE collections - PaperLab</title></svelte:head>
<h1>EJEE collections</h1>
<p class="pl-sub">Selected EJEE question collections and textbook chapters, kept in their own library. These are separate from the question-paper Archive.</p>
<p><a class="pl-btn pl-btn-primary" href="/ejee">Select questions from EJEE →</a></p>
{#if orderError}<p class="pl-error" role="alert">{orderError}</p>{/if}
{#if $role === 'archivist' && picked.length}
	<form class="pl-card merge" onsubmit={e => {e.preventDefault(); merge();}}>
		<strong>{picked.length} selected · {pickedQuestions} questions</strong>
		{#if picked.length < 2}<span class="pl-sub">Tick at least two collections to merge them.</span>{/if}
		<label>New collection title<input class="pl-input" bind:value={mergeTitle} maxlength="180" placeholder="e.g. Electrostatics - all questions" required /></label>
		<label class="check"><input type="checkbox" bind:checked={removeOriginals} /> Remove the original collections after merging</label>
		<p class="pl-sub">Questions are ordered by chapter and subtopic, then source, and renumbered from 1. Questions that appear in more than one selected collection are kept once.</p>
		<div class="merge-actions">
			<button class="pl-btn pl-btn-primary" disabled={merging || picked.length < 2 || !mergeTitle.trim()}>{merging ? 'Merging…' : `Merge ${picked.length} collections`}</button>
			<button type="button" class="pl-btn" disabled={merging} onclick={() => picked = []}>Clear selection</button>
		</div>
	</form>
{/if}
{#if removeError}<p class="pl-error" role="alert">{removeError}</p>{/if}
{#if mergeError}<p class="pl-error" role="alert">{mergeError}</p>{/if}
{#if mergeResult}<p role="status">Created "{mergeResult.title}" with {mergeResult.questions} questions{mergeResult.skipped_duplicates ? ` (${mergeResult.skipped_duplicates} duplicates skipped)` : ''}{mergeResult.removed ? ` · ${mergeResult.removed.length} originals removed` : ''}. <a href={`/ejee/library/${mergeResult.paper_id}`}>Open it →</a></p>{/if}
{#if loading}<p role="status">Loading EJEE collections…</p>{/if}
{#if error}<p class="pl-error" role="alert">{error}</p>{/if}
{#if !loading && !error && !papers.length}
	<div class="pl-card empty"><h2>No imported collections yet</h2><p>Filter and select questions in EJEE Import. Completed imports will appear here.</p></div>
{/if}
{#each books as book}
	<section class="pl-card book"><h2>{book}</h2>
		{#each papers.filter(p => p.book === book) as paper, i (paper.id)}
			{@const group = papers.filter(p => p.book === book)}
			<div class="row">
				{#if $role === 'archivist'}
					<input type="checkbox" class="pick" aria-label={`Select ${paper.title} to merge`} checked={picked.includes(paper.id)} onchange={e => pick(paper.id, e.currentTarget.checked)} />
				{/if}
				<a class="chapter" href={`/ejee/library/${paper.id}`}>
					<strong>{paper.title?.replace(`${book} — `,'') || 'EJEE collection'}</strong>
					<span>{paper.questions} questions · Open collection →</span>
				</a>
				{#if $role === 'archivist'}
					<button type="button" class="pl-btn danger" disabled={removing === paper.id} aria-label={`Delete collection ${paper.title}`} onclick={() => removeCollection(paper)}>{removing === paper.id ? 'Deleting…' : 'Delete'}</button>
				{/if}
				{#if $role === 'archivist' && group.length > 1}
					<div class="order" role="group" aria-label={`Reorder ${paper.title}`}>
						<button type="button" class="pl-btn" disabled={i === 0} onclick={() => move(paper, -1)} aria-label="Move up" title="Move up">↑</button>
						<button type="button" class="pl-btn" disabled={i === group.length - 1} onclick={() => move(paper, 1)} aria-label="Move down" title="Move down">↓</button>
					</div>
				{/if}
			</div>
		{/each}
	</section>
{/each}

<style>
	.book,.empty { margin-top:22px; padding:24px; }
	h2 { margin:0 0 16px; }
	.row { display:flex; align-items:center; gap:12px; border-top:1px solid var(--pl-line); }
	.chapter { flex:1; min-width:0; display:flex; flex-direction:column; gap:8px; padding:18px 0; text-decoration:none; color:inherit; }
	.order { display:flex; gap:4px; flex-shrink:0; }
	.order .pl-btn { min-height:28px; min-width:30px; padding:2px 8px; font-size:.78rem; line-height:1.2; }
	.danger { flex:none; min-height:28px; padding:2px 10px; font-size:.78rem; line-height:1.2; color:var(--pl-seal); border-color:var(--pl-seal); }
	.pick { flex:none; width:14px; height:14px; min-height:14px; margin:0; }
	.merge { display:grid; gap:12px; margin:16px 0; padding:18px; }
	.merge label { display:grid; gap:6px; }
	.merge label.check { display:flex; align-items:center; gap:10px; }
	.merge-actions { display:flex; flex-wrap:wrap; gap:10px; }
	.chapter span { opacity:.7; font-size:.9rem; }
	.chapter:hover strong { text-decoration:underline; }
</style>
