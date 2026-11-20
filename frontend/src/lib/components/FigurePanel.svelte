<script>
	import { untrack } from 'svelte';
	import { api } from '$lib/api.js';

	/**
	 * Figure manager: thumbnail grid with Adjust (re-crop) / Replace /
	 * Delete (two-step, trash + undo) and an Add card. All destructive ops
	 * keep bytes in trash; nothing is unlinked except via Empty trash.
	 */
	let { paperId, qn, rev = 0, onChanged = () => {}, reviewJobId = null, ejeePaperId = null } = $props();
	// Both EJEE modes crop from the original source image, so they may grow beyond the current PNG.
	const sourceMode = $derived(!!reviewJobId || !!ejeePaperId);

	let figures = $state([]);
	let trash = $state([]);
	let message = $state('');
	let busy = $state(false);

	let adjusting = $state(null);
	let box = $state({ left: 0, top: 0, right: 100, bottom: 100 });
	let angle = $state(0);
	let preview = $state('');
	let previewEdges = $state([]);
	let sourceEdgeReached = $derived(previewEdges.some(edge =>
		({ left: box.left === 0, top: box.top === 0, right: box.right === 100, bottom: box.bottom === 100 })[edge]
	));
	let previewError = $state('');
	let confirmEdges = $state(false);
	let cropError = $state('');
	let previewSeq = 0;
	let previewTimer = null;
	let replacing = $state(null);
	let replaceFile = $state(null);
	let replacePreview = $state('');
	let arming = $state(null);
	let lastDeleted = $state(null);

	let addTarget = $state('question');
	let addName = $state('');
	let addFile = $state(null);
	let addInput = $state(null);

	async function load() {
		try {
			if (ejeePaperId) {
				const rows = await api.getEjeeFigures(ejeePaperId, qn);
				figures = rows.map(row => ({
					name:row.name, side:row.side, usedIn:[], entry:row,
					mode:row.edited ? 'Edited' : row.needs_check ? 'Check crop' : '',
					url:api.ejeeFigureSource(ejeePaperId, qn, row.name),
					thumb:`/api/ejee/library/papers/${ejeePaperId}/questions/${encodeURIComponent(qn)}/figures/${row.name}`
				}));
				if (!rows.length) message = 'No source crops are archived for this question, so its diagrams cannot be re-cropped.';
				return;
			}
			if (reviewJobId) {
				const rows = await api.getEjeeCropReview(reviewJobId);
				figures = rows.map(row => ({
					name:`Q${row.number} · ${row.name} · page ${row.page}`, side:row.side, usedIn:[],
					mode:row.saved ? 'Saved' : 'Needs review', url:api.ejeeCropSource(reviewJobId,row), entry:row
				}));
				if (!rows.length) message = 'No diagram crops were recorded for this review.';
				return;
			}
			[figures, trash] = await Promise.all([
				api.listFigures(paperId, qn),
				api.listTrash(paperId, qn)
			]);
		} catch (e) {
			message = `Could not load figures: ${e.message}`;
		}
	}

	async function refresh() {
		await load();
		onChanged();
	}

	function bust(url) {
		return `${url}?v=${rev}`;
	}

	function openAdjust(fig) {
		adjusting = fig.name;
		replacing = null;
		arming = null;
		box = { left: 0, top: 0, right: 100, bottom: 100 };
		if (fig.entry?.box?.every(Number.isFinite)) {
			const [x,y,w,h] = fig.entry.box;
			box = {left:Math.max(0, x/10), top:Math.max(0, y/10), right:Math.min(100,(x+w)/10), bottom:Math.min(100,(y+h)/10)};
		}
		angle = fig.entry?.saved?.rotation ?? 0;
		setPreview('');
		cropError = '';
		message = '';
	}

	function setPreview(url) {
		if (preview) URL.revokeObjectURL(preview);
		preview = url;
	}

	let dragStart = null;
	function pointerPos(e) {
		const rect = e.currentTarget.getBoundingClientRect();
		return { x: Math.min(100, Math.max(0, (e.clientX - rect.left) / rect.width * 100)),
			y: Math.min(100, Math.max(0, (e.clientY - rect.top) / rect.height * 100)) };
	}
	function dragDown(e) {
		if (!sourceMode) return;
		e.currentTarget.setPointerCapture(e.pointerId);
		dragStart = pointerPos(e);
	}
	function dragMove(e) {
		if (!dragStart) return;
		const p = pointerPos(e);
		if (Math.abs(p.x - dragStart.x) < 1 || Math.abs(p.y - dragStart.y) < 1) return;
		box = { left: Math.min(dragStart.x, p.x), right: Math.max(dragStart.x, p.x),
			top: Math.min(dragStart.y, p.y), bottom: Math.max(dragStart.y, p.y) };
	}
	function dragUp() { dragStart = null; }

	async function restoreOriginal(fig) {
		if (!window.confirm(`Restore the original import crop of ${fig.name}?`)) return;
		busy = true; message = '';
		try { await api.restoreEjeeFigure(ejeePaperId, qn, fig.name); adjusting = null; message = `Restored ${fig.name}.`; await refresh(); }
		catch (e) { message = `Restore failed: ${e.message}`; } finally { busy = false; }
	}

	function stepAngle(d) {
		angle = Math.min(180, Math.max(-180, angle + d));
	}

	function queuePreview(fig) {
		// Debounced exact-result preview: what Save would write, read-only.
		clearTimeout(previewTimer);
		const seq = ++previewSeq;
		if (sourceMode) setPreview('');
		previewEdges = [];
		previewError = '';
		confirmEdges = false;
		cropError = '';
		previewTimer = setTimeout(async () => {
			try {
				const bounds = {
					left: box.left / 100,
					top: box.top / 100,
					right: box.right / 100,
					bottom: box.bottom / 100,
					rotate: angle
				};
				const { url, edges } = reviewJobId ? await api.previewEjeeCrop(reviewJobId, fig.entry, bounds)
					: ejeePaperId ? await api.previewEjeeFigure(ejeePaperId, qn, fig.name, bounds)
					: { url: await api.previewFigure(paperId, qn, fig.name, bounds), edges: [] };
				if (seq === previewSeq && adjusting === fig.name) {
					setPreview(url);
					previewEdges = edges;
				} else URL.revokeObjectURL(url);
			} catch (e) {
				if (sourceMode && seq === previewSeq && adjusting === fig.name) previewError = e.message;
			}
		}, 300);
	}

	$effect(() => {
		// Re-render the result preview on any slider move while adjusting.
		const { left, top, right, bottom } = box;
		const deg = angle;
		if (adjusting && left != null && top != null && right != null && bottom != null && deg != null) {
			const fig = figures.find((f) => f.name === adjusting);
			if (fig) untrack(() => queuePreview(fig));
		}
	});

	async function saveCrop(fig) {
		busy = true;
		message = '';
		cropError = '';
		try {
			const bounds = {
				left: box.left / 100,
				top: box.top / 100,
				right: box.right / 100,
				bottom: box.bottom / 100,
				rotate: angle
			};
			if (reviewJobId) await api.saveEjeeCrop(reviewJobId, fig.entry, { ...bounds, confirm_edges: confirmEdges });
			else if (ejeePaperId) await api.saveEjeeFigure(ejeePaperId, qn, fig.name, { ...bounds, confirm_edges: confirmEdges });
			else await api.cropFigure(paperId, qn, fig.name, bounds);
			message = reviewJobId ? `Saved ${fig.name}. Resume import to apply the crop.`
				: ejeePaperId ? `Saved ${fig.name}. The original crop is kept and can be restored.`
				: `Saved ${fig.name} - original kept in trash.`;
			adjusting = null;
			await refresh();
		} catch (e) {
			cropError = `Crop failed: ${e.message}`;
		} finally {
			busy = false;
		}
	}

	function pickReplace(fig, files) {
		replacing = fig.name;
		adjusting = null;
		replaceFile = files?.[0] ?? null;
		if (replacePreview) URL.revokeObjectURL(replacePreview);
		replacePreview = replaceFile ? URL.createObjectURL(replaceFile) : '';
	}

	async function uploadReplace(fig) {
		if (!replaceFile) return;
		busy = true;
		message = '';
		try {
			await api.replaceFigure(paperId, qn, fig.name, replaceFile);
			message = `Replaced ${fig.name} - previous bytes kept in trash.`;
			replacing = null;
			replaceFile = null;
			await refresh();
		} catch (e) {
			message = `Replace failed: ${e.message}`;
		} finally {
			busy = false;
		}
	}

	async function remove(fig) {
		if (arming !== fig.name) {
			arming = fig.name;
			message = '';
			return;
		}
		arming = null;
		busy = true;
		try {
			const res = await api.deleteFigure(paperId, qn, fig.name);
			lastDeleted = res.trash;
			message = `Deleted ${fig.name} - kept in trash.`;
			await refresh();
		} catch (e) {
			message = `Delete failed: ${e.message}`;
		} finally {
			busy = false;
		}
	}

	async function restore(trashName) {
		busy = true;
		message = '';
		try {
			await api.restoreFigure(paperId, qn, trashName);
			if (lastDeleted === trashName) lastDeleted = null;
			message = 'Restored from trash.';
			await refresh();
		} catch (e) {
			message = `Restore failed: ${e.message}`;
		} finally {
			busy = false;
		}
	}

	async function emptyTrashItem(trashName) {
		busy = true;
		try {
			await api.emptyTrashFigure(paperId, qn, trashName);
			if (lastDeleted === trashName) lastDeleted = null;
			message = 'Trash item deleted forever.';
			await refresh();
		} catch (e) {
			message = `Empty trash failed: ${e.message}`;
		} finally {
			busy = false;
		}
	}

	async function add() {
		if (!addFile) return;
		busy = true;
		message = '';
		try {
			const fig = await api.addFigure(paperId, qn, addTarget, addName.trim(), addFile);
			message = `Attached ${fig.name} to ${addTarget}.`;
			addName = '';
			addFile = null;
			if (addInput) addInput.value = '';
			await refresh();
		} catch (e) {
			message = `Add failed: ${e.message}`;
		} finally {
			busy = false;
		}
	}

	load();
