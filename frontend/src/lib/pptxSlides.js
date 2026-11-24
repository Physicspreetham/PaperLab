/**
 * Pure helpers for the PowerPoint export: split one question's content into
 * slides. Kept free of DOM/fetch so it can be unit-tested in node.
 */

/** Approximate on-slide "weight" of a unit (roughly characters of 16pt text). */
export const SLIDE_BUDGET = 780;
/** A figure takes the right-hand column, leaving less room for text. */
export const IMAGE_WEIGHT = 200;

const OPT_RE = /^\(?[A-Da-d]\)/;

export function isOptionText(text) {
	return OPT_RE.test(String(text).trim());
}

/**
 * Group consecutive option lines (A) B) C) D)) into one unit so a question's
 * options never split across slides unless they alone exceed a slide.
 * `units` are { html, weight, opt, images }.
 */
export function groupOptions(units) {
	const out = [];
	for (const u of units) {
		const prev = out[out.length - 1];
		if (u.opt && prev?.opt && prev.weight + u.weight <= SLIDE_BUDGET) {
			prev.html += u.html;
			prev.weight += u.weight;
			prev.images = [...(prev.images ?? []), ...(u.images ?? [])];
		} else {
			out.push({ ...u });
		}
	}
	return out;
}

const emit = (units) => ({
	html: units.map((x) => x.html).filter(Boolean).join('\n'),
	images: units.flatMap((x) => x.images ?? [])
});

/**
 * Pack units into slides of at most `budget` weight, in order. A single unit
 * heavier than the budget gets a slide of its own (it is never cut).
 * Returns an array of { html, images } (images are data: URIs).
 */
export function packSlides(units, budget = SLIDE_BUDGET) {
	const slides = [];
	let cur = [];
	let w = 0;
	for (const u of groupOptions(units)) {
		if (cur.length && w + u.weight > budget) {
			slides.push(emit(cur));
			cur = [];
			w = 0;
		}
		cur.push(u);
		w += u.weight;
	}
	if (cur.length) slides.push(emit(cur));
	return slides.length ? slides : [{ html: '', images: [] }];
}

/** "Question 3" for the first slide, "Question 3 (cont.)" afterwards. */
export function slideTitle(label, index) {
	const base = label ? `Question ${label}` : 'Question';
	return index === 0 ? base : `${base} (cont.)`;
}
