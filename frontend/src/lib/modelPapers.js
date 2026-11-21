import { browser } from '$app/environment';
import { readonly, writable } from 'svelte/store';
import { newId } from './cartModel.js';
import { modelPaperInput, validateModelPapers, withSeededPresets } from './modelPaperModel.js';
import { JEE_PRESET_PAPERS } from './jeePresets.js';

const KEY = 'pl-model-papers-v1';
const SEED_KEY = 'pl-model-papers-seed-v1';

function load() {
	if (!browser) return [];
	try {
		const raw = localStorage.getItem(KEY);
		const papers = raw == null ? [] : validateModelPapers(JSON.parse(raw));
		try {
			// One-time merge: browsers that stored a list before the presets
			// shipped get the missing ones added. Afterwards the stored
			// list is authoritative, so edits and deletes are never
			// overwritten or resurrected.
			if (!localStorage.getItem(SEED_KEY)) {
				const merged = withSeededPresets(papers, JEE_PRESET_PAPERS);
				localStorage.setItem(KEY, JSON.stringify(merged));
				localStorage.setItem(SEED_KEY, '1');
				return merged;
			}
		} catch {
			// Keep the in-memory list if storage is unavailable.
		}
		return papers;
	} catch {
		return [];
	}
}

const store = writable(load());
export const modelPaperList = readonly(store);

if (browser) {
	window.addEventListener('storage', (event) => {
		if (event.key === KEY) store.set(load());
	});
}

function change(update) {
	store.update((papers) => {
		const next = update(papers);
		if (browser) {
			try {
				localStorage.setItem(KEY, JSON.stringify(next));
			} catch {
				// Keep changes available in memory if browser storage is unavailable.
			}
		}
		return next;
	});
}

export const modelPapers = {
	save(id, name, counts) {
		const input = modelPaperInput(name, counts);
		if (input.error) return input;
		const paper = { id: id ?? newId(), ...input };
		change((papers) => papers.some((p) => p.id === paper.id)
			? papers.map((p) => p.id === paper.id ? paper : p)
			: [...papers, paper]);
		return { paper };
	},
	remove(id) {
		change((papers) => papers.filter((p) => p.id !== id));
	}
};
