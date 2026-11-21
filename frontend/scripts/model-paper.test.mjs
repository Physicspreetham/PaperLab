import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createCart, validateStore } from '../src/lib/cartModel.js';
import {
	compareModelPaper, groupCartItems, MODEL_PAPER_TYPES, modelPaperInput, modelTypeLabel, validateModelPapers
} from '../src/lib/modelPaperModel.js';

test('lists all additions before any removals, with omitted targets counting as zero', () => {
	const items = [
		{ number: '1', qtype: 'scq' },
		{ number: '2', qtype: 'int' },
		{ number: '3', qtype: 'other' }
	];
	assert.deepEqual(compareModelPaper({ msq: 2, 'par-scq': 1 }, groupCartItems(items)), [
		{ type: 'msq', count: 2, action: 'Add' },
		{ type: 'par-scq', count: 1, action: 'Add' },
		{ type: 'scq', count: 1, action: 'Remove' },
		{ type: 'int', count: 1, action: 'Remove' }
	]);
});

test('paragraph groups each count once and never count toward standalone targets', () => {
	const items = [
		{ number: 'A-7-10_paragraph', qtype: 'par-scq' },
		{ number: '11-12_paragraph', qtype: 'msq' },
		{ number: '13-14_paragraph', qtype: 'par-mix' },
		{ number: '15', qtype: 'scq' }
	];
	const groups = groupCartItems(items);
	assert.deepEqual(compareModelPaper({ 'par-scq': 2, 'par-msq': 1, scq: 1 }, groups), [
		{ type: 'par-scq', count: 1, action: 'Add' },
		{ type: 'par-mix', count: 1, action: 'Remove' }
	]);
	assert.deepEqual(compareModelPaper({ paragraph: 3, scq: 1 }, groups), []);
	assert.deepEqual(compareModelPaper({ paragraph: 2, scq: 1 }, groups), [
		{ type: 'paragraph', count: 1, action: 'Remove' }
	]);
});

test('sorts by type without changing insertion order within each type or mutating the cart', () => {
	const items = [
		{ number: '9', qtype: 'int' },
		{ number: '6', qtype: 'scq' },
		{ number: '5', qtype: 'int' }
	];
	assert.deepEqual(groupCartItems(items).flatMap((group) => group.items.map((item) => item.number)), ['6', '9', '5']);
	assert.deepEqual(items.map((item) => item.number), ['9', '6', '5']);
});

test('validates names and counts and retains only valid unique saved model papers', () => {
	assert.deepEqual(modelPaperInput('  Midterm  ', { scq: 10, msq: 6, 'par-scq': 2, int: 0, unknown: 5 }), {
		name: 'Midterm', counts: { scq: 10, msq: 6, 'par-scq': 2 }
	});
	for (const counts of [{}, { int: -1 }, { msq: 2.5 }, { msq: '2' }, { scq: 2000, msq: 1 }])
		assert.ok(modelPaperInput('Midterm', counts).error);
	assert.ok(modelPaperInput(' ', { scq: 2 }).error);
	const paper = { id: 'midterm', name: 'Midterm', counts: { scq: 10 } };
	assert.deepEqual(validateModelPapers([null, paper, paper, { id: 'broken' }]), [paper]);
});

test('legacy paragraph targets load intact but cannot be added to new models', () => {
	const paper = { id: 'old', name: 'Old', counts: { paragraph: 2 } };
	assert.deepEqual(validateModelPapers([paper]), [paper]);
	assert.ok(modelPaperInput(paper.name, paper.counts).error);
	assert.ok(!MODEL_PAPER_TYPES.includes('paragraph'));
	assert.ok(!MODEL_PAPER_TYPES.includes('unknown'));
});

test('matches non-negative integers separately from general integers and paragraph variants', () => {
	const input = modelPaperInput('Integer mix', { nni: 1, 'par-nni': 2 });
	assert.deepEqual(input.counts, { nni: 1, 'par-nni': 2 });
	const items = groupCartItems([
		{ number: '1', qtype: 'int' }, { number: '2', qtype: 'nni' },
		{ number: '3-5_paragraph', qtype: 'par-nni' }
	]);
	assert.deepEqual(compareModelPaper(input.counts, items), [
		{ type: 'par-nni', count: 1, action: 'Add' },
		{ type: 'int', count: 1, action: 'Remove' }
	]);
	assert.equal(modelTypeLabel('par-nni'), 'Paragraph: Non-negative integer (PAR-NNI)');
});

test('cart model selection defaults to none and survives cart store validation', () => {
	const old = createCart('Existing');
	delete old.modelPaperId;
	const current = { ...createCart('Selected'), modelPaperId: 'midterm' };
	const { store } = validateStore({ activeId: current.id, carts: [old, current] });
	assert.deepEqual(store.carts.map((cart) => cart.modelPaperId), [null, 'midterm']);
});

test('JEE presets merge without duplicating or disturbing user papers', async () => {
	const { JEE_PRESET_PAPERS } = await import('../src/lib/jeePresets.js');
	const { withSeededPresets } = await import('../src/lib/modelPaperModel.js');
	const seeded = withSeededPresets([], JEE_PRESET_PAPERS);
	assert.equal(seeded.length, 26);
	assert.equal(seeded[0].id, 'jee-2026-p1');
	const mine = { id: 'mine', name: 'Mine', counts: { scq: 2 } };
	const merged = withSeededPresets([mine], JEE_PRESET_PAPERS);
	assert.equal(merged.length, 27);
	assert.equal(merged[merged.length - 1], mine);
	const kept = withSeededPresets([{ ...seeded[0] }, mine], JEE_PRESET_PAPERS);
	assert.equal(kept.length, 27);
	assert.deepEqual(kept.filter((p) => p.id === 'jee-2026-p1').length, 1);
});

test('JEE presets are valid, unique, and use known types', async () => {
	const { JEE_PRESET_PAPERS } = await import('../src/lib/jeePresets.js');
	assert.equal(JEE_PRESET_PAPERS.length, 26);
	assert.deepEqual(new Set(JEE_PRESET_PAPERS.map((p) => p.id)).size, 26);
	const validated = validateModelPapers(JEE_PRESET_PAPERS);
	assert.equal(validated.length, 26);
	assert.equal(validated[0].id, 'jee-2026-p1');
	for (const paper of JEE_PRESET_PAPERS) {
		for (const type of Object.keys(paper.counts)) assert.ok(MODEL_PAPER_TYPES.includes(type), type);
		assert.ok(paper.name.length <= 80);
	}
	const byId = Object.fromEntries(JEE_PRESET_PAPERS.map((p) => [p.id, p.counts]));
	// 2014 Paper 1 correction: single-correct, never multiple-correct.
	assert.deepEqual(byId['jee-2014-p1'], { scq: 10, nni: 10 });
	// Single-digit INT (0-9) maps to nni under the format-first rule.
	assert.deepEqual(byId['jee-2022-p2'], { nni: 8, msq: 6, scq: 4 });
	assert.deepEqual(byId['jee-2024-p1'], { scq: 4, msq: 3, nni: 6, mtx: 4 });
	// Paragraph targets count groups: 2 paragraphs of 2 NUM is par-num: 2.
	assert.deepEqual(byId['jee-2024-p2']['par-num'], 2);
});
