<script>
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import Segments from '$lib/components/Segments.svelte';
	import { qtypeLabel } from '$lib/qtypes.js';
	let paper = $state(null), questions = $state([]), number = $state(''), loading = $state(true), error = $state('');
	let showSolution = $state(false);
	const current = $derived(questions.find(q => q.number === number));
	const index = $derived(questions.findIndex(q => q.number === number));
	function move(step) { number = questions[index + step]?.number || number; showSolution = false; }
	onMount(async () => {
		try {
			const result = await api.getImportedChapter($page.params.id);
			paper = result.paper; questions = result.questions; number = questions[0]?.number || '';
		} catch(e) { error = e.message; } finally { loading = false; }
	});
</script>

<svelte:head><title>{paper?.title || 'Imported chapter'} - PaperLab</title></svelte:head>
<a href="/ejee/library">← Imported textbooks</a>
{#if loading}<p role="status">Loading chapter…</p>{/if}
{#if error}<p class="pl-error" role="alert">{error}</p>{/if}
{#if paper}
	<h1>{paper.title}</h1><p class="pl-sub">Textbook library · {questions.length} questions · {paper.book}</p>
	{#if current}
		<div class="navigation">
			<button class="pl-btn" disabled={index <= 0} onclick={() => move(-1)}>← Previous</button>
			<label>Question<select class="pl-input" bind:value={number} onchange={() => showSolution = false}>{#each questions as q}<option value={q.number}>{q.number}</option>{/each}</select></label>
			<button class="pl-btn" disabled={index >= questions.length - 1} onclick={() => move(1)}>Next →</button>
		</div>
		<article class="pl-card question">
			<h2>Question {current.number}</h2><p class="meta">{qtypeLabel(current.qtype)} · {current.difficulty || 'Needs review'}</p>
			{#if current.topics.length}<details><summary>Topics</summary><ul>{#each current.topics as topic}<li>{topic.path}</li>{/each}</ul></details>{/if}
			{#if current.suggestion}<p class="hint">Topic review: {current.suggestion}</p>{/if}
			<Segments segments={current.question} />
			<button class="pl-btn" onclick={() => showSolution = !showSolution}>{showSolution ? 'Hide solution' : 'Show solution'}</button>
			{#if showSolution}<div class="solution"><Segments segments={current.solution} /></div>{/if}
		</article>
	{/if}
{/if}

<style>
	h1 { margin-top:20px; }
	.navigation { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:24px 0; }
	label { display:flex; align-items:center; gap:12px; }
	select { padding:9px 18px; color:inherit; background:var(--pl-surface); border:1px solid var(--pl-line); border-radius:8px; }
	.question { padding:24px; }
	h2 { margin:0 0 10px; }
	.meta,.hint { opacity:.7; }
	.solution { margin-top:22px; padding-top:18px; border-top:1px solid var(--pl-line); }
	details { margin-bottom:18px; }
</style>
