<script>
	import { onMount, untrack } from 'svelte';
	import { api } from '$lib/api.js';
	import { qtypeLabel } from '$lib/qtypes.js';
	import { PAGE_SIZE, defaultFilters, activeFilterCount } from '$lib/search.js';
	import FilterDropdown from '$lib/components/FilterDropdown.svelte';
	import TopicTreePicker from '$lib/components/TopicTreePicker.svelte';
	import ModelQuestion from '$lib/components/ModelQuestion.svelte';

	let { section, fits, taken, carts = [], activeCartId = '', onAdd, onClose } = $props();
	// section: pattern section (id, typeName, units, ...)
	// fits(qtype) -> bool: does this question type belong in the section
	// taken: Set of "paperId::number" already in the paper

	let tab = $state('cart');
	let currentKey = $state('');
	let pane = $state(null);
	const questionNodes = new Map();
	let cartId = $state(untrack(() => activeCartId || carts[0]?.id || ''));
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
	const pickedList = $derived(Object.values(picked).filter((it) => !taken.has(key(it)) && fits(it.qtype)));

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

	// Always constrain searches to the question types accepted by this section.
	const effective = $derived.by(() => {
		const f = { ...filters };
		if (facets) {
			f.qtype = (filters.qtype.length ? filters.qtype : facets.qtypes.map((o) => o.value)).filter((q) => fits(q));
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
			if (id === reqId) error = e.message;
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
		hasMore = false;
		total = 0;
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
	const blocked = (it) => taken.has(key(it)) || !fits(it.qtype);
	const why = (it) => (taken.has(key(it)) ? 'Already in the paper' : !fits(it.qtype) ? "Type doesn't fit this section" : '');

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
		onAdd(pickedList.filter((it) => !blocked(it)));
		picked = {};
	}

	function focusDialog(node) {
		const previous = document.activeElement;
		const oldOverflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		node.querySelector('button')?.focus();
		function trap(event) {
			if (event.key !== 'Tab') return;
			const controls = [...node.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]')].filter((el) => el.getClientRects().length);
			const first = controls[0], last = controls.at(-1);
			if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
			else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
		}
		node.addEventListener('keydown', trap);
		return { destroy() { node.removeEventListener('keydown', trap); document.body.style.overflow = oldOverflow; previous?.focus(); } };
	}

	const cartRows = $derived((cart?.items ?? []).filter((it) => fits(it.qtype)));
	const visibleRows = $derived(tab === 'cart' ? cartRows : items);
	const current = $derived(visibleRows.find((it) => key(it) === currentKey) ?? visibleRows[0] ?? null);
	function openQuestion(it) {
		currentKey = key(it);
		questionNodes.get(key(it))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}
	function questionAnchor(node, id) {
		questionNodes.set(id, node);
		return { destroy() { questionNodes.delete(id); } };
	}
	function onReaderScroll() {
		if (!pane) return;
		const top = pane.getBoundingClientRect().top + 80;
		for (const [id, node] of questionNodes) {
			if (node.getBoundingClientRect().bottom > top) { currentKey = id; break; }
		}
	}
	function loadMoreOnView(node, enabled) {
		let observer;
		function watch(active) {
			observer?.disconnect();
			if (!active) return;
			observer = new IntersectionObserver((entries) => {
				if (entries.some((entry) => entry.isIntersecting) && !loading && hasMore && !error) fetchPage(nextCursor, true);
			}, { root: pane, rootMargin: '400px' });
			observer.observe(node);
		}
		watch(enabled);
		return { update: watch, destroy() { observer?.disconnect(); } };
	}
	const searchActive = $derived(activeFilterCount(filters));
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onClose()} />

<div class="scrim" onclick={onClose} aria-hidden="true"></div>
<div class="dialog" use:focusDialog role="dialog" aria-modal="true" aria-label={`Add questions to Section ${section.id.replace('S', '')}`}>
	<header>
		<div>
			<h2>Add questions · Section {section.id.replace('S', '')} · {section.typeName}</h2>
			<p class="pl-sub">This section takes {section.units}{section.sets && section.per ? ` (${section.sets} × ${section.per})` : ''}. Choose Cart or Search. Only question types suitable for this section are shown.</p>
		</div>
		<button type="button" class="x" onclick={onClose} aria-label="Close">✕</button>
	</header>

	<div class="tabs" role="tablist">
		{#each [['cart', 'Cart'], ['search', 'Search']] as [id, label] (id)}
			<button type="button" role="tab" class:on={tab === id} aria-selected={tab === id} onclick={() => { tab = id; picked = {}; currentKey = ''; pane?.scrollTo({ top: 0 }); }}>
				{label}{#if id === 'cart'}<small> {cartRows.length}</small>{:else if id === 'search' && searchActive}<small> {searchActive}</small>{/if}
			</button>
		{/each}
	</div>

	<details class="configuration">
		<summary>{tab === 'search' ? 'Filters' : 'Choose cart'}</summary>

	{#if tab === 'search'}
		<div class="bar">
			<FilterDropdown label="Type" options={facetOpts.qtype} bind:selected={filters.qtype} format={qtypeLabel} />
			<FilterDropdown label="Difficulty" options={facetOpts.difficulty} bind:selected={filters.difficulty} />
			<FilterDropdown label="Source" options={facetOpts.institute} bind:selected={filters.institute} />
			<FilterDropdown label="Exam" options={facetOpts.exam} bind:selected={filters.exam} />
			<FilterDropdown label="Year" options={facetOpts.year} bind:selected={filters.year} />
			<TopicTreePicker nodes={topics} counts={topicCounts} bind:selected={filters.topic} />
			{#if searchActive}<button type="button" class="link" onclick={() => (filters = defaultFilters())}>Clear all filters · {searchActive}</button>{/if}
		</div>
	{:else}
		<div class="bar">
			<select bind:value={cartId} onchange={() => { picked = {}; currentKey = ''; pane?.scrollTo({ top: 0 }); }} aria-label="Source cart">
				{#each carts as c (c.id)}<option value={c.id}>{c.name} · {c.items.length}</option>{/each}
			</select>
			<button type="button" class="pl-btn" disabled={!cartRows.length} onclick={() => selectAll(cartRows)}>Select all that fit</button>
			{#if !carts.length}<span class="pl-sub">No carts yet: add questions to a cart from Search Questions.</span>{/if}
		</div>
	{/if}

	</details>

	{#if tab === 'search' && error}<p class="pl-error" role="alert">{error}</p>{/if}
	{#if visibleRows.length}
		<div class="desk">
			<nav class="index" aria-label="Questions">
				{#each visibleRows as it (key(it))}
					<div class="index-row">
						<input type="checkbox" aria-label={`Select question ${it.number} from paper ${it.paperId}`}
							checked={!!picked[key(it)] && !blocked(it)} disabled={blocked(it)} onchange={() => toggle(it)} />
						<button type="button" class="qbtn" class:active={current && key(current) === key(it)}
							aria-current={current && key(current) === key(it) ? 'true' : undefined}
							onclick={() => openQuestion(it)}>
							<span class="pl-mono">Q{it.number}</span>
							<small>Paper {it.paperId}</small>
							{#if why(it)}<small>{why(it)}</small>{/if}
						</button>
					</div>
				{/each}
				{#if tab === 'search' && hasMore}
					<button type="button" class="pl-btn" disabled={loading} onclick={() => fetchPage(nextCursor, true)}>{loading ? 'Loading…' : `Load more · ${items.length} of ${total}`}</button>
				{/if}
			</nav>
			<div class="pane" bind:this={pane} onscroll={onReaderScroll}>
				{#each visibleRows as it (key(it))}
					<div class="question-block" use:questionAnchor={key(it)}>
						<ModelQuestion item={it} selected={!!picked[key(it)] && !blocked(it)} disabled={blocked(it)} reason={why(it)}
							onToggle={() => toggle(it)} onAdd={(question) => { if (!blocked(question)) onAdd([toRow(question)]); }} />
					</div>
				{/each}
				{#if tab === 'search' && hasMore}
					<div class="more" use:loadMoreOnView={!loading && !error}>
						<button type="button" class="pl-btn" disabled={loading} onclick={() => fetchPage(nextCursor, true)}>{loading ? 'Loading…' : `Load more · ${items.length} of ${total}`}</button>
					</div>
				{/if}
			</div>
		</div>
	{:else}
		<div class="empty pl-sub">
			{#if loading && tab === 'search'}Loading…
			{:else if tab === 'cart'}No questions in this cart fit this section. Choose another cart or use Search.
			{:else if !error}No questions match these filters.{/if}
		</div>
	{/if}

	<footer>
		<span class="pl-sub">{pickedList.length} selected{tab !== 'cart' && total ? ` · ${total} match` : ''}</span>
		<span class="btns">
			{#if visibleRows.length}
				<button type="button" class="pl-btn" onclick={() => selectAll(visibleRows)}>Select all</button>
			{/if}
			<button type="button" class="pl-btn" disabled={!pickedList.length} onclick={() => (picked = {})}>Clear</button>
			<button type="button" class="pl-btn pl-btn-primary" disabled={!pickedList.length} title={`Add selected questions to Section ${section.id.replace('S', '')}`} onclick={add}>Add {pickedList.length || ''}</button>
			<button type="button" class="pl-btn" onclick={onClose}>Done</button>
		</span>
	</footer>
</div>

<style>
	.scrim { position: fixed; inset: 0; background: rgb(0 0 0 / 0.45); z-index: 40; }
	.dialog {
		position: fixed; z-index: 41; inset: 0;
		width: 100%; height: 100dvh; box-sizing: border-box;
		display: grid; grid-template-columns: 190px minmax(0, 1fr);
		grid-template-rows: auto auto auto minmax(0, 1fr) auto;
		background: var(--pl-surface); border: 1px solid var(--pl-line); box-shadow: var(--pl-shadow-md);
	}
	header { grid-column: 1; grid-row: 1; display: flex; align-items: start; gap: 4px; padding: 10px 8px 4px; }
	header h2 { font-size: 0.85rem; margin: 0; overflow-wrap: anywhere; }
	header p { display: none; }
	.x { min-height: 32px; min-width: 32px; padding: 0; border: none; background: none; color: var(--pl-ink-soft); }
	.tabs { grid-column: 1; grid-row: 2; display: flex; border-bottom: 1px solid var(--pl-line); }
	.tabs button { flex: 1; min-width: 0; min-height: 40px; border: none; border-bottom: 2px solid transparent; background: none; color: var(--pl-ink-soft); font-weight: 600; padding: 4px; }
	.tabs button.on { color: var(--pl-ink); border-bottom-color: var(--pl-seal); }
	.configuration { grid-column: 1; grid-row: 3; position: relative; margin: 8px; }
	.configuration summary { cursor: pointer; font-size: 0.85rem; min-height: 32px; display: flex; align-items: center; }
	.configuration summary::before { content: '▸'; margin-right: 4px; }
	.configuration[open] summary::before { content: '▾'; }
	.bar { position: absolute; left: 100%; top: 0; z-index: 10; width: min(400px, calc(100vw - 210px)); box-sizing: border-box; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px; background: var(--pl-surface); border: 1px solid var(--pl-line); border-radius: var(--pl-radius-sm); box-shadow: var(--pl-shadow-md); }
	.bar select { min-height: 36px; max-width: 100%; min-width: 0; border: 1px solid var(--pl-line); border-radius: var(--pl-radius-sm); background: var(--pl-paper); color: var(--pl-ink); padding: 0 8px; font: inherit; }
	.link { border: none; background: none; color: var(--pl-seal); text-decoration: underline; font-size: 0.8rem; }
	.desk { display: contents; }
	.index { grid-column: 1; grid-row: 4; min-height: 0; min-width: 0; display: flex; flex-direction: column; gap: 2px; padding: 4px; overflow-y: auto; overscroll-behavior: contain; }
	.index-row { display: flex; align-items: center; gap: 4px; }
	.index-row input { flex: none; width: 12px; height: 12px; min-width: 12px; min-height: 12px; padding: 0; margin: 4px; cursor: pointer; }
	.qbtn { display: flex; flex-direction: column; align-items: flex-start; text-align: left; border: none; border-left: 3px solid transparent; background: none; border-radius: 8px; padding: 8px 6px; min-height: 44px; min-width: 0; width: 100%; overflow-wrap: anywhere; color: var(--pl-ink); }
	.qbtn:hover, .qbtn.active { background: var(--pl-raised); }
	.qbtn.active { border-left-color: var(--pl-seal); font-weight: 600; }
	.qbtn small { font-size: 0.72rem; color: var(--pl-ink-soft); }
	.pane { grid-column: 2; grid-row: 1 / -1; min-width: 0; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 0 16px; border-left: 1px solid var(--pl-line); }
	.question-block { scroll-margin-top: 12px; border-bottom: 1px solid var(--pl-line); padding: 12px 0 24px; margin-bottom: 24px; }
	.more { padding: 16px 0; text-align: center; }
	.empty { grid-column: 2; grid-row: 1 / -1; padding: 18px; }
	.pl-error { position: absolute; top: 0; right: 16px; z-index: 11; max-width: 60%; background: var(--pl-surface); }
	footer { grid-column: 1; grid-row: 5; min-width: 0; padding: 8px; border-top: 1px solid var(--pl-line); }
	footer > span { font-size: 0.75rem; }
	.btns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; margin-top: 6px; }
	.btns button { justify-content: center; height: 28px; min-height: 28px; padding: 2px 4px; min-width: 0; border-radius: 3px; font-size: 0.75rem; line-height: 1; white-space: nowrap; }
	@media (max-width: 760px) {
		.dialog { grid-template-columns: 108px minmax(0, 1fr); }
		header { flex-direction: column-reverse; padding: 4px; }
		header h2 { font-size: 0.72rem; }
		.tabs button { font-size: 0.75rem; }
		.configuration { margin: 4px; }
		.bar { width: min(400px, calc(100vw - 120px)); }
		.index { padding: 2px; }
		.index-row { gap: 0; }
		.qbtn { padding: 6px 2px; }
		.qbtn small { font-size: 0.65rem; }
		.pane { padding: 0 8px; }
		footer { padding: 4px; }
		.btns button { font-size: 0.68rem; padding: 2px; }
	}
</style>
