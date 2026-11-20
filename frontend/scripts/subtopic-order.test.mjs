#!/usr/bin/env node
/** Run: node --test frontend/scripts/subtopic-order.test.mjs */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { orderBySubtopic, loadOrderKeys, clearOrderCache } from '../src/lib/subtopicOrder.js';
import { createDraft, importBlocks, setAssignmentOrder } from '../src/lib/builderModel.js';

const E = (paperId, number) => ({ paperId, number: String(number), library: 'ejee' });
const keys = {
	7: {
		1: { chapter_id: 39, sort: [2, 1] }, 2: { chapter_id: 39, sort: [1, 3] }, 3: { chapter_id: 39, sort: [1, 1] },
		4: { chapter_id: 39, sort: [1, 3] }, 5: { chapter_id: 12, sort: [5] }, 6: { chapter_id: 12, sort: [1] },
		7: { chapter_id: 39, sort: [1, 3, 2] }, 8: { chapter_id: 39, sort: [1, 3] }
	}
};

describe('orderBySubtopic', () => {
	it('groups a chapter by increasing EJEE subtopic position, stable for equal subtopics', () => {
		const out = orderBySubtopic([1, 2, 3, 4, 7, 8].map((n) => E(7, n)), keys);
		assert.deepEqual(out.map((i) => i.number), ['3', '2', '4', '8', '7', '1']);
	});
	it('keeps chapters in first-appearance order and sorts inside each', () => {
		const out = orderBySubtopic([5, 1, 6, 3].map((n) => E(7, n)), keys);
		assert.deepEqual(out.map((i) => i.number), ['6', '5', '3', '1']);
	});
	it('leaves untagged and non-EJEE items in their original relative order', () => {
		const items = [{ paperId: 3, number: '9' }, E(7, 1), E(9, 4), E(7, 3), { paperId: 3, number: '2' }];
		const out = orderBySubtopic(items, keys);
		// non-EJEE and untagged share the "other" group, which keeps its input order
		const other = out.filter((i) => !keys[i.paperId]?.[i.number]).map((i) => `${i.paperId}:${i.number}`);
		assert.deepEqual(other, ['3:9', '9:4', '3:2']);
		assert.deepEqual(out.filter((i) => keys[i.paperId]?.[i.number]).map((i) => i.number), ['3', '1']);
	});
	it('does not mutate its input', () => {
		const input = [E(7, 1), E(7, 3)];
		orderBySubtopic(input, keys);
		assert.deepEqual(input.map((i) => i.number), ['1', '3']);
	});
});

describe('loadOrderKeys', () => {
	it('fetches once per paper and tolerates failures', async () => {
		clearOrderCache();
		const calls = [];
		const fetcher = async (id) => { calls.push(id); if (id === 2) throw new Error('down'); return { 1: { chapter_id: 1, sort: [1] } }; };
		const out = await loadOrderKeys([E(1, 1), E(1, 2), E(2, 1), { paperId: 5, number: '1' }], fetcher);
		assert.deepEqual(out, { 1: { 1: { chapter_id: 1, sort: [1] } }, 2: {} });
		assert.deepEqual(calls.sort(), [1, 2]);
	});
});

describe('setAssignmentOrder', () => {
	it('reorders only with exactly the same blocks', () => {
		const d = importBlocks(createDraft('assignment'), [E(7, 1), E(7, 2), E(7, 3)]).draft;
		const ids = d.sections[0].blockIds;
		const next = setAssignmentOrder(d, [ids[2], ids[0], ids[1]]);
		assert.deepEqual(next.sections[0].blockIds, [ids[2], ids[0], ids[1]]);
		assert.equal(setAssignmentOrder(d, ids), d);
		assert.equal(setAssignmentOrder(d, [ids[0], ids[1]]), null);
		assert.equal(setAssignmentOrder(d, [ids[0], ids[0], ids[1]]), null);
		assert.equal(setAssignmentOrder(createDraft('paper'), []), null);
	});
});

import { topicHeadings } from '../src/lib/subtopicOrder.js';
describe('topicHeadings', () => {
	const leaf = (id, name) => ({ leaf: { id, name } });
	const k = { 7: { 1: leaf(10, 'A. Capacitance'), 2: leaf(10, 'A. Capacitance'), 3: leaf(11, 'B. Dielectrics'), 4: leaf(10, 'A. Capacitance') } };
	const blk = (blockId, number, library = 'ejee', paperId = 7) => ({ blockId, paperId, number: String(number), library });
	it('titles the first question of each run, again when the subtopic changes back', () => {
		const m = topicHeadings([blk('a', 1), blk('b', 2), blk('c', 3), blk('d', 4)], k);
		assert.deepEqual([...m], [['a', 'A. Capacitance'], ['c', 'B. Dielectrics'], ['d', 'A. Capacitance']]);
	});
	it('gives non-EJEE or untagged questions no title and restarts the run after them', () => {
		const m = topicHeadings([blk('a', 1), blk('x', 9, 'archive', 3), blk('b', 2), blk('u', 99)], k);
		assert.deepEqual([...m], [['a', 'A. Capacitance'], ['b', 'A. Capacitance']]);
	});
});
