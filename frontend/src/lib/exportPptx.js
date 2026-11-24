/**
 * PowerPoint (.pptx) export for the Paper Builder: one slide per question
 * (long questions continue over several slides), in the PaperLab slide theme.
 *
 * Walks the paginated preview rows in order, regroups them per question
 * (data-block), turns KaTeX output back into raw TeX (pandoc makes native,
 * editable PowerPoint equations), inlines figures as data: URIs and POSTs the
 * slides to /api/export/pptx.
 */
import { IMAGE_WEIGHT, isOptionText, packSlides, slideTitle } from '$lib/pptxSlides.js';

const BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '');
const MAX_IMG_PX = 520;

function blobToDataUrl(blob) {
	return new Promise((resolve, reject) => {
		const r = new FileReader();
		r.onload = () => resolve(r.result);
		r.onerror = () => reject(r.error);
		r.readAsDataURL(blob);
	});
}

async function inlineImage(src) {
	const res = await fetch(src);
	if (!res.ok) throw new Error(`figure ${res.status}`);
	return blobToDataUrl(await res.blob());
}

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Clean one preview element (a .question-flow) into slide units. */
async function toUnits(el, counter) {
	const liveImgs = [...el.querySelectorAll('img')];
	const clone = el.cloneNode(true);
	for (const node of clone.querySelectorAll('.pl-math, .pl-math-block')) {
		let tex = node.dataset.tex || '';
		try {
			tex = decodeURIComponent(tex);
		} catch {
			/* keep raw */
		}
		const span = document.createElement('span');
		span.className = node.classList.contains('pl-math-block') ? 'math display' : 'math inline';
		span.textContent = tex;
		node.replaceWith(span);
	}
	for (const n of clone.querySelectorAll('.figscale, .lightbox, .retry, .skel, script, style')) n.remove();
	for (const b of clone.querySelectorAll('button.figbtn')) b.replaceWith(...b.childNodes);
	await Promise.all(
		[...clone.querySelectorAll('img')].map(async (img, i) => {
			const live = liveImgs[i];
			try {
				img.setAttribute('src', await inlineImage(live?.currentSrc || live?.src || img.src));
				const w = Math.min(live?.naturalWidth || live?.offsetWidth || MAX_IMG_PX, MAX_IMG_PX);
				for (const a of ['style', 'class', 'height']) img.removeAttribute(a);
				img.setAttribute('width', String(Math.round(w)));
			} catch {
				counter.missing++;
				img.remove();
			}
		})
	);
	for (const w of [...clone.querySelectorAll('.md, .segs, .pl-optrow')]) w.replaceWith(...w.childNodes);
	// The "N." stem list becomes a plain numbered paragraph (list numbering would restart per slide).
	for (const ol of [...clone.querySelectorAll(':scope > ol')]) {
		let n = Number(ol.getAttribute('start')) || 1;
		const frag = document.createDocumentFragment();
		for (const li of ol.children) {
			const label = `<strong>${n}.</strong> `;
			const first = li.firstElementChild;
			if (first?.matches('p')) {
				first.insertAdjacentHTML('afterbegin', label);
				frag.append(...li.childNodes);
			} else {
				// Bare inline text: gather the leading inline run into a paragraph.
				const p = document.createElement('p');
				p.innerHTML = label;
				while (li.firstChild && !(li.firstChild.nodeType === 1 && li.firstChild.matches('p, ol, ul, figure, table, div'))) {
					p.append(li.firstChild);
				}
				frag.append(p, ...li.childNodes);
			}
			n++;
		}
		ol.replaceWith(frag);
	}
	// Loose text/inline nodes at the top level would be skipped: wrap runs in <p>.
	const BLOCK = 'p, ol, ul, figure, table, div, h1, h2, h3, h4, blockquote, pre';
	let run = null;
	for (const node of [...clone.childNodes]) {
		const isBlock = node.nodeType === 1 && node.matches(BLOCK);
		if (isBlock) {
			run = null;
		} else if (node.nodeType === 1 || (node.nodeType === 3 && node.textContent.trim())) {
			if (!run) {
				run = document.createElement('p');
				node.before(run);
			}
			run.append(node);
		} else if (node.nodeType === 3 && run) {
			run.append(node);
		}
	}
	const units = [];
	for (const node of clone.children) {
		// Figures leave the text: the server places them beside it as real pictures.
		const images = [...node.querySelectorAll('img')].map((img) => img.getAttribute('src')).filter(Boolean);
		for (const img of node.querySelectorAll('img')) img.remove();
		for (const f of node.querySelectorAll('figure, figcaption')) if (!f.textContent.trim()) f.remove();
		const empty = node.matches('figure, p, div') && !node.textContent.trim() && !node.querySelector('.math');
		const text = node.textContent || '';
		// textContent already includes each equation's TeX; typeset math is about half as long.
		const mathChars = [...node.querySelectorAll('.math')].reduce((a, m) => a + m.textContent.length, 0);
		const weight = (empty ? 0 : text.length - mathChars * 0.5 + (node.matches('table') ? 100 : 8)) + images.length * IMAGE_WEIGHT;
		units.push({
			html: empty ? '' : node.outerHTML,
			weight,
			images,
			opt: node.matches('p') && isOptionText(text)
		});
	}
	return units;
}

