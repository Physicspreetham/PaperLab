/**
 * Order EJEE questions the way the EJEE syllabus lists their subtopics.
 *
 * Chapters keep the order in which they first appear (the teacher's chosen
 * sequence). Inside a chapter, questions follow the node positions of their
 * week > topic > subtopic in EJEE (increasing), then their existing order.
 * Anything without preserved EJEE tags (other libraries, AI-reclassified
 * imports) stays in its original relative order, grouped at its first position.
 * Pure functions: the fetch lives in loadOrderKeys.
 */
const cache = new Map();

/** {paperId: {number: {chapter_id, sort:[...]}}}; failed papers map to {} so ordering degrades gracefully. */
export async function loadOrderKeys(items, fetcher = async (id) => (await import('./api.js')).api.getEjeeOrder(id)) {
	const ids = [...new Set((items ?? []).filter((i) => i?.library === 'ejee').map((i) => i.paperId))];
	const entries = await Promise.all(ids.map(async (id) => {
		if (!cache.has(id)) cache.set(id, Promise.resolve().then(() => fetcher(id)));
		try {
			return [id, await cache.get(id)];
		} catch {
			cache.delete(id);  // retry next time; ordering degrades to the original order meanwhile
			return [id, {}];
		}
	}));
	return Object.fromEntries(entries);
}

export function clearOrderCache() {
	cache.clear();
}

function compare(a, b) {
	const n = Math.max(a.length, b.length);
	for (let i = 0; i < n; i++) {
		// A question tagged at the topic itself comes before its deeper subtopics.
		const x = a[i] ?? -Infinity;
		const y = b[i] ?? -Infinity;
		if (x !== y) return x < y ? -1 : 1;
	}
	return 0;
}

/** @param items objects with {paperId, number, library}; returns a new array. */
export function orderBySubtopic(items, keys) {
	const groups = new Map();
	(items ?? []).forEach((item, index) => {
		const info = item?.library === 'ejee' ? keys?.[item.paperId]?.[String(item.number)] : null;
		const groupKey = info ? `c:${info.chapter_id ?? 'none'}` : 'other';
		if (!groups.has(groupKey)) groups.set(groupKey, []);
		groups.get(groupKey).push({ item, index, sort: info?.sort ?? null });
	});
	const out = [];
	for (const [key, rows] of groups) {
		if (key !== 'other') rows.sort((a, b) => compare(a.sort, b.sort) || a.index - b.index);
		out.push(...rows.map((r) => r.item));
	}
	return out;
}

/**
 * Where a subtopic title goes: the first block of every run of consecutive EJEE
 * questions that share a subtopic. Returns Map(blockId -> title).
 * @param ordered blocks in document order ({blockId, paperId, number, library})
 */
export function topicHeadings(ordered, keys) {
	const out = new Map();
	let previous = null;
	for (const block of ordered ?? []) {
		const leaf = block?.library === 'ejee' ? keys?.[block.paperId]?.[String(block.number)]?.leaf : null;
		if (leaf && leaf.id !== previous) out.set(block.blockId, leaf.name);
		previous = leaf ? leaf.id : null;
	}
	return out;
}
