import { browser } from '$app/environment';
import { readonly, writable } from 'svelte/store';
import { newId } from './cartModel.js';
import { modelPaperInput, validateModelPapers } from './modelPaperModel.js';

const KEY = 'pl-model-papers-v1';
function load() {
	if (!browser) return [];
	try {
		return validateModelPapers(JSON.parse(localStorage.getItem(KEY)));
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
