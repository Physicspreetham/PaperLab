<script>
	/**
	 * Pick questions by hand for one section of a model paper. Three ways in:
	 *   Cart    - questions you already collected
	 *   Search  - filter by type, difficulty, source, exam, year
	 *   Topics  - pick modules / chapters / weeks / subtopics from the syllabus tree
	 * Search and Topics share one filter set and one result list (same /api/search the
	 * Search page uses). Questions already in the paper are shown but can't be added twice.
	 */
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { qtypeLabel } from '$lib/qtypes.js';
	import { PAGE_SIZE, defaultFilters, activeFilterCount } from '$lib/search.js';
	import FilterDropdown from '$lib/components/FilterDropdown.svelte';
	import TopicTreePicker from '$lib/components/TopicTreePicker.svelte';

	let { section, fits, taken, carts = [], activeCartId = '', onAdd, onClose } = $props();
	// section: pattern section (id, typeName, units, ...)
	// fits(qtype) -> bool: does this question type belong in the section
	// taken: Set of "paperId::number" already in the paper

	let tab = $state('search'); // cart | search | topics
	let onlyFits = $state(true);
	let cartId = $state(activeCartId || carts[0]?.id || '');
	let filters = $state(defaultFilters());
	let facets = $state(null);
	let topics = $state([]);
	let items = $state([]);
	let total = $state(0);
	let nextCursor = $state(null);
	let hasMore = $state(false);
	let loading = $state(false);
	let error = $state('');
	let reqId = 0;
	let picked = $state({}); // key -> item

	const key = (it) => `${it.paperId}::${it.number}`;
	const cart = $derived(carts.find((c) => c.id === cartId) ?? null);
	const pickedList = $derived(Object.values(picked));

	const facetOpts = $derived.by(() => {
		if (!facets) return { qtype: [], difficulty: [], exam: [], institute: [], year: [] };
		return {
			qtype: facets.qtypes.map((o) => ({ value: o.value, count: o.count })),
			difficulty: facets.difficulties.map((o) => ({ value: o.value, count: o.count })),
			exam: facets.exams.map((o) => ({ value: o.value, count: o.count })),
			institute: facets.institutes.map((o) => ({ value: o.name, count: o.count })),
			year: facets.years.map((o) => ({ value: String(o.value), count: o.count }))
		};
	});
	const topicCounts = $derived(facets?.topicSubtreeCounts ?? facets?.topicCounts ?? {});

	// "only types that fit" narrows the search to what this section accepts
	const effective = $derived.by(() => {
		const f = { ...filters };
		if (onlyFits && facets && !filters.qtype.length) {
			f.qtype = facets.qtypes.map((o) => o.value).filter((q) => fits(q));
			if (!f.qtype.length) f.qtype = ['__none__'];
		}
		return f;
	});

	async function fetchPage(cursor, append) {
		const id = ++reqId;
		loading = true;
		if (!append) error = '';
		try {
			const res = await api.searchQuestions(effective, { limit: PAGE_SIZE, cursor });
			if (id !== reqId) return;
			items = append ? [...items, ...res.items] : res.items;
			total = res.total;
			nextCursor = res.nextCursor;
			hasMore = res.hasMore;
		} catch (e) {
			if (id === reqId && !append) error = e.message;
		} finally {
			if (id === reqId) loading = false;
		}
	}

	let sig = '';
	$effect(() => {
		if (tab === 'cart' || !facets) return;
		const s = JSON.stringify(effective);
		if (s === sig) return;
		sig = s;
		items = [];
		nextCursor = null;
		fetchPage(null, false);
	});

	onMount(async () => {
		try {
			const [f, t] = await Promise.all([api.getSearchFacets(), api.getTopics().catch(() => [])]);
			facets = f;
			topics = t;
		} catch (e) {
			error = e.message;
		}
	});

	const toRow = (it) => ({
		paperId: it.paperId,
		number: it.number,
		qtype: it.qtype,
		difficulty: it.difficulty ?? null
	});
	const blocked = (it) => taken.has(key(it)) || (onlyFits && !fits(it.qtype));
	const why = (it) => (taken.has(key(it)) ? 'Already in the paper' : onlyFits && !fits(it.qtype) ? "Type doesn't fit this section" : '');

	function toggle(it) {
		if (blocked(it)) return;
		const k = key(it);
		const next = { ...picked };
		if (next[k]) delete next[k];
		else next[k] = toRow(it);
		picked = next;
	}
	function selectAll(list) {
		const next = { ...picked };
		for (const it of list) if (!blocked(it)) next[key(it)] = toRow(it);
		picked = next;
	}

	function add() {
		if (!pickedList.length) return;
		onAdd(pickedList);
		picked = {};
	}

	const chapters = (it) => (it.chapters?.length ? it.chapters.join(' · ') + (it.chapterOverflow > 0 ? ` +${it.chapterOverflow}` : '') : '');
	const meta = (it) => it.paper ?? { exam: it.exam, year: it.year };
	const cartRows = $derived((cart?.items ?? []).map((it) => ({ ...it })));
	const searchActive = $derived(activeFilterCount(filters));
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onClose()} />

