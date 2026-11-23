/**
 * REST client for the PaperLab backend.
 *
 * Base URL defaults to same-origin /api (vite proxies it to
 * http://127.0.0.1:8000 in dev). Override with VITE_API_BASE.
 * Every function below maps 1:1 to BACKEND_CONTRACT.md.
 */

const BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '');

async function request(path, options = {}) {
	const { timeoutMs = 30000, ...fetchOptions } = options;
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	let res;
	try {
		res = await fetch(`${BASE}${path}`, {
			headers: { 'Content-Type': 'application/json' },
			...fetchOptions,
			signal: controller.signal
		});
	} catch (e) {
		clearTimeout(timer);
		if (e.name === 'AbortError') throw new Error('Request timed out - is the backend running?');
		throw new Error('Cannot reach the backend - is it running?');
	}
	clearTimeout(timer);
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const payload = (await res.json()).detail;
			if (typeof payload === 'string') detail = payload;
			if (Array.isArray(payload)) {
				detail = payload.filter(issue => typeof issue?.msg === 'string').map(issue => {
					const field = Array.isArray(issue.loc) ? issue.loc.slice(1).join('.') : '';
					return field ? `${field}: ${issue.msg}` : issue.msg;
				}).join('; ') || detail;
			}
		} catch {
			/* keep status text */
		}
		throw new Error(`${res.status}: ${detail}`);
	}
	if (res.status === 204) return null;
	return res.json();
}

