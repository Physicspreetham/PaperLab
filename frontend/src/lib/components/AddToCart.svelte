<script>
	import { activeCart, carts } from '$lib/carts.js';
	import CartIcon from '$lib/components/CartIcon.svelte';

	let { item, variant = 'chip' } = $props();

	const inCart = $derived(
		!!$activeCart?.items.some(
			(it) => it.paperId === item.paperId && String(it.number) === String(item.number)
		)
	);

	function toggle(e) {
		// The search card nests this button inside its link: swallow the
		// click so it toggles the cart instead of opening the question.
		e?.stopPropagation();
		e?.preventDefault();
		if (inCart) carts.remove(item.paperId, item.number);
		else carts.add(item);
	}
</script>

<button
	type="button"
	class="cartbtn {variant}"
	class:in={inCart}
	onclick={toggle}
	title={inCart
		? `Remove question ${item.number} from ${$activeCart?.name ?? 'cart'}`
		: `Add question ${item.number} to ${$activeCart?.name ?? 'cart'}`}
	aria-pressed={inCart}
	aria-label={inCart
		? `Remove question ${item.number} from cart`
		: `Add question ${item.number} to cart`}
>
	<CartIcon size={variant === 'tool' ? 16 : 14} />
</button>

<style>
	.cartbtn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--pl-line);
		background: var(--pl-surface);
		color: var(--pl-ink-soft);
		cursor: pointer;
		flex-shrink: 0;
		padding: 0;
		min-height: 0;
		min-width: 0;
		box-sizing: border-box;
	}
	.cartbtn:hover {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.cartbtn.in {
		background: var(--pl-pine-soft);
		border-color: var(--pl-pine);
		color: var(--pl-pine);
	}
	/* Search-card chips row: same height as the type chip (~22px). */
	.cartbtn.chip {
		width: 28px;
		height: 22px;
		border-radius: 6px;
	}
	/* Reader title row: match the editlink tool button. */
	.cartbtn.tool {
		width: 34px;
		height: 34px;
		border-radius: var(--pl-radius-sm);
	}
</style>