<div class="scrim" onclick={onClose} aria-hidden="true"></div>
<div class="dialog" role="dialog" aria-modal="true" aria-label={`Add questions to Section ${section.id.replace('S', '')}`}>
	<header>
		<div>
			<h2>Add questions · Section {section.id.replace('S', '')} · {section.typeName}</h2>
			<p class="pl-sub">This section takes {section.units}{section.sets && section.per ? ` (${section.sets} × ${section.per})` : ''}. Pick questions from your cart, by searching, or from the syllabus.</p>
		</div>
		<button type="button" class="x" onclick={onClose} aria-label="Close">✕</button>
	</header>

	<div class="tabs" role="tablist">
		{#each [['cart', 'Cart'], ['search', 'Search'], ['topics', 'Topics']] as [id, label] (id)}
			<button type="button" role="tab" class:on={tab === id} aria-selected={tab === id} onclick={() => (tab = id)}>
				{label}{#if id === 'cart'}<small> {cart?.items.length ?? 0}</small>{:else if id === 'search' && searchActive}<small> {searchActive}</small>{:else if id === 'topics' && filters.topic.length}<small> {filters.topic.length}</small>{/if}
			</button>
		{/each}
		<label class="fit"><input type="checkbox" bind:checked={onlyFits} /> Only types that fit this section</label>
	</div>

	{#if tab === 'search'}
		<div class="bar">
			<FilterDropdown label="Type" options={facetOpts.qtype} bind:selected={filters.qtype} format={qtypeLabel} />
			<FilterDropdown label="Difficulty" options={facetOpts.difficulty} bind:selected={filters.difficulty} />
			<FilterDropdown label="Source" options={facetOpts.institute} bind:selected={filters.institute} />
			<FilterDropdown label="Exam" options={facetOpts.exam} bind:selected={filters.exam} />
			<FilterDropdown label="Year" options={facetOpts.year} bind:selected={filters.year} />
			{#if searchActive}<button type="button" class="link" onclick={() => (filters = { ...defaultFilters(), topic: filters.topic })}>Clear filters</button>{/if}
		</div>
	{:else if tab === 'topics'}
		<div class="bar">
			<TopicTreePicker nodes={topics} counts={topicCounts} bind:selected={filters.topic} />
			<FilterDropdown label="Difficulty" options={facetOpts.difficulty} bind:selected={filters.difficulty} />
			<span class="pl-sub">Tick a module, chapter, week or subtopic; ticking a parent includes everything under it.</span>
			{#if filters.topic.length}<button type="button" class="link" onclick={() => (filters = { ...filters, topic: [] })}>Clear topics</button>{/if}
		</div>
	{:else}
		<div class="bar">
			<select bind:value={cartId} aria-label="Source cart">
				{#each carts as c (c.id)}<option value={c.id}>{c.name} · {c.items.length}</option>{/each}
			</select>
			<button type="button" class="pl-btn" disabled={!cartRows.length} onclick={() => selectAll(cartRows)}>Select all that fit</button>
			{#if !carts.length}<span class="pl-sub">No carts yet: add questions to a cart from Search Questions.</span>{/if}
		</div>
	{/if}

	<div class="list" role="list">
		{#if tab === 'cart'}
			{#each cartRows as it (key(it))}
				{@render row(it)}
			{:else}
				<p class="empty pl-sub">This cart is empty.</p>
			{/each}
		{:else}
			{#if error}<p class="pl-error" role="alert">{error}</p>{/if}
			{#each items as it (key(it))}
				{@render row(it)}
			{/each}
			{#if loading}<p class="empty pl-sub">Loading…</p>{:else if !items.length && !error}<p class="empty pl-sub">No questions match these filters.</p>{/if}
			{#if hasMore && !loading}
				<div class="more"><button type="button" class="pl-btn" onclick={() => fetchPage(nextCursor, true)}>Load more · {items.length} of {total}</button></div>
			{/if}
		{/if}
	</div>

	<footer>
		<span class="pl-sub">{pickedList.length} selected{tab !== 'cart' && total ? ` · ${total} match` : ''}</span>
		<span class="btns">
			{#if tab !== 'cart' && items.length}
				<button type="button" class="pl-btn" onclick={() => selectAll(items)}>Select shown</button>
			{/if}
			<button type="button" class="pl-btn" disabled={!pickedList.length} onclick={() => (picked = {})}>Clear</button>
			<button type="button" class="pl-btn pl-btn-primary" disabled={!pickedList.length} onclick={add}>Add {pickedList.length || ''} to Section {section.id.replace('S', '')}</button>
			<button type="button" class="pl-btn" onclick={onClose}>Done</button>
		</span>
	</footer>
</div>

{#snippet row(it)}
	{@const m = meta(it)}
	{@const off = blocked(it)}
	<label class="row" class:off title={why(it)}>
		<input type="checkbox" checked={!!picked[key(it)]} disabled={off} onchange={() => toggle(it)} />
		<span class="body">
			<span class="preview">{it.preview || `Paper ${it.paperId} · question ${it.number}`}</span>
			{#if chapters(it)}<span class="chap">{chapters(it)}</span>{/if}
			{#if why(it)}<span class="why">{why(it)}</span>{/if}
		</span>
		<span class="chips">
			<span class="pl-sub">{m.exam ?? ''}{m.year ? ` · ${m.year}` : ''}</span>
			{#if it.difficulty}<span class="chip">{it.difficulty}</span>{/if}
			<span class="chip">{qtypeLabel(it.qtype)}</span>
		</span>
	</label>
{/snippet}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		background: rgb(0 0 0 / 0.45);
		z-index: 40;
	}
	.dialog {
		position: fixed;
		z-index: 41;
		left: 50%;
		top: 5vh;
		transform: translateX(-50%);
		width: min(940px, 94vw);
		max-height: 90vh;
		display: flex;
		flex-direction: column;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-lg);
		box-shadow: var(--pl-shadow-md);
	}
	header {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		padding: 16px 20px 6px;
	}
	header h2 {
		font-size: 1.05rem;
		margin: 0 0 2px;
	}
	header p {
		margin: 0;
	}
	.x {
		min-height: 32px;
		min-width: 32px;
		border: none;
		background: none;
		color: var(--pl-ink-soft);
		font-size: 1rem;
	}
	.tabs {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 6px 20px 0;
		border-bottom: 1px solid var(--pl-line);
	}
	.tabs button {
		min-height: 36px;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		color: var(--pl-ink-soft);
		font-weight: 600;
		padding: 0 14px;
	}
	.tabs button.on {
		color: var(--pl-ink);
		border-bottom-color: var(--pl-seal);
	}
	.tabs small {
		color: var(--pl-seal);
		margin-left: 5px;
	}
	.fit {
		margin-left: auto;
		display: inline-flex;
		gap: 6px;
		align-items: center;
		font-size: 0.8rem;
		padding-bottom: 6px;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		padding: 10px 20px;
	}
	.bar select {
		min-height: 36px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-paper);
		color: var(--pl-ink);
		padding: 0 10px;
		font: inherit;
	}
	.link {
		border: none;
		background: none;
		min-height: 0;
		color: var(--pl-seal);
		text-decoration: underline;
		font-size: 0.8rem;
	}
	.list {
		flex: 1;
		min-height: 120px;
		overflow-y: auto;
		padding: 0 20px;
	}
	.row {
		display: grid;
		grid-template-columns: 24px 1fr auto;
		gap: 10px;
		align-items: start;
		padding: 10px 4px;
		border-top: 1px solid var(--pl-line);
		cursor: pointer;
	}
	.row.off {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.row:hover:not(.off) {
		background: var(--pl-raised);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.preview {
		font-size: 0.86rem;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.chap {
		font-size: 0.74rem;
		color: var(--pl-ink-soft);
	}
	.why {
		font-size: 0.72rem;
		color: var(--pl-seal);
	}
	.chips {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 3px;
		font-size: 0.72rem;
	}
	.chip {
		border: 1px solid var(--pl-line);
		border-radius: 999px;
		padding: 0 8px;
		font-weight: 600;
		background: var(--pl-paper);
	}
	.empty {
		padding: 18px 0;
	}
	.more {
		text-align: center;
		padding: 12px 0;
	}
	footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
		padding: 12px 20px;
		border-top: 1px solid var(--pl-line);
	}
	.btns {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
</style>
