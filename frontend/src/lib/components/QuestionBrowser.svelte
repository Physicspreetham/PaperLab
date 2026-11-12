<script>
	import { onMount } from 'svelte';
	import ModelQuestion from '$lib/components/ModelQuestion.svelte';
	import AddToCart from '$lib/components/AddToCart.svelte';
	import { qtypeLabel } from '$lib/qtypes.js';
	import { itemKey } from '$lib/cartModel.js';
	let { items = [], tools, mode = 'search', onRemove, hasMore = false, loading = false, onMore, onScroll, initialScroll = 0 } = $props();
	let browserElement = $state(null);
	let fullscreen = $state(false);
	let fullscreenError = $state('');
	let pane = $state(null);
	let active = $state('');
	const nodes = new Map();
	const key = (it) => itemKey(it.paperId, it.number, it.library);
	function anchor(node, id) { nodes.set(id, node); return { destroy() { nodes.delete(id); } }; }
	function jump(it) { active = key(it); nodes.get(active)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
	function scroll() {
		onScroll?.(pane.scrollTop);
		const top = pane.getBoundingClientRect().top + 60;
		for (const [id, node] of nodes) if (node.getBoundingClientRect().bottom > top) { active = id; break; }
	}
	function more(node, enabled) {
		let observer;
		function watch(value) {
			observer?.disconnect();
			if (!value) return;
			observer = new IntersectionObserver((entries) => {
				if (entries.some((e) => e.isIntersecting) && hasMore && !loading) onMore?.();
			}, { root: pane, rootMargin: '400px' });
			observer.observe(node);
		}
		watch(enabled);
		return { update: watch, destroy() { observer?.disconnect(); } };
	}
	async function toggleFullscreen() {
		fullscreenError = '';
		try {
			if (document.fullscreenElement === browserElement) await document.exitFullscreen();
			else if (browserElement?.requestFullscreen) await browserElement.requestFullscreen({ navigationUI: 'hide' });
			else fullscreenError = 'Use F11 to enter full screen in this browser.';
		} catch {
			fullscreenError = 'Full screen could not open. Try F11 in your browser.';
		}
	}
	async function back(event) {
		if (document.fullscreenElement === browserElement) {
			event.preventDefault();
			try { await document.exitFullscreen(); } catch { fullscreenError = 'Press Esc to exit full screen.'; }
		} else if (window.history.length > 1) {
			event.preventDefault();
			window.history.back();
		}
	}
	onMount(() => {
		pane.scrollTop = initialScroll;
		const sync = () => { fullscreen = document.fullscreenElement === browserElement; };
		sync();
		document.addEventListener('fullscreenchange', sync);
		return () => document.removeEventListener('fullscreenchange', sync);
	});
</script>

<div class="browser" bind:this={browserElement}>
	<aside>
		<div class="tools">
			<div class="screen-controls">
				<a class="back" href="/" onclick={back}>← Back</a>
				<button type="button" class="back" aria-pressed={fullscreen} onclick={toggleFullscreen}>{fullscreen ? 'Exit full screen' : 'Full screen'}</button>
			</div>
			{#if fullscreenError}<p class="pl-sub" role="status">{fullscreenError}</p>{/if}
			{@render tools()}
		</div>
		<nav class="two-columns" aria-label="Question thumbnails">
			{#each items as item (key(item))}
				<div class="thumbnail" class:active={active === key(item)}>
					<button type="button" class="open-question" aria-current={active === key(item) ? 'true' : undefined} onclick={() => jump(item)}>
						<strong>Q{item.number} · {item.library === 'ejee' ? 'EJEE collection' : 'Paper'} {item.paperId}</strong>
						<span class="preview">{item.preview || 'Open question'}</span>
						{#if item.thumb}<img src={item.thumb} alt={`Question ${item.number} preview`} loading="lazy" />{/if}
					</button>
					<div class="thumbnail-details">
						<small>{item.paper?.exam || item.exam || ''} · {qtypeLabel(item.qtype)}</small>
						{#if mode === 'search'}
							<AddToCart item={{ ...item, exam: item.paper?.exam ?? item.exam ?? '', year: item.paper?.year ?? item.year ?? null, institute: item.paper?.institute ?? item.institute ?? '' }} />
						{/if}
					</div>
				</div>
			{/each}
			{#if hasMore}<button type="button" class="pl-btn" disabled={loading} onclick={onMore}>{loading ? 'Loading…' : 'Load more'}</button>{/if}
		</nav>
	</aside>
	<div class="pane" bind:this={pane} onscroll={scroll}>
		{#each items as item (key(item))}
			<div class="question-block" use:anchor={key(item)}>
				<ModelQuestion {item} {mode} onRemove={() => onRemove?.(item)} />
			</div>
		{:else}<p class="pl-sub empty">{loading ? 'Loading questions…' : 'No questions to display.'}</p>{/each}
		{#if hasMore}
			<div class="more" use:more={!loading}>
				<button type="button" class="pl-btn" disabled={loading} onclick={onMore}>{loading ? 'Loading…' : 'Load more'}</button>
			</div>
		{/if}
	</div>
</div>

<style>
	.browser { display: grid; grid-template-columns: minmax(0, 44%) minmax(0, 1fr); flex: 1; min-height: 0; height: 100%; }
	.browser:fullscreen { width: 100%; height: 100dvh; background: var(--pl-surface); color: var(--pl-ink); }
	.screen-controls { display: flex; flex-wrap: wrap; gap: 6px; }
	aside { min-width: 0; min-height: 0; display: flex; flex-direction: column; border-right: 1px solid var(--pl-line); }
	.tools { padding: 10px; position: relative; z-index: 2; border-bottom: 1px solid var(--pl-line); }
	.back { display: inline-flex; align-items: center; min-height: 28px; padding: 2px 8px; margin-bottom: 8px; border: 1px solid var(--pl-line); border-radius: 3px; color: var(--pl-ink); font-size: 0.8rem; text-decoration: none; }
	nav { flex: 1; min-height: 0; overflow-y: auto; padding: 8px; overscroll-behavior: contain; }
	nav.two-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; align-content: start; align-items: start; }
	nav.two-columns > .pl-btn { grid-column: 1 / -1; }
	.thumbnail { display: flex; flex-direction: column; gap: 8px; width: 100%; box-sizing: border-box; min-width: 0; margin-bottom: 8px; padding: 10px; text-align: left; background: var(--pl-surface); color: var(--pl-ink); border: 1px solid var(--pl-line); border-radius: 4px; }
	.thumbnail.active { border-color: var(--pl-seal); background: var(--pl-raised); }
	.thumbnail img { width: 100%; height: auto; object-fit: contain; background: var(--pl-paper); }
	.thumbnail strong { font-size: 0.82rem; overflow-wrap: anywhere; }
	.preview { font-size: 0.8rem; line-height: 1.5; overflow-wrap: anywhere; }
	.open-question { display: flex; flex-direction: column; gap: 8px; width: 100%; min-width: 0; padding: 0; text-align: left; color: inherit; background: none; border: none; }
	.thumbnail-details { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px; }
	small { font-size: 0.72rem; color: var(--pl-ink-soft); }
	.pane { min-width: 0; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 0 16px; }
	.question-block { scroll-margin-top: 12px; padding-top: 12px; margin-bottom: 24px; border-bottom: 1px solid var(--pl-line); }
	.empty, .more { padding: 16px 0; }
	@media (max-width: 760px) {
		.browser { grid-template-columns: minmax(0, 44%) minmax(0, 1fr); }
		.tools, nav { padding: 4px; }
		nav.two-columns { gap: 4px; }
		.thumbnail { padding: 4px; }
		.thumbnail strong { font-size: 0.68rem; }
		.preview { font-size: 0.7rem; }
		.pane { padding: 0 8px; }
	}
</style>
