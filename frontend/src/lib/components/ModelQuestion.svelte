<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { qtypeLabel } from '$lib/qtypes.js';
	import Segments from '$lib/components/Segments.svelte';
	import AddToCart from '$lib/components/AddToCart.svelte';

	let { item, selected = false, disabled = false, reason = '', mode = 'section', onRemove, onToggle, onAdd } = $props();
	let element = $state(null);
	let question = $state(null);
	let paper = $state(null);
	let loading = $state(true);
	let error = $state('');
	let live = true;
	const details = $derived(question ?? item);
	const source = $derived(paper ?? item.paper ?? item);

	async function load() {
		loading = true;
		error = '';
		try {
			const [q, p] = await Promise.all([api.getQuestion(item.paperId, item.number, item.library), api.getPaper(item.paperId, item.library)]);
			if (!live) return;
			question = q;
			paper = p;
		} catch (e) {
			if (live) error = e.message;
		} finally {
			if (live) loading = false;
		}
	}

	onMount(() => {
		live = true;
		const observer = new IntersectionObserver((entries) => {
			if (entries.some((entry) => entry.isIntersecting)) { observer.disconnect(); load(); }
		}, { root: element.closest('.pane'), rootMargin: '600px' });
		observer.observe(element);
		return () => { live = false; observer.disconnect(); };
	});
	let showSolution = $state(false);
	let showQImage = $state(false);
	let imageOk = $state(true);
	const sourceHref = (action) => item.library === 'ejee' ? `/ejee/library/${item.paperId}?q=${encodeURIComponent(item.number)}` : `/archive/${encodeURIComponent(item.paperId)}?${new URLSearchParams({ from: 'search', q: String(item.number), action })}`;
	const renderUrl = () => `/api/papers/${item.paperId}/questions/${encodeURIComponent(item.number)}/render?part=question`;

</script>

<article bind:this={element} class="question" class:selected aria-label={`Paper ${item.paperId}, question ${item.number}`}>
	<div class="heading">
		<h2 class="qtitle">Question {item.number}</h2>
		{#if mode === 'section'}
		<label><input type="checkbox" checked={selected} {disabled} onchange={onToggle} /> Select question {item.number}</label>
		<button type="button" class="pl-btn pl-btn-primary" disabled={disabled || !question || loading || !!error}
			onclick={() => onAdd({ ...item, ...question })}>Add to section</button>
		{:else if mode === 'cart'}
			<button type="button" class="pl-btn" onclick={onRemove}>Remove from cart</button>
		{:else}
			<AddToCart item={{ ...item, qtype: details.qtype, difficulty: details.difficulty, exam: source.exam, year: source.year, institute: source.institute }} variant="tool" />
		{/if}
	</div>
	<p class="source">Source: {source.title || `Paper ${item.paperId}`}{source.institute ? ` · ${source.institute}` : ''}{source.exam ? ` · ${source.exam}` : ''}{source.year ? ` · ${source.year}` : ''} · Q{item.number}</p>
	<div class="tags">
		<span>{qtypeLabel(details.qtype)}</span>
		<span>{details.difficulty || 'Not graded'}</span>
	</div>
	{#if loading}
		<p class="pl-sub" role="status">Loading full question…</p>
	{:else if error}
		<p class="pl-error" role="alert">{error}</p>
		<button type="button" class="pl-btn" onclick={load}>Retry</button>
	{:else if question}
		<div class="topics">
			<strong>Tagging</strong>
			{#each question.topics ?? [] as topic (topic.code)}
				<span>{topic.path || topic.name || topic.code}{topic.auto ? ' (auto)' : ''}</span>
			{:else}
				<span class="pl-sub">Untagged</span>
			{/each}
		</div>
		<div class="statement">
			<svelte:boundary>
				<Segments segments={question.question} zoomable />
				{#snippet failed()}
					<p class="pl-error">Could not display this question.</p>
				{/snippet}
			</svelte:boundary>
		</div>
		<div class="row">
			{#if mode === 'search'}
				{#each [['solution', 'Show solution'], ['image', 'Render question as image'], ['classify', 'Edit classification'], ['figures', 'Manage figures']] as [action, label] (action)}
					<a class="pl-btn" href={sourceHref(action)} target="_blank" rel="noopener" title={`${label} in source paper`}>{label}</a>
				{/each}
			{:else}
			<button type="button" class="pl-btn" onclick={() => (showSolution = !showSolution)}>{showSolution ? 'Hide solution' : 'Show solution'}</button>
			{#if item.library !== 'ejee'}<button type="button" class="pl-btn" onclick={() => { showQImage = !showQImage; imageOk = true; }}>{showQImage ? 'Hide compiled image' : 'Render question as image'}</button>{/if}
			{/if}
		</div>
		{#if showQImage}
			{#if imageOk}<img class="compiled" src={renderUrl()} alt="Compiled question" onerror={() => (imageOk = false)} />
			{:else}<p class="pl-sub">TeX engine unavailable - the view above stands.</p>{/if}
		{/if}
		{#if showSolution}
			<div class="statement solution">
				<svelte:boundary>
					<Segments segments={question.solution} zoomable />
					{#snippet failed()}<p class="pl-error">Could not display this solution.</p>{/snippet}
				</svelte:boundary>
			</div>
		{/if}
	{/if}
	{#if reason}<p class="pl-sub" role="status">{reason}</p>{/if}
</article>

<style>
	.question { width: 100%; box-sizing: border-box; min-height: 260px; max-width: 1000px; min-width: 0; padding: 0 4px 24px; }
	.heading { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }
	.heading label { display: inline-flex; gap: 8px; align-items: center; font-size: 0.85rem; margin-left: auto; }
	.qtitle { font-family: 'Roboto', Inter, system-ui, sans-serif; font-size: 1.75rem; font-weight: 600; margin: 4px 0 10px; }
	.source { font-size: 0.85rem; color: var(--pl-ink-soft); overflow-wrap: anywhere; }
	.tags { display: flex; align-items: center; gap: 12px; margin: 0 0 22px; font-size: 0.85rem; color: var(--pl-ink-soft); }
	.tags span:first-child { background: var(--pl-raised); border: 1px solid var(--pl-line); border-radius: 6px; padding: 3px 10px; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.04em; color: var(--pl-ink); }
	.topics { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px; margin: 0 0 8px; font-size: 0.82rem; }
	.topics strong { padding: 4px 2px; color: var(--pl-ink-soft); }
	.topics span { background: var(--pl-surface); border: 1px solid var(--pl-line); border-radius: 6px; padding: 3px 10px; font-size: 0.8rem; max-width: 100%; overflow-wrap: anywhere; }
	.statement { overflow-wrap: anywhere; font-size: 17.5px; line-height: 1.7; max-width: 1000px; }
	.statement :global(.md p) { margin: 0.75em 0; }
	.row { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0 4px; }
	.compiled { max-width: 100%; border: 1px solid var(--pl-line); border-radius: var(--pl-radius-sm); margin: 8px 0; }
	.solution { border-top: 1px solid var(--pl-line); padding-top: 12px; }
	@media (max-width: 760px) { .qtitle { font-size: 1.35rem; } .statement { font-size: 16px; } }
</style>
