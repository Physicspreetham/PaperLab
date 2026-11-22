/**
 * Word (.docx) export for the Paper Builder.
 *
 * Takes the live, paginated preview (".apage" nodes), turns KaTeX output back
 * into raw TeX (pandoc converts it to native Word equations), inlines figures
 * as data: URIs, and POSTs the HTML to /api/export/docx.
 */

const BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '');
const MAX_IMG_PX = 600; // ~6.25in: fits an A4 text column in Word

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

/** Build the export HTML from the preview root. Returns { html, missing }. */
export async function buildExportHtml(root, title) {
	const pages = [...root.querySelectorAll('.apage')];
	if (pages.length === 0) throw new Error('Nothing to export yet.');

	const parts = [];
	let missing = 0;
	for (const page of pages) {
		const liveImgs = [...page.querySelectorAll('img')];
		const clone = page.cloneNode(true);

		// Math: KaTeX markup -> raw TeX in a math span (a pandoc filter makes it Word math).
		for (const node of clone.querySelectorAll('.pl-math, .pl-math-block')) {
			let tex = '';
			try {
				tex = decodeURIComponent(node.dataset.tex || '');
			} catch {
				tex = node.dataset.tex || '';
			}
			const display = node.classList.contains('pl-math-block');
			const span = document.createElement('span');
			span.className = display ? 'math display' : 'math inline';
			span.textContent = tex;
			node.replaceWith(span);
		}

		// Answer-key cells are <input>s: export what is typed in them.
		const liveInputs = [...page.querySelectorAll('input')];
		[...clone.querySelectorAll('input')].forEach((inp, i) => {
			inp.replaceWith(document.createTextNode(liveInputs[i]?.value || '—'));
		});

		// Paper/section headers -> named Word paragraph styles (see backend/docx_reference.py).
		const wrap = (el, style) => {
			const d = document.createElement('div');
			d.setAttribute('custom-style', style);
			el.replaceWith(d);
			d.appendChild(el);
		};
		for (const el of clone.querySelectorAll('.dochead p')) wrap(el, 'DocSub');
		for (const el of clone.querySelectorAll('p.seckind')) wrap(el, 'SecKind');
		for (const el of clone.querySelectorAll('p.parahead')) wrap(el, 'ParaHead');
		for (const el of clone.querySelectorAll('p.topichead')) wrap(el, 'TopicHead');
		for (const h of clone.querySelectorAll('h4.solhead')) {
			const p = document.createElement('p');
			p.textContent = h.textContent;
			h.replaceWith(p);
			wrap(p, 'ParaHead');
		}

		// UI-only chrome.
		for (const n of clone.querySelectorAll('.figscale, .lightbox, .retry, .skel, script, style')) n.remove();
		// Zoom buttons wrap figures: keep the image, drop the button.
		for (const b of clone.querySelectorAll('button.figbtn')) b.replaceWith(...b.childNodes);

		// Figures: inline bytes, fix width (layout px, unaffected by preview zoom).
		const imgs = [...clone.querySelectorAll('img')];
		await Promise.all(
			imgs.map(async (img, i) => {
				const live = liveImgs[i];
				try {
					img.setAttribute('src', await inlineImage(live?.currentSrc || live?.src || img.src));
					const w = Math.min(live?.offsetWidth || live?.naturalWidth || MAX_IMG_PX, MAX_IMG_PX);
					img.removeAttribute('style');
					img.removeAttribute('class');
					img.setAttribute('width', String(Math.round(w)));
					img.removeAttribute('height');
				} catch {
					missing++;
					img.remove();
				}
			})
		);
		// Flatten the preview's layout wrappers (.prow per paragraph, .md, .segs)
		// so neighbouring paragraphs are siblings: the Word filter groups the
		// A)-D) options into one row only when they sit side by side.
		for (const w of [...clone.querySelectorAll('.prow, .md, .segs, .pl-optrow')]) w.replaceWith(...w.childNodes);
		// Word consumes table cells rather than CSS grid. Preserve the key's
		// five width units, including wider equation and matching cells.
		for (const row of clone.querySelectorAll('.key-shell-row')) {
			const table = document.createElement('table');
			table.className = 'pl-key-table';
			table.setAttribute('border', '1');
			table.style.width = '100%';
			const cols = document.createElement('colgroup');
			for (let i = 0; i < 10; i++) {
				const col = document.createElement('col'); col.style.width = i%2 ? '14%' : '6%'; cols.append(col);
			}
			table.append(cols);
			const body = document.createElement('tbody'), line = document.createElement('tr');
			let used = 0;
			for (const shell of row.querySelectorAll('.key-shell')) {
				const span = Math.max(1, Math.min(5, Number(shell.dataset.keySpan) || 1));
				const number = document.createElement('td');
				number.style.width = '6%'; number.style.verticalAlign = 'middle';
				number.textContent = shell.querySelector('.key-number')?.textContent || '';
				const cell = document.createElement('td');
				cell.colSpan = span*2-1; cell.style.width = `${span * 20-6}%`;
				cell.style.verticalAlign = 'middle'; cell.style.textAlign = 'center';
				const value = shell.querySelector('.key-value');
				if (value) cell.append(...value.childNodes);
				line.append(number,cell); used += span;
			}
			if (used < 5) { const cell = document.createElement('td'); cell.colSpan = (5-used)*2; line.append(cell); }
			body.append(line); table.append(body); row.replaceWith(table);
		}
		parts.push(clone.innerHTML);
	}

	// Pagination splits preview rows into pages. Rejoin their key tables for
	// Word so it receives one continuous table and handles page breaks itself.
	const content = document.createElement('div');
	content.innerHTML = parts.join('\n');
	for (const table of content.querySelectorAll('table.pl-key-table')) {
		const previous = table.previousElementSibling;
		if (previous?.matches('table.pl-key-table')) {
			previous.querySelector('tbody').append(...table.querySelector('tbody').children);
			table.remove();
		}
	}
	const html = `<!doctype html><html><head><meta charset="utf-8"></head><body>${content.innerHTML}</body></html>`;
	return { html, missing };
}

/** Export + trigger the browser download. Returns { missing }. */
export async function downloadDocx(root, title) {
	const name = (title || '').trim() || 'paper';
	const { html, missing } = await buildExportHtml(root, name);
	let res;
	try {
		res = await fetch(`${BASE}/export/docx`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ html, title: name })
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
		throw new Error(detail);
	}
	const blob = await res.blob();
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = `${name.replace(/[^\w.-]+/g, '_') || 'paper'}.docx`;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 10000);
	return { missing };
}