export const api = {
	getEjeeCatalogue: () => request('/ejee/catalogue', { timeoutMs: 60000 }),
	getEjeeFilters: () => request('/ejee/filters', { timeoutMs: 60000 }),
	getEjeeQuestionDetails: (id, token) => request(`/ejee/questions/${id}?source_token=${encodeURIComponent(token)}`),
	searchEjeeQuestions: (body) => request('/ejee/questions/search', { method:'POST', body:JSON.stringify(body), timeoutMs:60000 }),
	importEjeeSelection: (body) => request('/ejee/selections', { method:'POST', body:JSON.stringify(body), timeoutMs:60000 }),
	appendEjeeSelection: (paperId, body) => request(`/ejee/collections/${paperId}/questions`, { method:'POST', body:JSON.stringify(body), timeoutMs:60000 }),
	setEjeeSource: (body) => request('/ejee/source', { method: 'PUT', body: JSON.stringify(body), timeoutMs: 60000 }),
	getEjeeJobs: () => request('/ejee/jobs'),
	getEjeeCropReview: (id) => request(`/ejee/jobs/${id}/crop-review`),
	ejeeCropSource: (id, row) => `${BASE}/ejee/jobs/${id}/crop-review/${encodeURIComponent(row.number)}/${row.name}/${row.page}`,
	previewEjeeCrop: async (id, row, box) => {
		const res = await fetch(`${api.ejeeCropSource(id, row)}/preview`, {
			method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(box)
		});
		if (!res.ok) {
			const error = await res.json().catch(() => null);
			throw new Error(typeof error?.detail === 'string' ? error.detail : `Crop preview failed (${res.status})`);
		}
		return {
			url: URL.createObjectURL(await res.blob()),
			edges: (res.headers.get('X-Crop-Edge-Warnings') || '').split(',').filter(Boolean)
		};
	},
	saveEjeeCrop: (id, row, box) => request(`/ejee/jobs/${id}/crop-review/${encodeURIComponent(row.number)}/${row.name}/${row.page}/save`, {
		method:'POST', body:JSON.stringify(box)
	}),
	getEjeeFigures: (paperId, qn) => request(`/ejee/collections/${paperId}/questions/${encodeURIComponent(qn)}/figures`),
	ejeeFigureSource: (paperId, qn, name) => `${BASE}/ejee/collections/${paperId}/questions/${encodeURIComponent(qn)}/figures/${name}/source`,
	previewEjeeFigure: async (paperId, qn, name, box) => {
		const res = await fetch(`${BASE}/ejee/collections/${paperId}/questions/${encodeURIComponent(qn)}/figures/${name}/preview`, {
			method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(box)
		});
		if (!res.ok) {
			const error = await res.json().catch(() => null);
			throw new Error(typeof error?.detail === 'string' ? error.detail : `Crop preview failed (${res.status})`);
		}
		return { url: URL.createObjectURL(await res.blob()),
			edges: (res.headers.get('X-Crop-Edge-Warnings') || '').split(',').filter(Boolean) };
	},
	saveEjeeFigure: (paperId, qn, name, box) => request(`/ejee/collections/${paperId}/questions/${encodeURIComponent(qn)}/figures/${name}/save`, {
		method:'POST', body:JSON.stringify(box)
	}),
	restoreEjeeFigure: (paperId, qn, name) => request(`/ejee/collections/${paperId}/questions/${encodeURIComponent(qn)}/figures/${name}/restore`, { method:'POST' }),
	getEjeeUsage: () => request('/ejee/usage'),
	getEjeeSelectionUsage: () => request('/ejee/usage/selection'),
	getImportedTextbooks: () => request('/ejee/library/papers'),
	reorderEjeeCollections: (ids) => request('/ejee/library/papers/order', { method: 'PUT', body: JSON.stringify({ ids }) }),
	getEjeeOrder: (id) => request(`/ejee/library/papers/${id}/order`),
	getImportedChapter: (id) => request(`/ejee/library/papers/${id}/questions`),
	importEjeeChapters: (book_id, chapters) => request('/ejee/jobs', { method: 'POST', body: JSON.stringify({ book_id, chapters }) }),
	resumeEjeeJob: (id) => request(`/ejee/jobs/${encodeURIComponent(id)}/resume`, { method: 'POST' }),
	cancelEjeeJob: (id) => request(`/ejee/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
	deleteEjeeJob: (id) => request(`/ejee/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
	getEjeeJobQuestions: (id) => request(`/ejee/jobs/${encodeURIComponent(id)}/questions`),
	deleteEjeeQuestion: (paperId, qn) => request(`/ejee/library/papers/${paperId}/questions/${encodeURIComponent(qn)}`, { method: 'DELETE' }),
	mergeEjeeCollections: (ids, title, remove_originals = false) => request('/ejee/library/papers/merge', { method: 'POST', body: JSON.stringify({ ids, title, remove_originals }), timeoutMs: 180000 }),
	deleteEjeeCollection: (id) => request(`/ejee/library/papers/${id}`, { method: 'DELETE' }),
	renameEjeeCollection: (id, title) => request(`/ejee/library/papers/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
	health: () => request('/health'),

	listPapers: (params = {}) => {
		const q = new URLSearchParams(
			Object.entries(params).filter(([, v]) => v !== '' && v != null)
		).toString();
		return request(`/papers${q ? `?${q}` : ''}`);
	},
	getPaper: (id, library) => request(`${library === 'ejee' ? '/ejee/library' : ''}/papers/${id}`),
	getLibrarySummary: () => request('/papers/summary'),
	getQuestions: (id) => request(`/papers/${id}/questions`),
	getQuestion: (paperId, qn, library) =>
		request(`${library === 'ejee' ? '/ejee/library' : ''}/papers/${paperId}/questions/${encodeURIComponent(qn)}`),

	getInbox: () => request('/inbox'),
	startPaper12Pilot: (model) => request('/pilot/12', {
		method: 'POST', body: JSON.stringify({ model }), timeoutMs: 60000
	}),
	paper12PilotStatus: () => request('/pilot/12'),
	startChatGPTConnection: () => request('/tagging/chatgpt/connect', { method: 'POST' }),
	getChatGPTModels: () => request('/tagging/chatgpt/models', { timeoutMs: 35000 }),
	disconnectChatGPT: () => request('/tagging/chatgpt/connection', { method: 'DELETE' }),
	autoTag: (paperId, qn, body) => request(`/tagging/${paperId}/${encodeURIComponent(qn)}`, {
		method: 'POST', body: JSON.stringify(body), timeoutMs: 150000
	}),
	classifyQuestion: (paperId, qn, body) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}`, {
			method: 'PATCH',
			body: JSON.stringify(body)
		}),

	getTopics: () => request('/topics'),
	createTopic: (body) => request('/topics', { method: 'POST', body: JSON.stringify(body) }),
	updateTopic: (code, body) =>
		request(`/topics/${encodeURIComponent(code)}`, {
			method: 'PATCH',
			body: JSON.stringify(body)
		}),
	deleteTopic: (code) =>
		request(`/topics/${encodeURIComponent(code)}`, { method: 'DELETE' }),
	moveTopic: (code, newParent) =>
		request(`/topics/${encodeURIComponent(code)}/move`, {
			method: 'POST',
			body: JSON.stringify({ newParent })
		}),
	getTopicUsage: () => request('/topics/usage'),

	getStats: () => request('/stats'),
	getDiskUsage: () => request('/stats/disk'),
	purgeRenderCache: () => request('/stats/disk/render', { method: 'DELETE' }),
	purgeCleanedPdfs: () => request('/stats/disk/cleaned', { method: 'DELETE' }),
	purgeIntermediates: () => request('/stats/disk/intermediates', { method: 'DELETE' }),
	getPaperPdfs: () => request('/stats/pdfs'),
	deletePaperPdfs: (body) => request('/stats/pdfs', { method: 'DELETE', body: JSON.stringify(body) }),

	listUploads: () => request('/uploads'),
	uploadFiles: (formData) =>
		request('/uploads', { method: 'POST', body: formData, headers: {} }),
	deleteUploads: (names) =>
		request('/uploads', { method: 'DELETE', body: JSON.stringify({ names }) }),
	suggestPairs: () => request('/uploads/pairs/suggest'),
	registerPairs: (pairs) =>
		request('/papers/register', { method: 'POST', body: JSON.stringify({ pairs }) }),

	getJobs: () => request('/jobs'),
	runPapers: (ids, mode = 'sequential', force = false) =>
		request('/jobs', { method: 'POST', body: JSON.stringify({ ids, mode, force }) }),
	deletePaper: (id) => request(`/papers/${id}`, { method: 'DELETE' }),

	listFigures: (paperId, qn) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures`),
	listTrash: (paperId, qn) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures/trash`),
	cropFigure: (paperId, qn, name, box) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures/${name}`, {
			method: 'PATCH',
			body: JSON.stringify(box)
		}),
	previewFigure: async (paperId, qn, name, box) => {
		const res = await fetch(
			`${BASE}/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures/${name}/preview`,
			{ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(box) }
		);
		if (!res.ok) throw new Error(`preview: ${res.status}`);
		return URL.createObjectURL(await res.blob());
	},
	replaceFigure: (paperId, qn, name, file) => {
		const form = new FormData();
		form.append('file', file);
		return request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures/${name}`, {
			method: 'PUT',
			body: form,
			headers: {}
		});
	},
	deleteFigure: (paperId, qn, name) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures/${name}`, {
			method: 'DELETE'
		}),
	restoreFigure: (paperId, qn, trashName) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures/${trashName}/restore`, {
			method: 'POST'
		}),
	emptyTrashFigure: (paperId, qn, trashName) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures/trash/${trashName}`, {
			method: 'DELETE'
		}),
	addFigure: (paperId, qn, target, filename, file) => {
		const form = new FormData();
		form.append('target', target);
		form.append('filename', filename);
		form.append('file', file);
		return request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/figures`, {
			method: 'POST',
			body: form,
			headers: {}
		});
	},

	login: (password) =>
		request('/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
	logout: () => request('/auth/logout', { method: 'POST' }),
	me: () => request('/auth/me'),
	getMeta: () => request('/papers/meta'),

	getTex: (paperId, qn, part) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/tex?part=${part}`),
	previewTex: (paperId, qn, body) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/tex/preview`, {
			method: 'POST',
			body: JSON.stringify(body)
		}),
	saveTex: (paperId, qn, body) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}/tex`, {
			method: 'PATCH',
			body: JSON.stringify(body)
		}),

	getSearchFacets: () => request('/search/facets'),
	searchQuestions: (filters = {}, { limit = 24, cursor = null } = {}) => {
		const q = new URLSearchParams();
		for (const [key, vals] of Object.entries(filters)) {
			if (key === 'include_supporting') { q.set(key, String(!!vals)); continue; }
			for (const v of vals ?? []) q.append(key, v);
		}
		q.set('limit', limit);
		if (cursor) q.set('cursor', cursor);
		return request(`/search?${q.toString()}`);
	},

	// Model paper builder (exam patterns + random picking)
	modelPatterns: () => request('/model/patterns'),
	modelDescribe: (pattern) => request('/model/describe', { method: 'POST', body: JSON.stringify({ pattern }) }),
	modelPreview: (body) => request('/model/preview', { method: 'POST', body: JSON.stringify(body) }),
	modelGenerate: (body) => request('/model/generate', { method: 'POST', body: JSON.stringify(body) }),
	modelRelease: (items) => request('/model/release', { method: 'POST', body: JSON.stringify({ items }) }),
	modelForgetUsed: () => request('/model/used', { method: 'DELETE' })
};
