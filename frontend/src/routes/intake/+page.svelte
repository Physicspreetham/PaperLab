<script>
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	import SegmentedTabs from '$lib/components/SegmentedTabs.svelte';

	const isArchivist = $derived($role === 'archivist');

	let jobs = $state({ running: [], finished: [] });
	let error = $state('');
	let refreshing = $state(false);

	// Stage tab
	let qFiles = $state(null);
	let sFiles = $state(null);
	let staged = $state([]);
	let toDelete = $state([]);
	let staging = $state(false);
	let stageMsg = $state('');

	// Verify tab
	let pairs = $state([]);
	let solutions = $state([]);
	let choices = $state({});
	let registering = $state(false);
	let verifyMsg = $state('');

	// Pipeline tab
	let papers = $state([]);
	let selected = $state([]);
	let mode = $state('sequential');
	let force = $state(false);
	let starting = $state(false);
	let armDelPapers = $state(false);
	let deletingPapers = $state(false);
	let runMsg = $state('');

	const tabs = [
		{ id: 'stage', label: 'Stage files' },
		{ id: 'verify', label: 'Verify pairs' },
		{ id: 'pipeline', label: 'Pipeline' }
	];
	const tab = $derived(tabs.find(({ id }) => id === $page.url.searchParams.get('tab'))?.id ?? 'stage');

	function setTab(id) {
		const url = new URL($page.url);
		url.searchParams.set('tab', id);
		void goto(url, { keepFocus: true, noScroll: true });
	}

	function paperName(paper) {
		return paper.title || paper.questionPdf?.split('/').pop() || 'Untitled paper';
	}

	async function loadJobs() {
		jobs = await api.getJobs();
	}

	async function loadStaged() {
		staged = (await api.listUploads()).staged;
	}

	async function loadPairs() {
		const res = await api.suggestPairs();
		pairs = res.pairs;
		solutions = res.solutions;
		choices = Object.fromEntries(
			pairs.map((p) => [p.question, p.solution || 'none'])
		);
	}

	async function loadPapers() {
		const queued = (await api.listPapers()).filter((p) => p.status !== 'done');
		papers = queued;
		const available = new Set(queued.map((paper) => paper.id));
		selected = selected.filter((id) => available.has(id));
	}

	async function refresh(loaders) {
		refreshing = true;
		error = '';
		const results = await Promise.allSettled(loaders.map((load) => load()));
		error = results.find((result) => result.status === 'rejected')?.reason.message ?? '';
		refreshing = false;
	}

	$effect(() => {
		if (isArchivist) void refresh([loadJobs, loadStaged, loadPairs, loadPapers]);
	});

	async function upload() {
		const all = [...(qFiles ?? []), ...(sFiles ?? [])];
		if (!all.length) return;
		staging = true;
		stageMsg = '';
		try {
			const form = new FormData();
			for (const f of all) form.append('files', f);
			const res = await api.uploadFiles(form);
			const nq = qFiles?.length ?? 0;
			const ns = sFiles?.length ?? 0;
			stageMsg = `Staged ${nq} question + ${ns} solution PDFs.`;
			qFiles = null;
			sFiles = null;
			await Promise.all([loadStaged(), loadPairs(), loadPapers()]);
		} catch (e) {
			stageMsg = `Upload failed: ${e.message}`;
		} finally {
			staging = false;
		}
	}

	async function removeSelected() {
		if (!toDelete.length) return;
		try {
			await api.deleteUploads(toDelete);
			toDelete = [];
			await Promise.all([loadStaged(), loadPairs()]);
		} catch (e) {
			stageMsg = `Delete failed: ${e.message}`;
		}
	}

	async function clearAll() {
		try {
			await fetch('/api/uploads/clear', { method: 'DELETE' });
			await Promise.all([loadStaged(), loadPairs()]);
		} catch (e) {
			stageMsg = `Clear failed: ${e.message}`;
		}
	}

	async function register() {
		registering = true;
		verifyMsg = '';
		try {
			const list = pairs.map((p) => {
				const c = choices[p.question];
				return {
					question: p.question,
					solution: c === 'none' ? null : c === 'same' ? p.question : c
				};
			});
			const res = await api.registerPairs(list);
			const fresh = res.registered.filter((r) => !r.reused).length;
			const reused = res.registered.length - fresh;
			verifyMsg = `Registered ${fresh} new paper(s), ${reused} already existed.`;
			await Promise.all([loadStaged(), loadPairs(), loadPapers()]);
		} catch (e) {
			verifyMsg = `Registration failed: ${e.message}`;
		} finally {
			registering = false;
		}
	}

	async function run() {
		if (!selected.length) return;
		armDelPapers = false;
		starting = true;
		runMsg = '';
		try {
			const { started } = await api.runPapers(selected, mode, force);
			runMsg = started.length ? 'Run submitted. Refresh to check progress.' : 'No new run started.';
			await refresh([loadJobs, loadPapers]);
		} catch (e) {
			runMsg = `Could not start run: ${e.message}`;
		} finally {
			starting = false;
		}
	}

	async function deleteSelectedPapers() {
		if (!selected.length || starting || deletingPapers) {
			armDelPapers = false;
			return;
		}
		if (!armDelPapers) {
			armDelPapers = true;
			return;
		}
		armDelPapers = false;
		deletingPapers = true;
		runMsg = '';
		try {
			for (const id of selected) await api.deletePaper(Number(id));
			runMsg = `Deleted ${selected.length} queued paper${selected.length === 1 ? '' : 's'} (row, outputs, managed PDFs).`;
			selected = [];
			await Promise.all([loadPapers(), loadJobs()]);
		} catch (e) {
			runMsg = `Delete failed: ${e.message}`;
		} finally {
			deletingPapers = false;
		}
	}
