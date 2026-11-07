<script>
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { cartStore } from '$lib/carts.js';
	import { parsedKeys } from '$lib/builder.js';
	import { modelStore, modelOrder, modelNumbering, model } from '$lib/modelStore.js';
	import { qtypeLabel } from '$lib/qtypes.js';
	import { downloadDocx } from '$lib/exportDocx.js';
	import { downloadPdf } from '$lib/exportPdf.js';
	import QuestionSheetPreview from '$lib/components/QuestionSheetPreview.svelte';
	import AnswerSheetPreview from '$lib/components/AnswerSheetPreview.svelte';
	import ModelPicker from '$lib/components/ModelPicker.svelte';

	// question types that can sit in each pattern section type (mirrors backend/patterns.py)
	const ACCEPTS = {
		single: ['scq'],
		multiple: ['msq'],
		integer: ['int', 'num'],
		numerical: ['num', 'int'],
		paragraph: ['par-scq', 'par-mix'],
		paragraph_multi: ['par-msq', 'par-mix'],
		paragraph_numeric: ['par-num', 'par-int', 'par-mix'],
		matching: ['mtx'],
		matrix: ['mtx'],
		matrix3: ['mtx']
	};
	const accepts = (sec) => ACCEPTS[sec.type === 'paragraph' && sec.multi ? 'paragraph_multi' : sec.type] ?? [];

	const draft = $derived($modelStore);
	const num = $derived($modelNumbering);
	const order = $derived($modelOrder);
	const pattern = $derived(draft?.pattern ?? null);

	let previewMode = $state('questions');
	let previewEl = $state(null);
	let busy = $state('');
	let note = $state(null); // {ok, text}
	let confirmNew = $state(false);
	let cartId = $state('');
	let sheetFont = $state('times');
	let figScale = $state(80);
	let pickerSec = $state(null); // pattern section the picker is open for

	onMount(() => {
		const saved = localStorage.getItem('pl-sheetfont-v2');
		if (['paperlab', 'times', 'arial', 'cambria', 'stix'].includes(saved)) sheetFont = saved;
		const n = sessionStorage.getItem('pl-model-note');
		if (n) {
			note = { ok: false, text: n };
			sessionStorage.removeItem('pl-model-note');
		}
	});
	$effect(() => {
		if (browser) localStorage.setItem('pl-sheetfont-v2', sheetFont);
	});
	$effect(() => {
		if (!cartId && $cartStore.carts.length > 0) cartId = $cartStore.activeId ?? $cartStore.carts[0].id;
	});
	const activeCart = $derived($cartStore.carts.find((c) => c.id === cartId) ?? null);

	const filled = (sec) => draft?.sections.find((s) => s.id === sec.id)?.blockIds.length ?? 0;
	const totalQs = $derived(num.total);
	const labelOf = (bid) => {
		const n = num.byBlock[bid] ?? [];
		return n.length > 1 ? `Q${n[0]}–${n[n.length - 1]}` : n.length ? `Q${n[0]}` : '—';
	};
	const takenAll = () => order.map((b) => ({ paperId: b.paperId, number: b.number }));

	function say(ok, text) {
		note = { ok, text };
		setTimeout(() => (note = null), 9000);
	}

	async function draw(sid, count, taken = takenAll()) {
		const r = await api.modelGenerate({
			pattern,
			options: draft.options,
			sections: [{ id: sid, count }],
			taken,
			record: true
		});
		return r.sections[0];
	}

	const asKeys = (blocks) => blocks.map((b) => ({ paperId: b.paperId, number: b.number }));
	const blocksOf = (sid) => (draft.sections.find((s) => s.id === sid)?.blockIds ?? []).map((id) => draft.blocks[id]).filter(Boolean);

	async function fill(sec, replace) {
		if (busy) return;
		busy = sec.id;
		try {
			const need = replace ? sec.units : sec.units - filled(sec);
			if (need <= 0) return say(true, 'Section is already full.');
			if (!replace) {
				const got = await draw(sec.id, need);
				model.addToSection(sec.id, got.items);
				return say(got.items.length >= need, got.items.length ? `Added ${got.items.length} question${got.items.length === 1 ? '' : 's'}${got.note ? ` (${got.note})` : ''}.` : got.note || 'No suitable question found.');
			}
			// Redraw: prefer different questions; if there are not enough new ones, top up from the old ones
			const old = blocksOf(sec.id);
			await api.modelRelease(asKeys(old));
			let got = await draw(sec.id, need); // old ones stay in `taken`, so these are all new
			let items = got.items;
			if (items.length < need) {
				const keep = new Set([...asKeys(items)].map((k) => `${k.paperId}::${k.number}`));
				const others = order
					.filter((b) => !old.some((o) => o.id === b.blockId) && !keep.has(`${b.paperId}::${b.number}`))
					.map((b) => ({ paperId: b.paperId, number: b.number }));
				const more = await draw(sec.id, need - items.length, [...others, ...asKeys(items)]);
				items = [...items, ...more.items];
				got = { ...got, note: items.length < need ? got.note || `only ${items.length} suitable questions found` : 'fewer new questions than needed: some were kept' };
			}
			model.replaceSection(sec.id, items);
			say(items.length >= need, `Redrew ${items.length} question${items.length === 1 ? '' : 's'}${got.note ? ` (${got.note})` : ''}.`);
		} catch (e) {
			say(false, e.message);
		} finally {
			busy = '';
		}
	}

	async function swap(bid) {
		if (busy) return;
		const sec = pattern.sections.find((s) => draft.sections.find((d) => d.id === s.id)?.blockIds.includes(bid));
		if (!sec) return;
		busy = bid;
		try {
			const old = draft.blocks[bid];
			const got = await draw(sec.id, 1);
			if (!got.items.length) return say(false, 'No other suitable question was found.');
			model.swap(bid, got.items[0]);
			await api.modelRelease([{ paperId: old.paperId, number: old.number }]).catch(() => {});
		} catch (e) {
			say(false, e.message);
		} finally {
			busy = '';
		}
	}

	function removeQ(bid) {
		const old = draft.blocks[bid];
		model.removeBlock(bid);
		if (old) api.modelRelease([{ paperId: old.paperId, number: old.number }]).catch(() => {});
	}

	const takenSet = $derived(new Set(order.map((b) => `${b.paperId}::${b.number}`)));

	function pickerAdd(rows) {
		const sec = pickerSec;
		if (!sec) return;
		const before = filled(sec);
		model.addToSection(sec.id, rows);
		const room = sec.units - before;
		say(rows.length <= room, `Added ${rows.length} question${rows.length === 1 ? '' : 's'} to Section ${sec.id.replace('S', '')}${rows.length > room ? `. The section takes ${sec.units}, so it now has more than the pattern asks for` : ''}.`);
	}

	function importCart() {
		if (!activeCart) return;
		const left = new Map(pattern.sections.map((s) => [s.id, s.units - filled(s)]));
		let added = 0;
		const skipped = [];
		const have = new Set(order.map((b) => `${b.paperId}::${b.number}`));
		for (const it of activeCart.items) {
			const k = `${it.paperId}::${it.number}`;
			const sec = pattern.sections.find((s) => (left.get(s.id) ?? 0) > 0 && accepts(s).includes(it.qtype));
			if (have.has(k) || !sec) {
				skipped.push(it);
				continue;
			}
			model.addToSection(sec.id, [{ paperId: it.paperId, number: it.number, qtype: it.qtype, difficulty: it.difficulty ?? null }]);
			left.set(sec.id, left.get(sec.id) - 1);
			have.add(k);
			added++;
		}
		say(skipped.length === 0, `Added ${added} from "${activeCart.name}"${skipped.length ? `; ${skipped.length} skipped (no matching section with room, or already in the paper)` : ''}.`);
	}

	// marks the user corrects (e.g. to match the official paper): re-describe so instructions follow
	let editTimer;
	function editPattern(mutator) {
		const next = JSON.parse(JSON.stringify(pattern));
		mutator(next);
		clearTimeout(editTimer);
		editTimer = setTimeout(async () => {
			try {
				model.setPattern(await api.modelDescribe(next));
			} catch (e) {
				say(false, e.message);
			}
		}, 300);
	}
	const setMark = (sid, key, v) => {
		const n = Math.max(0, Math.floor(Number(v)));
		if (!Number.isFinite(n)) return;
		editPattern((p) => {
			const s = p.sections.find((x) => x.id === sid);
			s[key] = n;
		});
	};
	const setMinutes = (v) => {
		const n = Math.floor(Number(v));
		if (n > 0) editPattern((p) => (p.minutes = n));
	};

	async function exportWord() {
		if (busy || !previewEl) return;
		busy = 'word';
		try {
			const base = draft.title?.trim() || 'model-paper';
			const { missing } = await downloadDocx(previewEl, previewMode === 'answers' ? `${base} - answers` : base);
			say(missing === 0, missing ? `Word file saved, but ${missing} figure${missing === 1 ? '' : 's'} could not be loaded.` : 'Word file saved.');
		} catch (e) {
			say(false, `Word export failed: ${e.message}`);
		} finally {
			busy = '';
		}
	}
	async function exportPdf() {
		if (busy || !previewEl) return;
		busy = 'pdf';
		try {
			const base = draft.title?.trim() || 'model-paper';
			const { missing } = await downloadPdf(previewEl, previewMode === 'answers' ? `${base} - answers` : base);
			say(missing === 0, missing ? `PDF saved, but ${missing} figure${missing === 1 ? '' : 's'} could not be loaded.` : 'PDF saved.');
		} catch (e) {
			say(false, `PDF export failed: ${e.message}`);
		} finally {
			busy = '';
		}
	}

	function startOver() {
		model.clear();
		goto('/model');
	}