</script>

<div class="figman">
	{#if message}<p class="pl-sub" role="status">{message}</p>{/if}
	{#if lastDeleted}
		<div class="row">
			<button type="button" class="pl-btn" disabled={busy} onclick={() => restore(lastDeleted)}>
				Undo delete
			</button>
		</div>
	{/if}

	<div class="grid">
		{#each figures as fig (fig.name)}
			<div class="pl-card fig">
				<img class="thumb" src={bust(fig.thumb || fig.url)} alt={fig.name} loading="lazy" />
				<div class="pl-mono fname">{fig.name}</div>
				<div class="badges">
					<span class="pl-chip">{fig.side}</span>
					{#if fig.mode}<span class="pl-chip">{fig.mode}</span>{/if}
					{#if !sourceMode && fig.usedIn.length === 0}
						<span class="pl-chip">unused</span>
					{:else if !sourceMode}
						{#each fig.usedIn as u (u)}<span class="pl-chip">in: {u}</span>{/each}
					{/if}
				</div>
				<div class="row">
					<button type="button" class="pl-btn" onclick={() => openAdjust(fig)}>Adjust</button>
					{#if ejeePaperId && fig.entry.edited}
						<button type="button" class="pl-btn" disabled={busy} onclick={() => restoreOriginal(fig)}>Restore original</button>
					{/if}
					{#if !sourceMode}
					<label class="pl-btn filebtn">
						Replace
						<input
							type="file"
							accept="image/png,image/jpeg"
							hidden
							onchange={(e) => pickReplace(fig, e.currentTarget.files)}
						/>
					</label>
					<button
						type="button"
						class="pl-btn pl-btn-danger"
						disabled={busy}
						onclick={() => remove(fig)}
					>
						{arming === fig.name ? 'Confirm delete' : 'Delete'}
					</button>
					{/if}
				</div>
				{#if arming === fig.name}
					<p class="pl-sub warn">
						{#if fig.usedIn.length}
							Used in: {fig.usedIn.join(' + ')} - refs will be removed (validated first).
						{:else}
							Unused figure - safe to delete.
						{/if}
					</p>
				{/if}
				{#if adjusting === fig.name}
					<div class="cropbox">
						<div class="cropwrap" class:draw={sourceMode} role="presentation"
							onpointerdown={dragDown} onpointermove={dragMove} onpointerup={dragUp} onpointercancel={dragUp}>
							<img src={bust(fig.url)} alt="Original for cropping" draggable="false" />
							<div
								class="croprect"
								style="left: {box.left}%; top: {box.top}%; width: {Math.max(box.right - box.left, 0)}%; height: {Math.max(box.bottom - box.top, 0)}%;"
								aria-hidden="true"
							></div>
						</div>
						<label>Left % <input type="range" min="0" max="99" step={sourceMode ? 0.1 : 1} bind:value={box.left} /></label>
						<label>Right % <input type="range" min="1" max="100" step={sourceMode ? 0.1 : 1} bind:value={box.right} /></label>
						<label>Top % <input type="range" min="0" max="99" step={sourceMode ? 0.1 : 1} bind:value={box.top} /></label>
						<label>Bottom % <input type="range" min="1" max="100" step={sourceMode ? 0.1 : 1} bind:value={box.bottom} /></label>
						<div class="rotctl">
							<span id="rot-label">Rotate</span>
							<div class="rotrow" role="group" aria-labelledby="rot-label">
								<button type="button" class="pl-btn rotbtn" aria-label="Rotate 1 degree counter-clockwise" onclick={() => stepAngle(-1)}>−</button>
								<input type="range" min="-180" max="180" step="1" bind:value={angle} aria-label="Rotation degrees" />
								<button type="button" class="pl-btn rotbtn" aria-label="Rotate 1 degree clockwise" onclick={() => stepAngle(1)}>+</button>
								<span class="pl-mono rotval">{angle}°</span>
							</div>
						</div>
						{#if preview}
							<div class="prevwrap">
								<p class="pl-sub prevcap">Result preview — exactly what Save writes</p>
								<img src={preview} alt="Rotated result preview" class="previmg" />
							</div>
						{/if}
						{#if sourceMode}<p class="pl-sub">Drag on the original image to draw the crop, then fine-tune with the sliders.</p>{:else}<p class="pl-sub">Crop stays inside the current image. To expand, re-crop from the PDF.</p>{/if}
						{#if previewError || cropError}<p class="pl-sub warn" role="alert">{cropError || previewError}</p>{/if}
						{#if previewEdges.length}
							<p class="pl-sub warn">
								Source ink touches the {previewEdges.join(', ')} edge.
								{#if sourceEdgeReached}The crop already reaches the source image boundary on a flagged edge.{/if}
								If the preview shows the full diagram, confirm it below to save.
							</p>
							<label><input type="checkbox" bind:checked={confirmEdges} /> The preview contains the complete diagram.</label>
						{/if}
						<div class="row">
							<button type="button" class="pl-btn pl-btn-primary" disabled={busy || (sourceMode && (!preview || (previewEdges.length > 0 && !confirmEdges)))} onclick={() => saveCrop(fig)}>Save crop</button>
							<button type="button" class="pl-btn" onclick={() => (adjusting = null)}>Cancel</button>
						</div>
					</div>
				{/if}
				{#if replacing === fig.name}
					<div class="cropbox">
						{#if replacePreview}
							<img src={replacePreview} alt="Replacement preview" class="replaceprev" />
						{/if}
						<p class="pl-sub">Refs stay untouched - only the image bytes change. Old bytes go to trash.</p>
						<div class="row">
							<button type="button" class="pl-btn pl-btn-primary" disabled={busy || !replaceFile} onclick={() => uploadReplace(fig)}>Upload replacement</button>
							<button type="button" class="pl-btn" onclick={() => (replacing = null)}>Cancel</button>
						</div>
					</div>
				{/if}
			</div>
		{/each}

		{#if !sourceMode}<div class="pl-card add">
			<h3>Add a figure</h3>
			<div class="segrow" role="group" aria-label="Attach to">
				{#each ['question', 'solution'] as t (t)}
					<button
						type="button"
						class="pl-btn"
						class:pl-btn-primary={addTarget === t}
						aria-pressed={addTarget === t}
						onclick={() => (addTarget = t)}
					>
						{t}
					</button>
				{/each}
			</div>
			<label>Filename (blank = next free name)
				<input type="text" bind:value={addName} placeholder="qfigN.png" />
			</label>
			<label>Cropped image (PNG/JPG)
				<input
					type="file"
					accept="image/png,image/jpeg"
					bind:this={addInput}
					onchange={(e) => (addFile = e.currentTarget.files?.[0] ?? null)}
				/>
			</label>
			<div class="row">
				<button type="button" class="pl-btn pl-btn-primary" disabled={!addFile || busy} onclick={add}>Add figure</button>
			</div>
		</div>{/if}
	</div>

	{#if trash.length > 0}
		<h3>Trash</h3>
		<p class="pl-sub">Bytes are safe here until deleted forever. Restoring refuses if the name is taken.</p>
		<ul class="trash">
			{#each trash as t (t.name)}
				<li>
					<span class="pl-mono">{t.original}</span>
					<button type="button" class="pl-btn" disabled={busy} onclick={() => restore(t.name)}>Restore</button>
					<button type="button" class="pl-btn pl-btn-danger" disabled={busy} onclick={() => emptyTrashItem(t.name)}>Delete forever</button>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.figman {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 12px;
	}
	.thumb {
		max-width: 120px;
		max-height: 120px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
	}
	.fname {
		margin-top: 8px;
		word-break: break-all;
	}
	.badges {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 8px 0;
	}
	.badges .pl-chip {
		margin-right: 0;
	}
	.add {
		display: flex;
		flex-direction: column;
		gap: 10px;
		min-width: 0;
	}
	.add h3 {
		margin: 0;
	}
	.segrow {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.add label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.8rem;
		font-weight: 600;
		min-width: 0;
	}
	.add input[type='text'],
	.add input[type='file'] {
		width: 100%;
		max-width: 100%;
		min-width: 0;
	}
	.row {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		align-items: center;
	}
	.filebtn {
		cursor: pointer;
	}
	.warn {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-ochre-soft);
		padding: 8px 12px;
	}
	.cropbox {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-top: 8px;
		border-top: 1px solid var(--pl-line);
		padding-top: 8px;
	}
	.cropbox label {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 0.8rem;
		font-weight: 600;
	}
	.rotctl {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 0.8rem;
		font-weight: 600;
	}
	.rotrow {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.rotrow input[type='range'] {
		flex: 1;
		min-width: 0;
	}
	.rotbtn {
		padding: 6px 12px;
		min-height: 0;
		font-size: 1rem;
		line-height: 1;
		flex-shrink: 0;
	}
	.rotval {
		min-width: 3.5ch;
		text-align: right;
		flex-shrink: 0;
	}
	.cropwrap {
		position: relative;
		display: inline-block;
		max-width: 100%;
		overflow: hidden;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
	}
	.cropwrap.draw { cursor: crosshair; touch-action: none; user-select: none; }
	.cropwrap img {
		display: block;
		max-width: 100%;
		height: auto;
	}
	.croprect {
		position: absolute;
		border: 2px dashed var(--pl-seal);
		background: rgb(140 47 40 / 0.08);
		box-shadow: 0 0 0 9999px rgb(0 0 0 / 0.45);
		pointer-events: none;
	}
	.replaceprev {
		max-width: 200px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
	}
	.prevwrap {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.prevcap {
		margin: 0;
	}
	.previmg {
		max-width: 220px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
	}
	.add h3 {
		font-size: 1.05rem;
	}
	.trash {
		list-style: none;
		padding: 0;
		margin: 8px 0 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.trash li {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	h3 {
		font-size: 1.05rem;
		margin: 8px 0 0;
	}
	.pl-btn-danger {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.pl-btn-danger:hover {
		background: var(--pl-seal);
		color: #fff;
	}
</style>
