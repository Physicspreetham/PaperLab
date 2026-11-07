/**
 * "Save PDF" for the Paper Builder, without the browser print dialog.
 *
 * Builds a fully self-contained copy of the paginated preview (all CSS, fonts
 * and figures inlined as data: URIs, no scripts) and POSTs it to
 * /api/export/pdf, where a headless Chrome/Edge prints it with the same
 * @media print rules the Print button uses (A4, exactly as previewed).
 */

const BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '');

function blobToDataUrl(blob) {
	return new Promise((resolve, reject) => {
		const r = new FileReader();
		r.onload = () => resolve(r.result);
		r.onerror = () => reject(r.error);
		r.readAsDataURL(blob);
	});
}

const dataCache = new Map();
async function toDataUrl(url) {
	if (dataCache.has(url)) return dataCache.get(url);
	const p = (async () => {
		const res = await fetch(url);
		if (!res.ok) throw new Error(`${res.status} ${url}`);
		return blobToDataUrl(await res.blob());
	})();
	dataCache.set(url, p);
	try {
		return await p;
	} catch (e) {
		dataCache.delete(url);
		throw e;
	}
}

/** All page CSS as text, with @font-face sources inlined (woff2 only). */
async function collectCss() {
	const chunks = [];
	for (const sheet of document.styleSheets) {
		let rules;
		try {
			rules = sheet.cssRules;
		} catch {
			continue; // cross-origin sheet: not ours
		}
		for (const rule of rules) {
			if (rule.type === CSSRule.FONT_FACE_RULE) {
				const src = rule.style.getPropertyValue('src');
				const urls = [...src.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((m) => m[1]);
				const pick = urls.find((u) => /\.woff2(\?|#|$)/i.test(u)) || urls[0];
				if (!pick) continue;
				try {
					const abs = new URL(pick, sheet.href || document.baseURI).href;
					const data = await toDataUrl(abs);
					const fmt = /\.woff2/i.test(pick) ? 'woff2' : /\.woff/i.test(pick) ? 'woff' : 'truetype';
					const style = rule.style;
					const parts = [
						`font-family:${style.getPropertyValue('font-family')}`,
						`font-style:${style.getPropertyValue('font-style') || 'normal'}`,
						`font-weight:${style.getPropertyValue('font-weight') || '400'}`
					];
					const ur = style.getPropertyValue('unicode-range');
					if (ur) parts.push(`unicode-range:${ur}`);
					chunks.push(`@font-face{${parts.join(';')};src:url(${data}) format("${fmt}")}`);
				} catch {
					/* font unavailable: fall back to system fonts */
				}
			} else {
				// Strip any url(...) that is not already a data: URI (the server refuses them).
				chunks.push(rule.cssText.replace(/url\(\s*["']?(?!data:|#)[^)]*\)/gi, 'none'));
			}
		}
	}
	return chunks.join('\n');
}

/** Build the self-contained print document. Returns { html, missing }. */
export async function buildPdfHtml(root, title) {
	const view = root.querySelector('.pview');
	if (!view || root.querySelectorAll('.apage').length === 0) throw new Error('Nothing to export yet.');

	const liveImgs = [...view.querySelectorAll('img')];
	const clone = view.cloneNode(true);
	for (const n of clone.querySelectorAll('script, .figscale, .lightbox, .retry, .skel')) n.remove();
	// Zoom buttons wrap figures; keep the picture only.
	for (const b of clone.querySelectorAll('button.figbtn')) b.replaceWith(...b.childNodes);
	// No inline event handlers or links out of the page.
	for (const el of clone.querySelectorAll('*')) {
		for (const a of [...el.attributes]) {
			if (/^on/i.test(a.name)) el.removeAttribute(a.name);
		}
		if (el.tagName === 'A') el.removeAttribute('href');
	}
	// Answer-key inputs: show the typed value as text.
	const liveInputs = [...view.querySelectorAll('input')];
	[...clone.querySelectorAll('input')].forEach((inp, i) => {
		inp.replaceWith(document.createTextNode(liveInputs[i]?.value || '—'));
	});

	let missing = 0;
	const imgs = [...clone.querySelectorAll('img')];
	await Promise.all(
		imgs.map(async (img, i) => {
			const live = liveImgs[i];
			try {
				img.setAttribute('src', await toDataUrl(live?.currentSrc || live?.src || img.src));
				img.removeAttribute('srcset');
				img.removeAttribute('loading');
			} catch {
				missing++;
				img.remove();
			}
		})
	);

	const css = await collectCss();
	const htmlAttrs = [...document.documentElement.attributes]
		.filter((a) => !/^on/i.test(a.name))
		.map((a) => `${a.name}="${String(a.value).replace(/"/g, '&quot;')}"`)
		.join(' ');
	const bodyClass = document.body.className ? ` class="${document.body.className}"` : '';
	const safeTitle = String(title).replace(/[<>&"]/g, '');
	const html =
		`<!doctype html><html ${htmlAttrs}><head><meta charset="utf-8"><title>${safeTitle}</title>` +
		`<style>${css}</style>` +
		// Print the pages only: no chrome, no scaling, white background.
		`<style>html,body{background:#fff!important;margin:0!important;height:auto!important;overflow:visible!important}` +
		`.pview{overflow:visible!important;height:auto!important}</style>` +
		`</head><body${bodyClass}>${clone.outerHTML}</body></html>`;
	return { html, missing };
}

/** Export + trigger the download. Returns { missing }. */
export async function downloadPdf(root, title) {
	const name = (title || '').trim() || 'paper';
	const { html, missing } = await buildPdfHtml(root, name);
	let res;
	try {
		res = await fetch(`${BASE}/export/pdf`, {
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
	a.download = `${name.replace(/[^\w.-]+/g, '_') || 'paper'}.pdf`;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 10000);
	return { missing };
}