</script>

<svelte:head><title>Intake and Pipeline - PaperLab</title></svelte:head>

<h1>Intake &amp; Pipeline</h1>
<p class="pl-sub">Stage PDFs, verify pairs, then run the extractor. Nothing enters processing until you confirm the pairs.</p>

{#if !isArchivist}
	<div class="pl-card">
		<p>This area needs archivist access. Use the role switch in the sidebar to log in.</p>
	</div>
{:else}
	<SegmentedTabs {tabs} bind:value={() => tab, setTab} />

	{#if error}
		<div class="pl-error" role="alert" style="margin-top: 12px">
			<strong>Could not load some intake data.</strong>
			<p class="pl-mono">{error}</p>
		</div>
	{/if}

	{#if tab === 'stage'}
		<div class="pl-card panel">
			<h2>Stage files</h2>
			<p class="pl-sub">Nothing enters processing until you confirm the pairs on Verify. Filenames decide the split: solution-named files land as solutions, combined single files land as questions.</p>
			<label class="upload">
				Questions (or combined Q + Key + Solutions PDFs)
				<input type="file" accept="application/pdf" multiple bind:files={qFiles} aria-label="Question PDFs" />
			</label>
			<p class="pl-sub">Single file holding QP + Key + Solutions? Upload it above — you will pair it with “Same file” on Verify.</p>
			<label class="upload">
				Solution PDFs (separate files only)
				<input type="file" accept="application/pdf" multiple bind:files={sFiles} aria-label="Solution PDFs" />
			</label>
			<div class="row">
				<button type="button" class="pl-btn pl-btn-primary" disabled={!(qFiles?.length || sFiles?.length) || staging} onclick={upload}>
					{staging ? 'Staging…' : 'Stage files'}
				</button>
				{#if stageMsg}<span class="pl-sub" role="status">{stageMsg}</span>{/if}
			</div>
			{#if staged.length === 0}
				<p class="pl-sub">Upload PDFs above, then stage them for pairing.</p>
			{:else}
				<h3>Staged ({staged.length})</h3>
				<div class="checklist">
					{#each staged as name (name)}
						<label>
							<input type="checkbox" value={name} bind:group={toDelete} />
							<span class="pl-mono">{name}</span>
						</label>
					{/each}
				</div>
				<div class="row">
					<button type="button" class="pl-btn" disabled={!toDelete.length} onclick={removeSelected}>
						Delete selected
					</button>
					<button type="button" class="pl-btn" onclick={clearAll}>Clear staging area</button>
				</div>
			{/if}
		</div>
	{:else if tab === 'verify'}
		<div class="pl-card panel">
			<h2>Verify pairs</h2>
			<p class="pl-sub">Auto-matched by filename - correct any mismatch, then confirm. "Same file" means one PDF holds questions, key and solutions.</p>
			{#if pairs.length === 0}
				<p class="pl-sub">Nothing to pair - stage files first.</p>
			{:else}
				{#each pairs as pair (pair.question)}
					<div class="pair">
						<strong>{pair.question}</strong>
						<select bind:value={choices[pair.question]} aria-label={`Solution for ${pair.question}`}>
							<option value="none">No separate solution PDF</option>
							<option value="same">Same file (combined)</option>
							{#each solutions as s (s)}
								<option value={s}>{s}</option>
							{/each}
						</select>
					</div>
				{/each}
				<div class="row">
					<button type="button" class="pl-btn pl-btn-primary" disabled={registering} onclick={register}>
						{registering ? 'Registering…' : 'Confirm pairs & register'}
					</button>
				</div>
			{/if}
			{#if verifyMsg}<p class="pl-sub" role="status">{verifyMsg}</p>{/if}
		</div>
	{:else}
		<div class="pl-card panel">
			<div class="panel-heading">
				<h2>Pipeline</h2>
				<button type="button" class="pl-btn" disabled={refreshing} onclick={() => refresh([loadJobs, loadPapers])}>
					{refreshing ? 'Refreshing…' : 'Refresh'}
				</button>
			</div>
			<h3>Background jobs</h3>
			{#if jobs.running.length === 0 && jobs.finished.length === 0}
				<p class="pl-sub">No jobs yet.</p>
			{:else}
				<ul>
					{#each jobs.running as job (job.key)}
						<li class="pl-mono">{job.key} - running…</li>
					{/each}
					{#each jobs.finished as job}
						<li class="pl-mono">{job.key} - {job.status} ({job.info})</li>
					{/each}
				</ul>
			{/if}
			<h3>Run papers</h3>
			{#if papers.length === 0}
				<p class="pl-sub">Queue is empty - confirm pairs first.</p>
			{:else}
				<div class="checklist">
					{#each papers as p (p.id)}
						<label>
							<input type="checkbox" value={p.id} bind:group={selected} />
							<span class="paper-detail">
								#{p.id} - {paperName(p)} <span class="pl-mono">({p.status})</span>
								{#if p.error}<span class="paper-error pl-sub">{p.error}</span>{/if}
							</span>
						</label>
					{/each}
				</div>
				<div class="row">
					<label>Mode
						<select bind:value={mode}>
							<option value="sequential">One by one (sequential)</option>
							<option value="parallel">All in parallel</option>
						</select>
					</label>
					<label class="inline">
						<input type="checkbox" bind:checked={force} />
						Force rerun (wipes outputs first)
					</label>
					<button type="button" class="pl-btn pl-btn-primary" disabled={!selected.length || starting} onclick={run}>
						{starting ? 'Starting…' : 'Run'}
					</button>
					<button
						type="button"
						class="pl-btn"
						disabled={!selected.length || starting || deletingPapers}
						title="Remove queued papers (DB row, outputs and managed PDFs)"
						onclick={deleteSelectedPapers}
					>
						{deletingPapers ? 'Deleting…' : armDelPapers ? `Click again to delete ${selected.length}` : 'Delete selected'}
					</button>
				</div>
			{/if}
			{#if runMsg}<p class="pl-sub" role="status">{runMsg}</p>{/if}
		</div>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.panel {
		margin-top: 16px;
	}
	.panel h2 {
		font-size: 1.2rem;
		margin-bottom: 4px;
	}
	.panel h3 {
		font-size: 1rem;
		margin-top: 16px;
	}
	.panel-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.upload {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-weight: 600;
		font-size: 0.9rem;
		margin-top: 12px;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		margin-top: 12px;
	}
	.checklist {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-top: 8px;
	}
	.checklist label {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 6px 0;
	}
	.paper-detail {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.paper-error {
		display: block;
	}
	.pair {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
		align-items: center;
		padding: 8px 0;
		border-bottom: 1px solid var(--pl-line);
	}
	.inline {
		display: flex;
		align-items: center;
		gap: 8px;
		font-weight: 500;
	}
</style>
