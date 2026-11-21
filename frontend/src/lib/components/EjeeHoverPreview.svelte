<script>
	let { row, index, total, sourceToken, selected, disabled, onToggle, onFullscreen, onClose, onWheel, onEnter, onLeave, neighbours = [] } = $props();
	let loading = $state(true), failed = $state(false), area = $state(null), shownWidth = $state(undefined);
	// Never enlarge small sources, never exceed reading width, always fit the fixed panel.
	function fit(img) {
		const nw = img.naturalWidth, nh = img.naturalHeight;
		if (!nw || !area) return;
		const cs = getComputedStyle(area), aw = area.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight), ah = area.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
		shownWidth = Math.floor(nw * Math.min(1, 900 / nw, aw / nw, ah / nh));
	}
	const urlFor = r => `/api/ejee/questions/${r.id}/preview?size=full&source_token=${encodeURIComponent(sourceToken)}`;
	const imageUrl = $derived(urlFor(row));
	$effect(() => { row.id; loading = true; failed = false; shownWidth = undefined; });
	// Warm the cache for the questions the user is likely to slide to next.
	$effect(() => { for (const n of neighbours) if (n?.ready) new Image().src = urlFor(n); });
	function wheel(node) {
		const handler = event => onWheel(event);
		node.addEventListener('wheel', handler, { passive: false });
		return { destroy() { node.removeEventListener('wheel', handler); } };
	}
</script>

<aside class="hover-preview" role="dialog" aria-label={`Preview of ${row.title}`} aria-modal="false" onmouseenter={onEnter} onmouseleave={onLeave} use:wheel>
	<div class="image-area" bind:this={area} aria-busy={loading}>
		<button class="fs" type="button" aria-label="Open fullscreen viewer" title="Fullscreen (F)" onclick={onFullscreen}>⛶</button>
		{#if loading && !failed}<p class="status" role="status">Loading question image…</p>{/if}
		{#if failed}<p class="status" role="alert">Could not load this image.</p>{/if}
		{#key row.id}<img src={imageUrl} alt={`Full source question: ${row.title}`} style:width={shownWidth ? `${shownWidth}px` : undefined} style:visibility={shownWidth ? 'visible' : 'hidden'} onload={e => { fit(e.currentTarget); loading = false; }} onerror={() => { loading = false; failed = true; }} />{/key}
	</div>
	<div class="bar">
		<div class="line">
			<span class="lbl">LEVEL</span><span class="chip level">{row.difficulty || 'Not graded'}</span>
			<span class="lbl">MODEL</span><span class="chip model">{row.qtype || 'Not tagged'}</span>
			<strong class="source" title={row.source || ''}>{row.source || 'Not specified'}</strong>
		</div>
		<div class="line">
			<span class="path" title={row.path || ''}>{row.path || 'Not tagged'}</span>
			<span class="count" title={row.title}>{index + 1} / {total.toLocaleString()} · scroll for more</span>
			<button class="btn" type="button" {disabled} aria-pressed={selected} title="Add to cart (C)" onclick={() => onToggle(!selected)}>{selected ? '✓ Added to cart' : '🛒 Add to cart'}</button>
			<button class="btn" type="button" aria-label="Close preview" title="Close (Esc)" onclick={onClose}>✕</button>
		</div>
	</div>
</aside>

<style>
	.hover-preview { position:fixed; z-index:60; top:50%; left:50%; transform:translate(-50%,-50%); width:min(94vw,1000px); height:min(88vh,720px); display:flex; flex-direction:column; background:#fff; color:var(--pl-ink); font-family:var(--pl-font-ui); font-size:.85rem; border:1px solid var(--pl-line); border-radius:var(--pl-radius-md); box-shadow:var(--pl-shadow-md); overflow:hidden; }
	.image-area { position:relative; flex:1; min-height:0; display:flex; align-items:flex-start; justify-content:flex-start; padding:22px 28px; background:#fff; overflow:hidden; overscroll-behavior:contain; }
	.image-area img { display:block; flex:none; width:auto; height:auto; max-width:none; max-height:none; background:#fff; }
	.status { position:absolute; top:12px; left:12px; margin:0; padding:6px 10px; background:var(--pl-raised); color:var(--pl-ink); border-radius:var(--pl-radius-sm); z-index:1; }
	.fs { position:absolute; top:12px; right:12px; z-index:2; width:32px; height:32px; border:1px solid var(--pl-line); border-radius:var(--pl-radius-sm); background:var(--pl-surface); color:var(--pl-ink); font-size:1rem; cursor:pointer; }
	.fs:hover { background:var(--pl-raised); }
	.bar { background:var(--pl-raised); color:var(--pl-ink); border-top:1px solid var(--pl-line); padding:8px 14px; display:grid; gap:6px; flex-shrink:0; }
	.line { display:flex; align-items:center; gap:10px; flex-wrap:wrap; min-width:0; }
	.lbl { font-family:var(--pl-font-mono); font-size:.7rem; font-weight:600; letter-spacing:.06em; color:var(--pl-ink-soft); }
	.chip { padding:2px 10px; border-radius:var(--pl-radius-pill); font-weight:600; font-size:.78rem; }
	.level { background:var(--pl-pine-soft); color:var(--pl-pine); }
	.model { background:var(--pl-seal-soft); color:var(--pl-seal); }
	.source { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:600; }
	.path { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; padding:4px 10px; border:1px solid var(--pl-line); border-radius:var(--pl-radius-sm); background:var(--pl-surface); }
	.count { white-space:nowrap; color:var(--pl-ink-soft); }
	.btn { min-height:32px; padding:4px 12px; border:1px solid var(--pl-line); border-radius:var(--pl-radius-sm); background:var(--pl-surface); color:var(--pl-ink); font:inherit; font-weight:600; cursor:pointer; white-space:nowrap; }
	.btn:hover:not(:disabled) { background:var(--pl-raised); }
	.btn:disabled { opacity:.4; cursor:default; }
	.btn[aria-pressed=true] { background:var(--pl-seal); border-color:var(--pl-seal); color:#fff; }
	@media(max-width:700px) { .hover-preview { width:calc(100vw - 16px); } .image-area { padding:12px; } }
</style>
