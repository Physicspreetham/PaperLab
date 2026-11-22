/**
 * Pure cart-model helpers (no localStorage, no Svelte). carts.js wraps
 * these with persistence. Kept pure so node --test can cover them.
 *
 * Identity: {paperId:number, number:string}. Everything else is a
 * re-fetchable snapshot (plain text + URL strings only — never segments,
 * HTML, or image bytes).
 */

export const CART_SCHEMA_VERSION = 1;
export const MAX_CARTS = 50;
export const MAX_ITEMS_PER_CART = 2000;

const isValidId = (v) => typeof v === 'number' && Number.isFinite(v);
const cleanStr = (v, max = 500) =>
	typeof v === 'string' ? v.slice(0, max) : v == null ? v : String(v).slice(0, max);

export function newId() {
	try {
		if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
	} catch { /* fall through */ }
	return `c-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;
}

export function createCart(name = 'Untitled cart') {
	const now = new Date().toISOString();
	return {
		id: newId(),
		name: String(name ?? 'Untitled cart').slice(0, 80) || 'Untitled cart',
		modelPaperId: null,
		createdAt: now,
		updatedAt: now,
		items: []
	};
}

/** Minimal snapshot for one question. Extra fields are dropped. */
export function toCartItem(src) {
	if (!src || typeof src !== 'object') return null;
	const paperId = typeof src.paperId === 'string' ? parseInt(src.paperId, 10) : src.paperId;
	const number = src.number != null ? String(src.number) : '';
	if (!isValidId(paperId) || !number) return null;
	return {
		paperId,
		number,
		qtype: cleanStr(src.qtype ?? 'unknown', 20) || 'unknown',
		difficulty: src.difficulty ?? null,
		preview: cleanStr(src.preview ?? '', 300),
		thumb: typeof src.thumb === 'string' ? src.thumb.slice(0, 500) : null,
		exam: cleanStr(src.exam ?? '', 80) || '',
		year: src.year ?? null,
		institute: cleanStr(src.institute ?? '', 120) || '',
		addedAt: src.addedAt ?? new Date().toISOString()
	};
}

export const itemKey = (paperId, number) => `${paperId}::${String(number)}`;

export function findItemIndex(cart, paperId, number) {
	const k = itemKey(paperId, number);
	return cart.items.findIndex((it) => itemKey(it.paperId, it.number) === k);
}

/** Add; returns {cart, added:boolean, reason}. Never mutates input. */
export function addItem(cart, src) {
	const item = toCartItem(src);
	if (!item) return { cart, added: false, reason: 'invalid' };
	if (findItemIndex(cart, item.paperId, item.number) !== -1)
		return { cart, added: false, reason: 'duplicate' };
	if (cart.items.length >= MAX_ITEMS_PER_CART)
		return { cart, added: false, reason: 'full' };
	const now = new Date().toISOString();
	return {
		cart: { ...cart, updatedAt: now, items: [...cart.items, item] },
		added: true, reason: 'ok'
	};
}

/** Remove by identity; returns {cart, removed:boolean}. */
export function removeItem(cart, paperId, number) {
	const i = findItemIndex(cart, paperId, number);
	if (i === -1) return { cart, removed: false };
	const items = cart.items.slice();
	items.splice(i, 1);
	return { cart: { ...cart, updatedAt: new Date().toISOString(), items }, removed: true };
}

/** Build the same lightweight snapshot from a reader question or a whole paper. */
export function questionCartSnapshot(paper, question) {
	let preview = '';
	let thumb = null;
	for (const segment of question.question ?? []) {
		if (!preview && segment?.kind === 'text' && typeof segment.html === 'string') {
			preview = segment.html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 300);
		}
		if (!thumb && segment?.kind === 'fig' && segment.url) thumb = segment.url;
		if (preview && thumb) break;
	}
	return {
		paperId: question.paperId ?? paper?.id,
		number: question.number,
		qtype: question.qtype,
		difficulty: question.difficulty ?? null,
		preview,
		thumb,
		exam: paper?.exam ?? '',
		institute: paper?.institute ?? ''
	};
}

/** Add the missing questions, or remove the paper if every current question is in the cart. */
export function togglePaper(cart, paperId, questions) {
	const wanted = new Map();
	for (const src of questions) {
		const item = toCartItem(src);
		if (!item || item.paperId !== paperId) return { cart, action: 'invalid', count: 0 };
		wanted.set(item.number, item);
	}
	if (!wanted.size) return { cart, action: 'empty', count: 0 };
	const have = new Set(
		cart.items.filter((it) => it.paperId === paperId).map((it) => String(it.number))
	);
	const missing = [...wanted.values()].filter((it) => !have.has(it.number));
	if (cart.items.length + missing.length > MAX_ITEMS_PER_CART)
		return { cart, action: 'full', count: 0 };
	const items = missing.length
		? [...cart.items, ...missing]
		: cart.items.filter((it) => it.paperId !== paperId);
	return {
		cart: { ...cart, items, updatedAt: new Date().toISOString() },
		action: missing.length ? 'added' : 'removed',
		count: missing.length || cart.items.length - items.length
	};
}

/** Remove every question of one paper; returns {cart, count}. */
export function removePaper(cart, paperId) {
	const items = cart.items.filter((it) => it.paperId !== paperId);
	const count = cart.items.length - items.length;
	if (!count) return { cart, count: 0 };
	return { cart: { ...cart, items, updatedAt: new Date().toISOString() }, count };
}

/** Validate a parsed store blob; returns {ok, store} with repairs applied. */
export function validateStore(raw) {
	const fresh = () => {
		const c = createCart('My first cart');
		return { version: CART_SCHEMA_VERSION, activeId: c.id, carts: [c] };
	};
	if (!raw || typeof raw !== 'object') return { ok: false, store: fresh() };
	const carts = Array.isArray(raw.carts) ? raw.carts : [];
	const clean = [];
	for (const c of carts.slice(0, MAX_CARTS)) {
		if (!c || typeof c !== 'object') continue;
		const items = Array.isArray(c.items) ? c.items : [];
		const seen = new Set();
		const good = [];
		for (const it of items.slice(0, MAX_ITEMS_PER_CART)) {
			const norm = toCartItem(it);
			if (!norm) continue;
			const k = itemKey(norm.paperId, norm.number);
			if (seen.has(k)) continue; // drop dupes from corrupt/manual edits
			seen.add(k);
			good.push(norm);
		}
		clean.push({
			id: typeof c.id === 'string' && c.id ? c.id : newId(),
			name: String(c.name ?? 'Untitled cart').slice(0, 80) || 'Untitled cart',
			modelPaperId: typeof c.modelPaperId === 'string' && c.modelPaperId ? c.modelPaperId : null,
			createdAt: c.createdAt ?? new Date().toISOString(),
			updatedAt: c.updatedAt ?? new Date().toISOString(),
			items: good
		});
	}
	if (clean.length === 0) {
		const c = createCart('My first cart');
		return { ok: false, store: { version: CART_SCHEMA_VERSION, activeId: c.id, carts: [c] } };
	}
	let activeId = typeof raw.activeId === 'string' ? raw.activeId : null;
	if (!clean.some((c) => c.id === activeId)) activeId = clean[0].id;
	return { ok: true, store: { version: CART_SCHEMA_VERSION, activeId, carts: clean } };
}