/** Build { title, subtitle, slides: [{title, html}], missing } from the live preview. */
export async function buildSlides(root, title) {
	const rows = [...root.querySelectorAll('.apage .prow')];
	if (rows.length === 0) throw new Error('Nothing to export yet.');
	const counter = { missing: 0 };
	const order = [];
	const byBlock = new Map();
	let subtitle = '';
	let kicker = '';
	for (const row of rows) {
		if (row.querySelector('.dochead')) {
			subtitle = row.querySelector('.dochead .pl-sub')?.textContent?.trim() || '';
		} else if (row.querySelector('.sechead')) {
			const h = row.querySelector('.sechead h3')?.textContent?.trim() || '';
			const kind = row.querySelector('.sechead .seckind')?.textContent?.trim() || '';
			order.push({ kind: 'section', title: [h, kind].filter(Boolean).join(' ') });
		} else if (row.querySelector('p.topichead')) {
			kicker = row.querySelector('p.topichead').textContent.trim();
		} else {
			const el = row.querySelector('[data-block]');
			if (!el) continue;
			const id = el.dataset.block;
			let q = byBlock.get(id);
			if (!q) {
				q = { kind: 'question', label: el.dataset.qlabel || '', kicker, els: [] };
				kicker = '';
				byBlock.set(id, q);
				order.push(q);
			}
			q.els.push(el);
		}
	}
	const slides = [];
	for (const item of order) {
		if (item.kind === 'section') {
			slides.push({ title: item.title, html: '', images: [] });
			continue;
		}
		const units = [];
		for (const el of item.els) units.push(...(await toUnits(el, counter)));
		packSlides(units).forEach(({ html, images }, i) => {
			const lead = i === 0 && item.kicker ? `<p><em>${esc(item.kicker)}</em></p>\n` : '';
			slides.push({ title: slideTitle(item.label, i), html: lead + html, images });
		});
	}
	if (!slides.some((s) => s.html || s.images.length)) throw new Error('No questions to export yet.');
	return { title, subtitle, slides, missing: counter.missing };
}

/** Export + trigger the browser download. Returns { missing, count }. */
export async function downloadPptx(root, title) {
	const name = (title || '').trim() || 'paper';
	const { subtitle, slides, missing } = await buildSlides(root, name);
	let res;
	try {
		res = await fetch(`${BASE}/export/pptx`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ title: name, subtitle, slides })
		});
	} catch {
		throw new Error('Cannot reach the backend - is it running?');
	}
	if (!res.ok) {
		let detail = res.statusText;
		try {
			detail = (await res.json()).detail || detail;
		} catch {
			/* keep status text */
		}
		throw new Error(typeof detail === 'string' ? detail : 'export failed');
	}
	const url = URL.createObjectURL(await res.blob());
	const a = document.createElement('a');
	a.href = url;
	a.download = `${name.replace(/[^\w.-]+/g, '_') || 'paper'}.pptx`;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 10000);
	return { missing, count: slides.length };
}
