import { MAX_ITEMS_PER_CART } from './cartModel.js';
import { isParagraphId } from './paragraph.js';
import { SECTION_TYPES, qtypeLabel } from './qtypes.js';

export const LEGACY_PARAGRAPH_TYPE = 'paragraph';
export const MODEL_PAPER_TYPES = SECTION_TYPES.filter((type) => type !== 'unknown');
const knownTypes = new Set(MODEL_PAPER_TYPES);
export const MAX_MODEL_QUESTIONS = MAX_ITEMS_PER_CART;

const names = {
	scq: 'Single correct',
	msq: 'Multiple correct',
	int: 'Integer',
	nni: 'Non-negative integer',
	num: 'Numerical',
	mtx: 'Matrix match',
	mix: 'Mixed'
};

export const isParagraphType = (type) => type?.startsWith('par-');

export function modelTypeLabel(type) {
	const label = isParagraphType(type) ? `Paragraph: ${names[type.slice(4)]}` : names[type];
	return `${label} (${qtypeLabel(type).toUpperCase()})`;
}

export function modelQuantity(type, count) {
	const plural = count !== 1;
	if (type === LEGACY_PARAGRAPH_TYPE) return `${count} paragraph group${plural ? 's' : ''}`;
	if (isParagraphType(type)) return `${count} ${names[type.slice(4)].toLowerCase()} paragraph group${plural ? 's' : ''}`;
	return `${count} ${names[type].toLowerCase()} question${plural ? 's' : ''}`;
}

export function modelPaperInput(name, counts, { allowLegacy = false } = {}) {
	const cleanName = typeof name === 'string' ? name.trim() : '';
	if (!cleanName || cleanName.length > 80) return { error: 'Enter a name of up to 80 characters.' };
	const cleanCounts = {};
	let total = 0;
	const types = allowLegacy ? [...MODEL_PAPER_TYPES, LEGACY_PARAGRAPH_TYPE] : MODEL_PAPER_TYPES;
	for (const type of types) {
		const count = counts?.[type] ?? 0;
		if (!Number.isInteger(count) || count < 0 || count > MAX_MODEL_QUESTIONS)
			return { error: 'Use whole numbers from 0 to 2,000.' };
		if (count > 0) cleanCounts[type] = count;
		total += count;
	}
	if (!total) return { error: 'Add at least one question type.' };
	if (total > MAX_MODEL_QUESTIONS) return { error: 'A model paper can have at most 2,000 items.' };
	return { name: cleanName, counts: cleanCounts };
}

export function validateModelPapers(raw) {
	if (!Array.isArray(raw)) return [];
	const ids = new Set();
	const papers = [];
	for (const entry of raw) {
		if (typeof entry?.id !== 'string' || !entry.id || ids.has(entry.id)) continue;
		const paper = modelPaperInput(entry.name, entry.counts, { allowLegacy: true });
		if (paper.error) continue;
		papers.push({ id: entry.id, ...paper });
		ids.add(entry.id);
	}
	return papers;
}

/** Add any missing JEE presets in front, keeping the user's own papers after. */
export function withSeededPresets(papers, presets) {
	const ids = new Set(papers.map((p) => p.id));
	return [
		...validateModelPapers(presets).filter((p) => !ids.has(p.id)),
		...papers
	];
}

/** Group in the shared type order, preserving the original order within a type. */
export function groupCartItems(items) {
	const groups = SECTION_TYPES.map((type) => ({ type, items: [] }));
	const byType = new Map(groups.map((group) => [group.type, group.items]));
	for (const item of items) {
		const { number, qtype } = item;
		const type = !isParagraphType(qtype) && isParagraphId(number) ? `par-${qtype}` : qtype;
		byType.get(knownTypes.has(type) ? type : 'unknown').push(item);
	}
	return groups;
}

export function compareModelPaper(targets, groups) {
	const additions = [];
	const removals = [];
	const legacyTarget = targets[LEGACY_PARAGRAPH_TYPE];
	let legacyCount = 0;
	function compare(type, delta) {
		if (delta > 0) additions.push({ type, count: delta, action: 'Add' });
		if (delta < 0) removals.push({ type, count: -delta, action: 'Remove' });
	}
	for (const { type, items } of groups) {
		if (type === 'unknown') continue;
		if (legacyTarget && isParagraphType(type)) {
			legacyCount += items.length;
		} else {
			compare(type, (targets[type] ?? 0) - items.length);
		}
	}
	if (legacyTarget) compare(LEGACY_PARAGRAPH_TYPE, legacyTarget - legacyCount);
	return [...additions, ...removals];
}
