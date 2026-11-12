/**
 * In-memory question-detail cache (never persisted). Builder previews and
 * solution views share one fetch per question per session instead of each
 * component refetching. Failures are NOT cached — retry refetches.
 */
import { api } from './api.js';
import { itemKey } from './cartModel.js';

const cache = new Map();

const key = itemKey;

export function getQuestionDetail(paperId, number, library) {
	const k = key(paperId, number, library);
	if (!cache.has(k)) {
		cache.set(
			k,
			api.getQuestion(paperId, number, library).catch((e) => {
				cache.delete(k);
				throw e;
			})
		);
	}
	return cache.get(k);
}

/**
 * Seed one cache entry from an already-fetched detail object (bulk
 * endpoint). Never overwrites: in-flight or settled entries win, so a
 * bulk prefetch can never clobber fresher data. Failures are never
 * seeded, matching getQuestionDetail semantics.
 */
export function seedQuestionDetail(paperId, number, data, library) {
	const k = key(paperId, number, library);
	if (!cache.has(k)) cache.set(k, Promise.resolve(data));
	return cache.get(k);
}

export function dropQuestionDetail(paperId, number, library) {
	cache.delete(key(paperId, number, library));
}
