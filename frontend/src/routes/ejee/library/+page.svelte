<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	let papers = $state([]), loading = $state(true), error = $state('');
	const books = $derived([...new Set(papers.map(p => p.book))]);
	let orderError = $state('');
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
				<a class="chapter" href={`/ejee/library/${paper.id}`}>
					<strong>{paper.title?.replace(`${book} — `,'') || 'EJEE collection'}</strong>
					<span>{paper.questions} questions · Open collection →</span>
				</a>
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
	.order { display:flex; gap:6px; flex-shrink:0; }
	.order .pl-btn { min-height:38px; min-width:42px; padding:4px 10px; }
	.chapter span { opacity:.7; font-size:.9rem; }
	.chapter:hover strong { text-decoration:underline; }
</style>
