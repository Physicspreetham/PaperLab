<script>
	let { selected = false, disabled = false, title = 'question', onToggle } = $props();
</script>

<button type="button" class="import-cart" class:selected {disabled} aria-pressed={selected}
	aria-label={`${selected ? 'Remove' : 'Add'} ${title} ${selected ? 'from' : 'to'} import cart`}
	title={selected ? 'Remove from import cart' : 'Add to import cart'} onclick={onToggle}>
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3h2l3 13h11l3-9H6"/><circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/>{#if selected}<path d="m10 10 2 2 4-4"/>{/if}</svg>
</button>

<style>
	.import-cart { display:inline-flex; align-items:center; justify-content:center; width:42px; height:42px; flex:none; padding:8px; border:1px solid var(--pl-line); border-radius:8px; background:var(--pl-surface); color:var(--pl-ink); cursor:pointer; }
	.import-cart.selected { background:var(--pl-pine-soft); border-color:var(--pl-pine); color:var(--pl-pine); }
	.import-cart svg { width:23px; height:23px; }
	.import-cart:disabled { opacity:.45; cursor:not-allowed; }
</style>
