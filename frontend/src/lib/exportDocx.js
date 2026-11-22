/** Snapshot the current sheet, not the controls or browser print styles. */
const BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '');
const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const FIGURE_PATH = /^\/api\/papers\/[1-9][0-9]*\/questions\/[^/]+\/figures\/[^/]+$/;
const STYLED = [
	['.dochead p', 'DocSub'],
	['p.seckind', 'SecKind'],
	['p.parahead', 'ParaHead'],
	['p.topichead', 'TopicHead'],
	['h4.solhead', 'ParaHead']
];

function wrap(el, style) {
	const d = document.createElement('div');
	d.setAttribute('custom-style', style);
	if (el.matches('h4.solhead')) {
		const p = document.createElement('p');
		p.append(...el.childNodes);
		el.replaceWith(p);
		el = p;
	}
	el.replaceWith(d);
	d.appendChild(el);
}

export function snapshotWordSheet(root) {
	const pages = root.querySelectorAll('.apage');
	if (!pages.length) throw new Error('Nothing to export yet.');
	const content = document.createElement('div');
	for (const live of pages) {
		const page = live.cloneNode(true);
		// Read the visible values, which may differ from the draft's last render.
		const inputs = live.querySelectorAll('input');
		page.querySelectorAll('input').forEach((input, i) => {
			input.replaceWith(document.createTextNode(inputs[i].value || '—'));
		});
		const images = live.querySelectorAll('img');
		page.querySelectorAll('img').forEach((img, i) => {
			const source = images[i];
			const url = new URL(source.getAttribute('src'), document.baseURI);
			if (url.origin !== location.origin || !FIGURE_PATH.test(url.pathname)) {
				throw new Error('Word export can only include archive figures. Use Print / PDF for this sheet.');
			}
			img.removeAttribute('src');
			img.removeAttribute('height');
			img.dataset.figure = url.pathname; // no query, network URL, or file path
			const width = Math.min(source.offsetWidth || source.naturalWidth || 250, 600);
			img.setAttribute('width', String(Math.max(1, Math.round(width))));
		});
		for (const node of page.querySelectorAll('.pl-math, .pl-math-block')) {
			const span = document.createElement('span');
			span.className = node.classList.contains('pl-math-block') ? 'math display' : 'math inline';
			span.textContent = decodeURIComponent(node.dataset.tex || '');
			node.replaceWith(span);
		}
		for (const [selector, style] of STYLED) {
			for (const el of page.querySelectorAll(selector)) wrap(el, style);
		}
		for (const heading of page.querySelectorAll('h3.solshead')) heading.dataset.solutions = '1';
		for (const table of page.querySelectorAll('.key table')) {
			table.className = 'pl-key-table';
			const cols = document.createElement('colgroup');
			for (let i = 0; i < (table.tHead?.rows[0]?.cells.length ?? 0); i++) {
				const col = document.createElement('col');
				col.dataset.width = i % 2 ? '12' : '8'; // room for "Q.No" at the Word body size
				cols.append(col);
			}
			table.prepend(cols);
		}
		for (const el of page.querySelectorAll('.figscale, .lightbox, script, style')) el.remove();
		for (const el of page.querySelectorAll('a, button.figbtn, .prow, .md, .segs, .pl-optrow')) {
			el.replaceWith(...el.childNodes);
		}
		for (const el of page.querySelectorAll('[style]')) el.removeAttribute('style');
		content.append(...page.childNodes);
	}
	// Svelte's hydration markers are not part of the document.
	const walker = document.createTreeWalker(content, NodeFilter.SHOW_COMMENT);
	const comments = [];
	while (walker.nextNode()) comments.push(walker.currentNode);
	comments.forEach((node) => node.remove());
	return new XMLSerializer().serializeToString(content);
}

export async function downloadDocx(root, title) {
	const body = JSON.stringify({ sheet: snapshotWordSheet(root), title });
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), 40000);
	let response, file, error;
	try {
		response = await fetch(`${BASE}/export/docx`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body,
			signal: controller.signal
		});
		if (response.ok) file = await response.blob();
		else error = await response.json().catch(() => ({}));
	} catch {
		throw new Error('Could not reach Word export. Try again or use Print / PDF.');
	} finally {
		clearTimeout(timer);
	}
	if (!response.ok) {
		const detail = error?.detail;
		throw new Error(typeof detail === 'string' ? detail : 'Word export failed. Try again or use Print / PDF.');
	}
	if (file.type !== DOCX || !file.size) throw new Error('Word export did not return a document. Try again or use Print / PDF.');
	const href = URL.createObjectURL(file);
	const a = document.createElement('a');
	a.href = href;
	a.download = /filename="([A-Za-z0-9_.-]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? 'paper.docx';
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(href), 10000);
}