</script>

<svelte:head><title>Model paper - PaperLab</title></svelte:head>

{#if !draft || !pattern}
	<div class="none">
		<h1>No model paper yet</h1>
		<p class="pl-sub">Choose an exam pattern first, then generate a paper or build it by hand.</p>
		<a class="pl-btn pl-btn-primary" href="/model">Create a model paper</a>
	</div>
{:else}
	<div class="page">
		<header class="topbar">
			<span class="ident">Model paper</span>
			<div class="seg" role="group" aria-label="Preview mode">
				<button type="button" class:active={previewMode === 'questions'} aria-pressed={previewMode === 'questions'} onclick={() => (previewMode = 'questions')}>Question Sheet</button>
				<button type="button" class:active={previewMode === 'answers'} aria-pressed={previewMode === 'answers'} onclick={() => (previewMode = 'answers')}>Answer Sheet</button>
			</div>
			<span class="docstatus" role="status">{pattern.label} · {totalQs} of {pattern.questions} questions · {pattern.total} marks</span>
			<div class="actions">
				<select bind:value={sheetFont} aria-label="Sheet body font">
					<option value="paperlab">Inter</option>
					<option value="times">Times (Chaitanya)</option>
					<option value="arial">Arial (FITJEE)</option>
					<option value="cambria">Cambria</option>
					<option value="stix">STIX Two Text</option>
				</select>
				<button type="button" class="pl-btn" onclick={() => (confirmNew = true)}>New</button>
				<button type="button" class="pl-btn" disabled={!!busy || totalQs === 0} onclick={exportWord}>{busy === 'word' ? 'Exporting…' : 'Word (.docx)'}</button>
				<button type="button" class="pl-btn pl-btn-primary" disabled={!!busy || totalQs === 0} onclick={exportPdf}>{busy === 'pdf' ? 'Saving…' : 'Save PDF'}</button>
				<button type="button" class="pl-btn" onclick={() => window.print()}>Print</button>
			</div>
		</header>

		{#if note}<div class={note.ok ? 'note ok' : 'note'} role="status">{note.text}</div>{/if}
		{#if confirmNew}
			<div class="note" role="alert">
				<span>Discard this model paper and start a new one?</span>
				<span class="errbtns">
					<button type="button" class="pl-btn pl-btn-primary" onclick={startOver}>Discard paper</button>
					<button type="button" class="pl-btn" onclick={() => (confirmNew = false)}>Keep</button>
				</span>
			</div>
		{/if}

		<div class="workspace">
			<div class="editor">
				<div class="card">
					<label class="field">Title
						<input value={draft.title} oninput={(e) => model.setTitle(e.currentTarget.value)} placeholder={`${pattern.label} (Physics) — model paper`} />
					</label>
					<label class="field inline">Time (minutes)
						<input class="num" inputmode="numeric" value={pattern.minutes} onchange={(e) => setMinutes(e.currentTarget.value)} />
					</label>
					<p class="pl-sub">{pattern.note}</p>
				</div>

				<div class="card">
					<h3>Marking scheme</h3>
					<table>
						<thead><tr><th>Sec</th><th>Type</th><th>Filled</th><th>Marks each</th><th>Negative</th><th>Max</th></tr></thead>
						<tbody>
							{#each pattern.sections as s (s.id)}
								<tr>
									<td>{s.id.replace('S', '')}</td>
									<td>{s.typeName}</td>
									<td class:low={filled(s) < s.units}>{filled(s)} / {s.units}</td>
									<td><input class="mk" inputmode="numeric" value={s.c} disabled={s.type === 'matrix'} onchange={(e) => setMark(s.id, 'c', e.currentTarget.value)} aria-label={`Section ${s.id.replace('S', '')} marks`} /></td>
									<td><input class="mk" inputmode="numeric" value={s.neg} disabled={s.type === 'matrix'} onchange={(e) => setMark(s.id, 'neg', e.currentTarget.value)} aria-label={`Section ${s.id.replace('S', '')} negative marks`} /></td>
									<td>{s.max}</td>
								</tr>
							{/each}
						</tbody>
						<tfoot><tr><td colspan="5">Physics total</td><td>{pattern.total}</td></tr></tfoot>
					</table>
					<p class="pl-sub">Correct the marks to match the official paper; the instructions on the sheet follow.</p>
				</div>

				{#each pattern.sections as s (s.id)}
					{@const sec = draft.sections.find((d) => d.id === s.id)}
					<div class="card">
						<div class="sechead">
							<h3>Section {s.id.replace('S', '')} · {s.typeName}</h3>
							<span class="pl-sub">{filled(s)} of {s.units}{s.sets && s.per ? ` (${s.sets} × ${s.per})` : ''} · {s.max} marks</span>
						</div>
						<div class="secbtns">
							<button type="button" class="pl-btn" disabled={!!busy} onclick={() => (pickerSec = s)}>Add questions…</button>
							{#if filled(s) < s.units}
								<button type="button" class="pl-btn" disabled={!!busy} onclick={() => fill(s, false)}>{busy === s.id ? 'Picking…' : 'Fill empty places'}</button>
							{/if}
							{#if filled(s) > 0}
								<button type="button" class="pl-btn" disabled={!!busy} onclick={() => fill(s, true)}>Redraw section</button>
							{/if}
						</div>
						<ol class="qs">
							{#each sec?.blockIds ?? [] as bid, i (bid)}
								{@const b = draft.blocks[bid]}
								<li>
									<span class="qn">{labelOf(bid)}</span>
									<span class="qinfo">Paper {b.paperId} · #{b.number}<small> · {qtypeLabel(b.qtype)}{b.difficulty ? ` · ${b.difficulty}` : ''}</small></span>
									<span class="qbtns">
										<button type="button" class="mini" disabled={i === 0} onclick={() => model.moveBlock(bid, -1)} aria-label="Move up" title="Move up">↑</button>
										<button type="button" class="mini" disabled={i === sec.blockIds.length - 1} onclick={() => model.moveBlock(bid, 1)} aria-label="Move down" title="Move down">↓</button>
										<button type="button" class="mini" disabled={!!busy} onclick={() => swap(bid)} aria-label={`Swap ${labelOf(bid)} for another`} title="Swap for another random question">{busy === bid ? '…' : '⇄'}</button>
										<button type="button" class="mini" onclick={() => removeQ(bid)} aria-label={`Remove ${labelOf(bid)}`} title="Remove">✕</button>
									</span>
								</li>
							{:else}
								<li class="empty">No questions yet.</li>
							{/each}
						</ol>
					</div>
				{/each}

				<div class="card">
					<h3>Add a whole cart</h3>
					<p class="pl-sub">Every question goes to the first section of its type that still has room. To choose questions one by one, use <em>Add questions…</em> on a section.</p>
					<div class="secbtns">
						<select bind:value={cartId} aria-label="Source cart">
							{#each $cartStore.carts as c (c.id)}<option value={c.id}>{c.name} · {c.items.length}</option>{/each}
						</select>
						<button type="button" class="pl-btn" disabled={!activeCart || activeCart.items.length === 0} onclick={importCart}>Import</button>
					</div>
				</div>
			</div>

			<div class="previewcol">
				<div class="panehead">
					<span>Preview</span>
					<label class="figctl">Fig
						<input type="range" min="40" max="150" step="5" bind:value={figScale} aria-label="Figure size percent" />
						<span class="pl-sub">{figScale}%</span>
					</label>
				</div>
				<div class="previewscroll" bind:this={previewEl}>
					{#if previewMode === 'questions'}
						<QuestionSheetPreview title={draft.title || `${pattern.label} (Physics) — model paper`} ordered={order} numbering={num} sections={draft.sections} mode="paper" bare={true} font={sheetFont} {figScale} {pattern} />
					{:else}
						<AnswerSheetPreview
							title={draft.title || `${pattern.label} (Physics) — model paper`} numbering={num} blocks={draft.blocks}
							overrides={draft.keyOverride} parsed={$parsedKeys} ordered={order} bare={true} font={sheetFont} {figScale}
							onOverride={(bid, i, t) => model.setOverride(bid, i, t)}
						/>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}

{#if pickerSec && draft}
	<ModelPicker
		section={pickerSec}
		fits={(qt) => accepts(pickerSec).includes(qt)}
		taken={takenSet}
		carts={$cartStore.carts}
		activeCartId={cartId}
		onAdd={pickerAdd}
		onClose={() => (pickerSec = null)}
	/>
{/if}

<style>
	.none {
		max-width: 520px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		align-items: flex-start;
	}
	.page {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	.topbar {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		padding: 8px 16px;
		background: var(--pl-surface);
		border-bottom: 1px solid var(--pl-line);
	}
	.ident {
		font-weight: 700;
	}
	.docstatus {
		color: var(--pl-ink-soft);
		font-size: 0.8rem;
	}
	.actions {
		margin-left: auto;
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
	}
	.seg {
		display: inline-flex;
		gap: 2px;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		padding: 3px;
	}
	.seg button {
		border: none;
		background: none;
		border-radius: var(--pl-radius-pill);
		padding: 5px 14px;
		min-height: 0;
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
	}
	.seg button.active {
		background: var(--pl-surface);
		color: var(--pl-ink);
		box-shadow: var(--pl-shadow-sm);
	}
	select,
	input {
		min-height: 34px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-paper);
		color: var(--pl-ink);
		padding: 0 10px;
		font: inherit;
	}
	.note {
		margin: 8px 16px 0;
		padding: 8px 12px;
		border: 1px solid var(--pl-seal);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-seal-soft);
		font-size: 0.85rem;
		display: flex;
		gap: 12px;
		align-items: center;
		flex-wrap: wrap;
	}
	.note.ok {
		border-color: var(--pl-line);
		background: var(--pl-pine-soft);
	}
	.errbtns {
		display: inline-flex;
		gap: 8px;
	}
	.workspace {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(320px, 400px) 1fr;
		gap: 0;
	}
	.editor {
		overflow-y: auto;
		padding: 12px 16px 32px;
		display: flex;
		flex-direction: column;
		gap: 12px;
		border-right: 1px solid var(--pl-line);
	}
	.card {
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.card h3 {
		font-size: 0.9rem;
		margin: 0;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.78rem;
		font-weight: 600;
	}
	.field.inline {
		flex-direction: row;
		align-items: center;
		gap: 10px;
	}
	.num {
		width: 80px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.8rem;
	}
	th,
	td {
		text-align: left;
		padding: 5px 4px;
		border-bottom: 1px solid var(--pl-line);
	}
	th {
		font-size: 0.65rem;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--pl-ink-soft);
	}
	tfoot td {
		font-weight: 700;
		border-bottom: none;
	}
	td.low {
		color: var(--pl-seal);
		font-weight: 700;
	}
	.mk {
		width: 46px;
		min-height: 28px;
		padding: 0 6px;
	}
	.sechead {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 8px;
		flex-wrap: wrap;
	}
	.secbtns {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.qs {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.qs li {
		display: grid;
		grid-template-columns: 64px 1fr auto;
		align-items: center;
		gap: 6px;
		padding: 5px 0;
		border-top: 1px solid var(--pl-line);
		font-size: 0.82rem;
	}
	.qs li.empty {
		display: block;
		color: var(--pl-ink-soft);
	}
	.qn {
		font-weight: 700;
	}
	.qbtns {
		display: inline-flex;
		gap: 4px;
	}
	.mini {
		min-height: 28px;
		min-width: 28px;
		padding: 0 6px;
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		background: none;
		color: var(--pl-ink);
		font-size: 0.85rem;
	}
	.mini:disabled {
		opacity: 0.35;
	}
	.mini:hover:not(:disabled) {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.previewcol {
		min-width: 0;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	.panehead {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 16px;
		font-size: 0.78rem;
		font-weight: 700;
		color: var(--pl-ink-soft);
	}
	.figctl {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		font-weight: 600;
	}
	.figctl input {
		min-height: 0;
		padding: 0;
	}
	.previewscroll {
		flex: 1;
		min-height: 0;
		overflow: auto;
		padding: 4px 16px 32px;
	}
	@media (max-width: 900px) {
		.page {
			height: auto;
			overflow: visible;
		}
		.workspace {
			grid-template-columns: 1fr;
		}
		.editor {
			border-right: none;
			max-height: 60vh;
		}
	}
	@media print {
		.page {
			height: auto;
			overflow: visible;
		}
		.topbar,
		.note,
		.editor,
		.panehead {
			display: none;
		}
		.workspace {
			display: block;
		}
		.previewscroll {
			overflow: visible;
			padding: 0;
		}
	}
</style>
