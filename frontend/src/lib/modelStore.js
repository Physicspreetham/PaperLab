/**
 * Model paper draft store (`pl-model-v1`): one working model paper kept in the
 * browser, same hardening idea as the Paper Builder drafts. A model paper is a
 * builder-shaped draft (sections -> blockIds, blocks, keyOverride) so numbering,
 * the question/answer sheets and the Word/PDF exports are all reused, plus the
 * exam `pattern` (sections, marks, instructions) and the options it was
 * generated with (so "fill" / "swap" draw from the same scope).
 */
import { browser } from '$app/environment';
import { writable, derived } from 'svelte/store';
import { newBlockId, setKeyOverride } from './builderModel.js';
import { assignNumbers, flattenDraft } from './numbering.js';

export const MODEL_KEY = 'pl-model-v1';
const VERSION = 1;

const now = () => new Date().toISOString();

function validate(raw) {
	if (!raw || typeof raw !== 'object' || !raw.pattern || !Array.isArray(raw.pattern.sections)) return null;
	const blocks = {};
	for (const [id, b] of Object.entries(raw.blocks ?? {})) {
		if (b && typeof b.paperId === 'number' && b.number != null) {
			blocks[id] = { ...b, id, number: String(b.number), qtype: String(b.qtype ?? 'unknown') };
		}
	}
	const seen = new Set();
	const sections = raw.pattern.sections.map((ps) => {
		const have = (raw.sections ?? []).find((s) => s.id === ps.id);
		const ids = (have?.blockIds ?? []).filter((id) => blocks[id] && !seen.has(id) && seen.add(id));
		return { id: ps.id, atype: ps.type, blockIds: ids };
	});
	return {
		version: VERSION,
		title: String(raw.title ?? ''),
		pattern: raw.pattern,
		options: raw.options ?? {},
		sections,
		blocks,
		keyOverride: raw.keyOverride && typeof raw.keyOverride === 'object' ? raw.keyOverride : {},
		createdAt: raw.createdAt ?? now(),
		updatedAt: raw.updatedAt ?? now()
	};
}

function load() {
	if (!browser) return null;
	try {
		const raw = localStorage.getItem(MODEL_KEY);
		return raw ? validate(JSON.parse(raw)) : null;
	} catch {
		return null;
	}
}

export const modelStore = writable(load());

if (browser) {
	modelStore.subscribe((d) => {
		try {
			if (d) localStorage.setItem(MODEL_KEY, JSON.stringify(d));
			else localStorage.removeItem(MODEL_KEY);
		} catch {
			/* quota/private mode: stay in memory */
		}
	});
	window.addEventListener('storage', (e) => {
		if (e.key !== MODEL_KEY) return;
		try {
			modelStore.set(e.newValue ? validate(JSON.parse(e.newValue)) : null);
		} catch {
			/* ignore cross-tab garbage */
		}
	});
}

export const modelOrder = derived(modelStore, ($d) => ($d ? flattenDraft($d) : []));
export const modelNumbering = derived(modelOrder, ($o) => assignNumbers($o));

const toBlock = (it) => ({
	id: newBlockId(),
	paperId: it.paperId,
	number: String(it.number),
	qtype: it.qtype || 'unknown',
	difficulty: it.difficulty ?? null,
	chapter: it.chapter ?? ''
});

const touch = (d) => ({ ...d, updatedAt: now() });

/** Place items in a section (skips questions already in the paper). */
function addItems(d, sid, items, { replace = false } = {}) {
	const sections = d.sections.map((s) => ({ ...s, blockIds: [...s.blockIds] }));
	const blocks = { ...d.blocks };
	const sec = sections.find((s) => s.id === sid);
	if (!sec) return d;
	if (replace) {
		for (const id of sec.blockIds) delete blocks[id];
		sec.blockIds = [];
	}
	const have = new Set(Object.values(blocks).map((b) => `${b.paperId}::${b.number}`));
	for (const it of items) {
		const k = `${it.paperId}::${it.number}`;
		if (have.has(k)) continue;
		have.add(k);
		const b = toBlock(it);
		blocks[b.id] = b;
		sec.blockIds.push(b.id);
	}
	return touch({ ...d, sections, blocks });
}

export const model = {
	/** Start a new model paper from a pattern and the generator's picks ([{id, items}]). */
	create({ pattern, options, title, picks = [] }) {
		let d = {
			version: VERSION,
			title: String(title ?? '').trim(),
			pattern,
			options,
			sections: pattern.sections.map((s) => ({ id: s.id, atype: s.type, blockIds: [] })),
			blocks: {},
			keyOverride: {},
			createdAt: now(),
			updatedAt: now()
		};
		for (const p of picks) d = addItems(d, p.id, p.items);
		modelStore.set(d);
	},
	clear() {
		modelStore.set(null);
	},
	setTitle(title) {
		modelStore.update((d) => (d ? touch({ ...d, title: String(title ?? '').slice(0, 120) }) : d));
	},
	/** Replace the pattern (after the user corrected marks/minutes); keeps every question. */
	setPattern(pattern) {
		modelStore.update((d) => (d ? touch({ ...d, pattern }) : d));
	},
	addToSection(sid, items) {
		modelStore.update((d) => (d ? addItems(d, sid, items) : d));
	},
	replaceSection(sid, items) {
		modelStore.update((d) => (d ? addItems(d, sid, items, { replace: true }) : d));
	},
	/** Put `item` where block `blockId` was (same section, same place). */
	swap(blockId, item) {
		modelStore.update((d) => {
			if (!d || !d.blocks[blockId]) return d;
			const sections = d.sections.map((s) => ({ ...s, blockIds: [...s.blockIds] }));
			const sec = sections.find((s) => s.blockIds.includes(blockId));
			if (!sec) return d;
			const blocks = { ...d.blocks };
			delete blocks[blockId];
			const nb = toBlock(item);
			blocks[nb.id] = nb;
			sec.blockIds[sec.blockIds.indexOf(blockId)] = nb.id;
			const keyOverride = Object.fromEntries(Object.entries(d.keyOverride).filter(([k]) => !k.startsWith(`${blockId}:`)));
			return touch({ ...d, sections, blocks, keyOverride });
		});
	},
	removeBlock(blockId) {
		modelStore.update((d) => {
			if (!d || !d.blocks[blockId]) return d;
			const blocks = { ...d.blocks };
			delete blocks[blockId];
			const sections = d.sections.map((s) => ({ ...s, blockIds: s.blockIds.filter((id) => id !== blockId) }));
			const keyOverride = Object.fromEntries(Object.entries(d.keyOverride).filter(([k]) => !k.startsWith(`${blockId}:`)));
			return touch({ ...d, sections, blocks, keyOverride });
		});
	},
	moveBlock(blockId, dir) {
		modelStore.update((d) => {
			if (!d) return d;
			const sections = d.sections.map((s) => ({ ...s, blockIds: [...s.blockIds] }));
			const sec = sections.find((s) => s.blockIds.includes(blockId));
			if (!sec) return d;
			const i = sec.blockIds.indexOf(blockId);
			const j = i + (dir < 0 ? -1 : 1);
			if (j < 0 || j >= sec.blockIds.length) return d;
			[sec.blockIds[i], sec.blockIds[j]] = [sec.blockIds[j], sec.blockIds[i]];
			return touch({ ...d, sections });
		});
	},
	setOverride(blockId, subIndex, text) {
		modelStore.update((d) => (d ? setKeyOverride(d, blockId, subIndex, text) : d));
	}
};
