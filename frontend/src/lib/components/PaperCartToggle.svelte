<script>
	import { api } from '$lib/api.js';
	import { activeCart, carts } from '$lib/carts.js';
	import { questionCartSnapshot } from '$lib/cartModel.js';
	import CartIcon from '$lib/components/CartIcon.svelte';

	let { paper, expected = 0 } = $props();

	let busy = $state(false);
	let failed = $state(false);
	let fetched = $state(null);

	const inCartCount = $derived(
		$activeCart?.items.filter((it) => it.paperId === paper.id).length ?? 0
	);
	const total = $derived(fetched?.length ?? expected ?? 0);
	const full = $derived(total > 0 && inCartCount >= total);

	async function toggle() {
		if (busy) return;
		if (full) {
			carts.removePaper(paper.id);
			return;
		}
		busy = true;
		failed = false;
		try {
			if (!fetched) fetched = await api.getQuestions(paper.id);
			const snapshots = fetched.map((q) => questionCartSnapshot(paper, q));
			const result = carts.togglePaper(paper.id, snapshots);
			if (result.action !== 'added') failed = true;
		} catch {
			failed = true;
		} finally {
			busy = false;
		}
	}

	const label = $derived(
		busy
			? `Adding paper ${paper.id} to cart…`
			: failed
				? `Couldn't load paper ${paper.id}. Try again.`
				: full
					? `Remove all ${total} questions of paper ${paper.id} from ${$activeCart?.name ?? 'cart'}`
					: inCartCount > 0
						? `Add the remaining questions of paper ${paper.id} to ${$activeCart?.name ?? 'cart'} (${inCartCount} of ${total} in cart)`
						: `Add all ${total} questions of paper ${paper.id} to ${$activeCart?.name ?? 'cart'}`
	);
</script>

<button
	type="button"
	class="papercart"
	class:full
	disabled={busy || total === 0}
	aria-pressed={full}
	aria-label={label}
	title={failed ? "Couldn't load the questions. Try again." : label}
	onclick={toggle}
>
	<CartIcon size={20} />
</button>

<style>
	.papercart {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 44px;
		height: 44px;
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		background: var(--pl-surface);
		color: var(--pl-ink-soft);
		cursor: pointer;
		flex-shrink: 0;
		padding: 0;
		box-sizing: border-box;
	}
	.papercart:hover:not(:disabled) {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.papercart:focus-visible {
		outline: 2px solid var(--pl-focus, var(--pl-seal));
		outline-offset: 2px;
	}
	.papercart.full {
		background: var(--pl-pine-soft);
		border-color: var(--pl-pine);
		color: var(--pl-pine);
	}
	.papercart:disabled {
		opacity: 0.55;
		cursor: wait;
	}
</style>
