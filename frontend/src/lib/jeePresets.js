/**
 * Built-in model-paper presets mirroring the Physics section of each
 * JEE Advanced paper (2014–2026, per-subject structures).
 *
 * Mapping to PaperLab types: SC -> scq, MC -> msq, single-digit INT (0–9)
 * and NNI -> nni (both rule out negatives under the extractor's
 * format-first rule), NUM -> num, MATRIX-SC / matrix-match -> mtx.
 * Paragraph targets count GROUPS (one cart item each): "2 paragraphs of
 * 2 NUM" is par-num: 2, not 4.
 *
 * 2014 Paper 1 uses the corrected structure (Section 1 was 10
 * single-correct, not multiple-correct).
 */
export const JEE_PRESET_PAPERS = [
	{ id: 'jee-2026-p1', name: 'JEE Advanced 2026 Paper 1 · Physics', counts: { scq: 4, msq: 4, num: 4, mtx: 4 } },
	{ id: 'jee-2026-p2', name: 'JEE Advanced 2026 Paper 2 · Physics', counts: { scq: 4, msq: 5, num: 5, 'par-num': 2 } },
	{ id: 'jee-2025-p1', name: 'JEE Advanced 2025 Paper 1 · Physics', counts: { scq: 4, msq: 3, num: 6, mtx: 3 } },
	{ id: 'jee-2025-p2', name: 'JEE Advanced 2025 Paper 2 · Physics', counts: { scq: 4, msq: 4, num: 8 } },
	{ id: 'jee-2024-p1', name: 'JEE Advanced 2024 Paper 1 · Physics', counts: { scq: 4, msq: 3, nni: 6, mtx: 4 } },
	{ id: 'jee-2024-p2', name: 'JEE Advanced 2024 Paper 2 · Physics', counts: { scq: 4, msq: 3, nni: 6, 'par-num': 2 } },
	{ id: 'jee-2023-p1', name: 'JEE Advanced 2023 Paper 1 · Physics', counts: { scq: 4, msq: 3, nni: 6, mtx: 4 } },
	{ id: 'jee-2023-p2', name: 'JEE Advanced 2023 Paper 2 · Physics', counts: { scq: 4, msq: 3, nni: 6, 'par-num': 2 } },
	{ id: 'jee-2022-p1', name: 'JEE Advanced 2022 Paper 1 · Physics', counts: { num: 8, msq: 6, mtx: 4 } },
	{ id: 'jee-2022-p2', name: 'JEE Advanced 2022 Paper 2 · Physics', counts: { nni: 8, msq: 6, scq: 4 } },
	{ id: 'jee-2021-p1', name: 'JEE Advanced 2021 Paper 1 · Physics', counts: { scq: 4, 'par-num': 3, msq: 6, nni: 3 } },
	{ id: 'jee-2021-p2', name: 'JEE Advanced 2021 Paper 2 · Physics', counts: { msq: 6, 'par-num': 3, 'par-scq': 2, nni: 3 } },
	{ id: 'jee-2020-p1', name: 'JEE Advanced 2020 Paper 1 · Physics', counts: { scq: 6, msq: 6, num: 6 } },
	{ id: 'jee-2020-p2', name: 'JEE Advanced 2020 Paper 2 · Physics', counts: { nni: 6, msq: 6, num: 6 } },
	{ id: 'jee-2019-p1', name: 'JEE Advanced 2019 Paper 1 · Physics', counts: { scq: 4, msq: 8, num: 6 } },
	{ id: 'jee-2019-p2', name: 'JEE Advanced 2019 Paper 2 · Physics', counts: { msq: 8, num: 6, mtx: 4 } },
	{ id: 'jee-2018-p1', name: 'JEE Advanced 2018 Paper 1 · Physics', counts: { msq: 6, num: 8, 'par-scq': 2 } },
	{ id: 'jee-2018-p2', name: 'JEE Advanced 2018 Paper 2 · Physics', counts: { msq: 6, num: 8, mtx: 4 } },
	{ id: 'jee-2017-p1', name: 'JEE Advanced 2017 Paper 1 · Physics', counts: { msq: 7, nni: 5, mtx: 6 } },
	{ id: 'jee-2017-p2', name: 'JEE Advanced 2017 Paper 2 · Physics', counts: { scq: 7, msq: 7, 'par-scq': 2 } },
	{ id: 'jee-2016-p1', name: 'JEE Advanced 2016 Paper 1 · Physics', counts: { scq: 5, msq: 8, nni: 5 } },
	{ id: 'jee-2016-p2', name: 'JEE Advanced 2016 Paper 2 · Physics', counts: { scq: 6, msq: 8, 'par-scq': 2 } },
	{ id: 'jee-2015-p1', name: 'JEE Advanced 2015 Paper 1 · Physics', counts: { nni: 8, msq: 10, mtx: 2 } },
	{ id: 'jee-2015-p2', name: 'JEE Advanced 2015 Paper 2 · Physics', counts: { nni: 8, msq: 8, 'par-msq': 2 } },
	{ id: 'jee-2014-p1', name: 'JEE Advanced 2014 Paper 1 · Physics', counts: { scq: 10, nni: 10 } },
	{ id: 'jee-2014-p2', name: 'JEE Advanced 2014 Paper 2 · Physics', counts: { scq: 10, 'par-scq': 3, mtx: 4 } }
];
