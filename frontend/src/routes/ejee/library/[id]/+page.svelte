<script>
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	import Segments from '$lib/components/Segments.svelte';
	import { qtypeLabel } from '$lib/qtypes.js';
	import AddToCart from '$lib/components/AddToCart.svelte';
	import FigurePanel from '$lib/components/FigurePanel.svelte';
	import { carts, cartStore, activeCart } from '$lib/carts.js';
	import { itemKey } from '$lib/cartModel.js';
	let cartMessage = $state('');
	const collectionItems = $derived(questions.map(q => ({paperId:Number(paper?.id), number:q.number, library:'ejee',
		qtype:q.qtype, difficulty:q.difficulty, exam:'EJEE collection', institute:q.source || paper?.book,
		preview:`${paper?.title} · Question ${q.number}`})));
	const cartName = $derived((paper?.title || '').trim().slice(0, 80));
	const titledCart = $derived($cartStore.carts.find(c => c.name === cartName));
	const addedCount = $derived.by(() => {
		const keys = new Set((titledCart?.items ?? []).map(i => itemKey(i.paperId,i.number,i.library)));
		return collectionItems.filter(i => keys.has(itemKey(i.paperId,i.number,i.library))).length;
	});
	// The whole collection goes into a cart named after its title (created on first use).
	function addCollection() {
		if (titledCart) carts.switch(titledCart.id); else carts.create(cartName);
		const result = carts.addMany(collectionItems);
		cartMessage = `${result.added} questions added to cart "${cartName}".`;
		if (result.duplicate) cartMessage += ` ${result.duplicate} already in cart.`;
		if (result.full) cartMessage += ` ${result.full} could not be added because the cart is full. Choose another cart.`;
		if (result.invalid) cartMessage += ` ${result.invalid} invalid questions skipped.`;
	}
	let paper = $state(null), questions = $state([]), number = $state(''), loading = $state(true), error = $state('');
	let openSolutions = $state({}), editing = $state(null), figureRev = $state(0);
	let visible = $state({});
	let renderObserver, positionObserver;
	let deleting = $state(null), deleteError = $state('');
	async function removeQuestion(n) {
		if (!window.confirm(`Delete question ${n} from "${paper.title}"? It is removed from this collection (and can be imported again from EJEE Import).`)) return;
		deleting = n; deleteError = '';
		try {
			await api.deleteEjeeQuestion(paper.id, n);
			questions = questions.filter(q => q.number !== n);
			if (editing === n) editing = null;
			if (number === n) number = questions[0]?.number || '';
		} catch(e) { deleteError = `Could not delete question ${n}: ${e.message}`; } finally { deleting = null; }
	}
	let renaming = $state(false), titleDraft = $state(''), titleError = $state(''), titleBusy = $state(false);
	function startRename() { titleDraft = paper.title; titleError = ''; renaming = true; }
	async function saveTitle() {
		titleBusy = true; titleError = '';
		try {
			const saved = await api.renameEjeeCollection(paper.id, titleDraft);
			paper = {...paper, title: saved.title}; renaming = false;
		} catch(e) { titleError = e.message; } finally { titleBusy = false; }
	}
	// Questions render only when scrolled near, so a 150-question collection stays fast.
	function track(node) {
		renderObserver ??= new IntersectionObserver(entries => {
			for (const entry of entries) if (entry.isIntersecting) {
				visible = {...visible, [entry.target.dataset.n]: true};
				renderObserver.unobserve(entry.target);
			}
		}, {rootMargin: '1500px 0px'});
		positionObserver ??= new IntersectionObserver(entries => {
			for (const entry of entries) if (entry.isIntersecting) number = entry.target.dataset.n;
		}, {rootMargin: '-15% 0px -75% 0px'});
		renderObserver.observe(node); positionObserver.observe(node);
		return {destroy() { renderObserver?.unobserve(node); positionObserver?.unobserve(node); }};
	}
	async function jump(n) {
		visible = {...visible, [n]: true}; number = n;
		await tick();
		const target = () => document.getElementById(`q-${n}`)?.scrollIntoView({block: 'start'});
		target(); setTimeout(target, 250);  // placeholders resize once their content renders
	}
	onMount(() => {
		(async () => {
			try {
				const result = await api.getImportedChapter($page.params.id);
				paper = result.paper; questions = result.questions;
				const requested = $page.url.searchParams.get('q');
				number = questions.some(q => q.number === requested) ? requested : questions[0]?.number || '';
				if (requested && number === requested) { await tick(); jump(requested); }
			} catch(e) { error = e.message; } finally { loading = false; }
		})();
		return () => { renderObserver?.disconnect(); positionObserver?.disconnect(); };
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
		<span class="pl-sub">{addedCount}/{questions.length} in cart "{cartName}"</span>
	</div>
	{#if cartMessage}<p role="status">{cartMessage}</p>{/if}
	{#if deleteError}<p class="pl-error" role="alert">{deleteError}</p>{/if}
	{#if questions.length}
		<nav class="navigation" aria-label="Question navigation">
			<label>Jump to question<select class="pl-input" value={number} onchange={e => { jump(e.currentTarget.value); e.currentTarget.blur(); }}>{#each questions as q}<option value={q.number}>{q.number}</option>{/each}</select></label>
			<span class="pl-sub">{Math.max(1, questions.findIndex(q => q.number === number) + 1)} of {questions.length} · scroll or use ↑ ↓ keys</span>
		</nav>
		{#each questions as current (current.number)}
			<article class="pl-card question" id={`q-${current.number}`} data-n={current.number} use:track>
			{#if visible[current.number]}
				<header class="qhead">
					<h2>Question {current.number}</h2>
					<div class="qactions">
						<AddToCart item={{paperId:Number(paper.id),number:current.number,library:'ejee',qtype:current.qtype,difficulty:current.difficulty,exam:'EJEE collection',institute:current.source || paper.book,preview:`${paper.title} · Question ${current.number}`}} variant="tool" showLabel />
						{#if $role === 'archivist'}
							<button type="button" class="pl-btn" onclick={() => editing = editing === current.number ? null : current.number}>{editing === current.number ? 'Close diagram editor' : 'Edit diagrams'}</button>
							<button type="button" class="pl-btn danger" disabled={deleting === current.number} aria-label={`Delete question ${current.number}`} onclick={() => removeQuestion(current.number)}>{deleting === current.number ? 'Deleting…' : 'Delete'}</button>
						{/if}
					</div>
				</header>
				<div class="chips">
					<span class="chip">{qtypeLabel(current.qtype)}</span>
					<span class="chip">{current.difficulty || 'Needs review'}</span>
					{#if current.source}<span class="chip source" title="Source">{current.source}</span>{/if}
					{#each current.source_tags || [] as tag}<span class="chip">{tag}</span>{/each}
					{#if current.tagging_mode === 'source'}<span class="chip quiet">Original EJEE tags</span>{/if}
				</div>
				{#if current.topics.length}<details class="topics"><summary>Topics ({current.topics.length})</summary><ul>{#each current.topics as topic}<li>{topic.path}</li>{/each}</ul></details>{/if}
				{#if current.suggestion}<p class="hint">Topic review: {current.suggestion}</p>{/if}
				{#if $role === 'archivist' && editing === current.number}
					{#key figureRev}
						<div class="figures-editor"><FigurePanel ejeePaperId={paper.id} qn={current.number} rev={figureRev}
							onChanged={async () => { figureRev += 1; const fresh = await api.getImportedChapter($page.params.id); questions = fresh.questions; }} /></div>
					{/key}
				{/if}
				<Segments segments={current.question} zoomable figureScale={0.4} figureMax={300} />
				<button class="pl-btn" onclick={() => openSolutions = {...openSolutions, [current.number]: !openSolutions[current.number]}}>
					{openSolutions[current.number] ? 'Hide' : 'Show'} {current.key_only ? 'answer key' : 'solution'}
				</button>
				{#if openSolutions[current.number]}<div class="solution"><Segments segments={current.solution} zoomable figureScale={0.4} figureMax={300} /></div>{/if}
			{:else}
				<p class="placeholder" aria-busy="true">Question {current.number}…</p>
			{/if}
			</article>
		{/each}
	{/if}
{/if}

<style>
	h1 { margin-top:20px; }
	.rename { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:20px; }
	.rename input { flex:1 1 320px; }
	.rename-btn { margin-left:12px; vertical-align:middle; font-size:.85rem; min-height:36px; padding:6px 12px; }
	.navigation { position:sticky; top:0; z-index:5; display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin:16px 0; padding:10px 0; background:var(--pl-paper); border-bottom:1px solid var(--pl-line); }
	label { display:flex; align-items:center; gap:12px; }
	select { padding:9px 18px; color:inherit; background:var(--pl-surface); border:1px solid var(--pl-line); border-radius:8px; }
	.question { padding:24px; margin-bottom:18px; scroll-margin-top:72px; }
	.placeholder { min-height:300px; opacity:.4; margin:0; }
	.hint { opacity:.7; margin:8px 0; }
	.qhead { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px 16px; }
	.qhead h2 { margin:0; }
	.qactions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
	.danger { color:var(--pl-seal); border-color:var(--pl-seal); }
	.chips { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0 6px; }
	.chip { font-size:.8rem; line-height:1.3; padding:3px 10px; border:1px solid var(--pl-line); border-radius:999px; }
	.chip.source { max-width:100%; overflow-wrap:anywhere; }
	.chip.quiet { opacity:.65; }
	.topics { margin:4px 0 14px; }
	.topics summary { cursor:pointer; font-size:.88rem; opacity:.8; }
	.topics ul { margin:6px 0 0; padding-left:20px; font-size:.88rem; }
	.cart-actions { display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin:12px 0; }
	.solution { margin-top:22px; padding-top:18px; border-top:1px solid var(--pl-line); }
	.figures-editor { margin:14px 0; padding:14px; border:1px solid var(--pl-line); border-radius:10px; }
</style>
