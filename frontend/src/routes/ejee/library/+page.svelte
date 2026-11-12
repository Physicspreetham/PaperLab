<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	let papers = $state([]), loading = $state(true), error = $state('');
	const books = $derived([...new Set(papers.map(p => p.book))]);
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
{#if loading}<p role="status">Loading EJEE collections…</p>{/if}
{#if error}<p class="pl-error" role="alert">{error}</p>{/if}
{#if !loading && !error && !papers.length}
	<div class="pl-card empty"><h2>No imported collections yet</h2><p>Filter and select questions in EJEE Import. Completed imports will appear here.</p></div>
{/if}
{#each books as book}
	<section class="pl-card book"><h2>{book}</h2>
		{#each papers.filter(p => p.book === book) as paper (paper.id)}
			<a class="chapter" href={`/ejee/library/${paper.id}`}>
				<strong>{paper.title?.replace(`${book} — `,'') || 'EJEE collection'}</strong>
				<span>{paper.questions} questions · Open collection →</span>
			</a>
		{/each}
	</section>
{/each}

<style>
	.book,.empty { margin-top:22px; padding:24px; }
	h2 { margin:0 0 16px; }
	.chapter { display:flex; flex-direction:column; gap:8px; padding:18px 0; border-top:1px solid var(--pl-line); text-decoration:none; color:inherit; }
	.chapter span { opacity:.7; font-size:.9rem; }
	.chapter:hover strong { text-decoration:underline; }
</style>
