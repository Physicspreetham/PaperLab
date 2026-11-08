<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import FilterDropdown from '$lib/components/FilterDropdown.svelte';
	import TopicTreePicker from '$lib/components/TopicTreePicker.svelte';
	import QuestionBrowser from '$lib/components/QuestionBrowser.svelte';
	import { qtypeLabel } from '$lib/qtypes.js';
	import {
		PAGE_SIZE,
		activeFilterCount,
		defaultFilters,
		loadSearchState,
		saveSearchState
	} from '$lib/search.js';

	const stored = loadSearchState();

	let filters = $state(stored?.filters ?? defaultFilters());
	let items = $state(stored?.items ?? []);
	let total = $state(stored?.total ?? 0);
	let nextCursor = $state(stored?.nextCursor ?? null);
	let hasMore = $state(stored?.hasMore ?? false);
	let scrollY = $state(stored?.scrollY ?? 0);

	let facets = $state(null);
	let topics = $state([]);
	let loading = $state(!(stored?.items?.length > 0));
	let loadingMore = $state(false);
	let error = $state('');
	let reqId = $state(0);

	const activeCount = $derived(activeFilterCount(filters));
	const shown = $derived(items.length);

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

	$effect(() => {
		saveSearchState({ filters, items, total, nextCursor, hasMore, scrollY });
	});

	async function fetchPage(cursor, append) {
		const id = ++reqId;
		error = '';
		if (append) loadingMore = true;
		else {
			loading = true;
			error = '';
		}
		try {
			const res = await api.searchQuestions(filters, { limit: PAGE_SIZE, cursor });
			if (id !== reqId) return; // stale: filters changed mid-flight
			if (append) items = [...items, ...res.items];
			else items = res.items;
			total = res.total;
			nextCursor = res.nextCursor;
			hasMore = res.hasMore;
		} catch (e) {
			if (id !== reqId) return;
			// Stale cursor (filters changed elsewhere): restart cleanly once.
			if (cursor && String(e.message).startsWith('400') && !append) {
				nextCursor = null;
				return fetchPage(null, false);
			}
			error = e.message;
		} finally {
			if (id === reqId) {
				loading = false;
				loadingMore = false;
			}
		}
	}

	function onFiltersChanged() {
		items = [];
		total = 0;
		nextCursor = null;
		hasMore = false;
		fetchPage(null, false);
	}

	// Any filter edit restarts from page one.
	let filterSig = $state(JSON.stringify(stored?.filters ?? defaultFilters()));
	$effect(() => {
		const sig = JSON.stringify(filters);
		if (sig !== filterSig) {
			filterSig = sig;
			onFiltersChanged();
		}
	});

	function clearAll() {
		filters = defaultFilters();
	}

	function rememberScroll() {
		// Reader scroll position is supplied by QuestionBrowser.
		saveSearchState({ filters, items, total, nextCursor, hasMore, scrollY });
	}

	onMount(async () => {
		try {
			const [f, t] = await Promise.all([
				api.getSearchFacets(),
				api.getTopics().catch(() => [])
			]);
			facets = f;
			topics = t;
		} catch (e) {
			if (items.length === 0) error = e.message;
		} finally {
			if (items.length === 0 && !error) {
				fetchPage(null, false);
			} else {
				loading = false;
			}
		}
	});
</script>

<svelte:head><title>Search Questions - PaperLab</title></svelte:head>
<svelte:window onpagehide={rememberScroll} />

<QuestionBrowser {items} hasMore={hasMore && !error} loading={loading || loadingMore} onMore={() => fetchPage(nextCursor, true)} initialScroll={scrollY} onScroll={(value) => (scrollY = value)}>
{#snippet tools()}
<h1>Search questions</h1>

<div class="bar" role="group" aria-label="Question filters">
	<FilterDropdown label="Type" options={facetOpts.qtype} bind:selected={filters.qtype} format={qtypeLabel} />
	<FilterDropdown label="Difficulty" options={facetOpts.difficulty} bind:selected={filters.difficulty} />
	<FilterDropdown label="Source" options={facetOpts.institute} bind:selected={filters.institute} />
	<FilterDropdown label="Exam" options={facetOpts.exam} bind:selected={filters.exam} />
	<FilterDropdown label="Year" options={facetOpts.year} bind:selected={filters.year} />
	<TopicTreePicker nodes={topics} counts={filters.include_supporting ? {} : topicCounts} bind:selected={filters.topic} />
	<label><input type="checkbox" bind:checked={filters.include_supporting} /> Include supporting concepts</label>
	{#if activeCount > 0}
		<button type="button" class="clear-all" onclick={clearAll}>
			Clear all · {activeCount}
		</button>
	{/if}
</div>

{#if loading}
	<p class="pl-sub">Loading questions…</p>
{:else if error && items.length === 0}
	<div class="pl-error" role="alert">
		<strong>Could not reach the backend.</strong>
		<p class="pl-mono">{error}</p>
		<button type="button" class="pl-btn" onclick={() => fetchPage(null, false)}>Retry</button>
	</div>
{:else}
	<p class="count" aria-live="polite"><strong>{total} question{total === 1 ? '' : 's'}</strong>{shown < total ? ` · showing ${shown}` : ''}</p>
	{#if items.length === 0}
		<div class="pl-card">
			<p>No questions match these filters. Clear a filter or two to widen the net.</p>
			<button type="button" class="pl-btn" onclick={clearAll}>Clear all filters</button>
		</div>

	{/if}
{/if}

{#if error && items.length > 0}<p class="pl-error" role="alert">{error}</p><button type="button" class="pl-btn" onclick={() => fetchPage(nextCursor, true)}>Retry loading more</button>{/if}
{/snippet}
</QuestionBrowser>

<style>
	h1 { font-size: 1.1rem; margin: 0 0 8px; }
	.bar { display: flex; flex-wrap: wrap; gap: 8px; }
	.clear-all { border: 1px solid var(--pl-line); border-radius: 3px; background: none; color: var(--pl-seal); padding: 4px; }
	.count, .pl-sub { font-size: 0.8rem; }
</style>
