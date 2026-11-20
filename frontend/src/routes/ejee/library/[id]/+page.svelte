<script>
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	import Segments from '$lib/components/Segments.svelte';
	import { qtypeLabel } from '$lib/qtypes.js';
	import AddToCart from '$lib/components/AddToCart.svelte';
	import { carts, cartStore, activeCart } from '$lib/carts.js';
	import { itemKey } from '$lib/cartModel.js';
	let cartMessage = $state('');
	const collectionItems = $derived(questions.map(q => ({paperId:Number(paper?.id), number:q.number, library:'ejee',
		qtype:q.qtype, difficulty:q.difficulty, exam:'EJEE collection', institute:q.source || paper?.book,
		preview:`${paper?.title} · Question ${q.number}`})));
	const addedCount = $derived.by(() => {
		const keys = new Set(($activeCart?.items ?? []).map(i => itemKey(i.paperId,i.number,i.library)));
		return collectionItems.filter(i => keys.has(itemKey(i.paperId,i.number,i.library))).length;
	});
	function addCollection() {
		const result = carts.addMany(collectionItems);
		cartMessage = `${result.added} questions added to ${$activeCart?.name || 'cart'}.`;
		if (result.duplicate) cartMessage += ` ${result.duplicate} already in cart.`;
		if (result.full) cartMessage += ` ${result.full} could not be added because the cart is full. Choose another cart.`;
		if (result.invalid) cartMessage += ` ${result.invalid} invalid questions skipped.`;
	}
	let paper = $state(null), questions = $state([]), number = $state(''), loading = $state(true), error = $state('');
	let showSolution = $state(false);
	let renaming = $state(false), titleDraft = $state(''), titleError = $state(''), titleBusy = $state(false);
	function startRename() { titleDraft = paper.title; titleError = ''; renaming = true; }
	async function saveTitle() {
		titleBusy = true; titleError = '';
		try {
			const saved = await api.renameEjeeCollection(paper.id, titleDraft);
			paper = {...paper, title: saved.title}; renaming = false;
		} catch(e) { titleError = e.message; } finally { titleBusy = false; }
	}
	const current = $derived(questions.find(q => q.number === number));
	const index = $derived(questions.findIndex(q => q.number === number));
	function move(step) { number = questions[index + step]?.number || number; showSolution = false; }
	onMount(async () => {
		try {
			const result = await api.getImportedChapter($page.params.id);
			paper = result.paper; questions = result.questions;
			const requested = $page.url.searchParams.get('q');
			number = questions.some(q => q.number === requested) ? requested : questions[0]?.number || '';
		} catch(e) { error = e.message; } finally { loading = false; }
	});
</script>

<svelte:head><title>{paper?.title || 'Imported collection'} - PaperLab</title></svelte:head>
<a href="/ejee/library">← EJEE collections</a>
{#if loading}<p role="status">Loading collection…</p>{/if}
{#if error}<p class="pl-error" role="alert">{error}</p>{/if}
{#if paper}
	{#if renaming}
		<form class="rename" onsubmit={e => {e.preventDefault(); saveTitle();}}>
			<input class="pl-input" aria-label="Collection title" bind:value={titleDraft} maxlength="180" required />
			<button class="pl-btn pl-btn-primary" disabled={titleBusy || !titleDraft.trim()}>{titleBusy ? 'Saving…' : 'Save title'}</button>
			<button type="button" class="pl-btn" disabled={titleBusy} onclick={() => renaming = false}>Cancel</button>
		</form>
		{#if titleError}<p class="pl-error" role="alert">{titleError}</p>{/if}
	{:else}
		<h1>{paper.title}{#if $role === 'archivist'} <button type="button" class="pl-btn rename-btn" onclick={startRename}>Edit title</button>{/if}</h1>
	{/if}<p class="pl-sub">EJEE library · {questions.length} questions · {paper.book}</p>
	<div class="cart-actions">
		{#if paper.can_append && $role === 'archivist'}
			<a class="pl-btn" href={`/ejee?append=${paper.id}`}>Add more questions</a>
		{/if}
		<label>Cart<select class="pl-input" value={$activeCart?.id} onchange={(e) => { carts.switch(e.currentTarget.value); cartMessage=''; }}>
			{#each $cartStore.carts as cart}<option value={cart.id}>{cart.name}</option>{/each}
		</select></label>
		<button type="button" class="pl-btn pl-btn-primary" disabled={!questions.length || addedCount === questions.length} onclick={addCollection}>
			{addedCount === questions.length && questions.length ? 'All questions in cart' : `Add all ${questions.length} questions to cart`}
		</button>
		<a class="pl-btn" href="/cart">Open cart →</a>
		<span class="pl-sub">{addedCount}/{questions.length} in selected cart</span>
	</div>
	{#if cartMessage}<p role="status">{cartMessage}</p>{/if}
	{#if current}
		<div class="navigation">
			<button class="pl-btn" disabled={index <= 0} onclick={() => move(-1)}>← Previous</button>
			<label>Question<select class="pl-input" bind:value={number} onchange={() => showSolution = false}>{#each questions as q}<option value={q.number}>{q.number}</option>{/each}</select></label>
			<button class="pl-btn" disabled={index >= questions.length - 1} onclick={() => move(1)}>Next →</button>
		</div>
		<article class="pl-card question">
			<h2>Question {current.number}</h2>
			<div class="cart-actions"><AddToCart item={{paperId:Number(paper.id),number:current.number,library:'ejee',qtype:current.qtype,difficulty:current.difficulty,exam:'EJEE collection',institute:current.source || paper.book,preview:`${paper.title} · Question ${current.number}`}} variant="tool" showLabel /><a class="pl-btn" href="/cart">Open cart →</a></div>
			{#if current.source}<p class="meta">Source: {current.source}</p>{/if}<p class="meta">{qtypeLabel(current.qtype)} · {current.difficulty || 'Needs review'}</p>
			{#if current.topics.length}<details><summary>Topics</summary><ul>{#each current.topics as topic}<li>{topic.path}</li>{/each}</ul></details>{/if}
			{#if current.tagging_mode === 'source'}<p class="meta">Original EJEE tagging</p>{/if}
			{#if current.source_tags?.length}<p class="meta">Tags: {current.source_tags.join(' · ')}</p>{/if}
			{#if current.suggestion}<p class="hint">Topic review: {current.suggestion}</p>{/if}
			<Segments segments={current.question} />
			<button class="pl-btn" onclick={() => showSolution = !showSolution}>
				{showSolution ? 'Hide' : 'Show'} {current.key_only ? 'answer key' : 'solution'}
			</button>
			{#if showSolution}<div class="solution"><Segments segments={current.solution} /></div>{/if}
		</article>
	{/if}
{/if}

<style>
	h1 { margin-top:20px; }
	.rename { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:20px; }
	.rename input { flex:1 1 320px; }
	.rename-btn { margin-left:12px; vertical-align:middle; font-size:.85rem; min-height:36px; padding:6px 12px; }
	.navigation { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:24px 0; }
	label { display:flex; align-items:center; gap:12px; }
	select { padding:9px 18px; color:inherit; background:var(--pl-surface); border:1px solid var(--pl-line); border-radius:8px; }
	.question { padding:24px; }
	h2 { margin:0 0 10px; }
	.meta,.hint { opacity:.7; }
	.cart-actions { display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin:12px 0; }
	.solution { margin-top:22px; padding-top:18px; border-top:1px solid var(--pl-line); }
	details { margin-bottom:18px; }
</style>
