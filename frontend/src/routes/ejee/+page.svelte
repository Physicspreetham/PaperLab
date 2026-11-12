<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import EjeeSelection from '$lib/components/EjeeSelection.svelte';
	import { role, loginOpen } from '$lib/stores.js';
	const admin = $derived($role === 'archivist');
	let catalogue = $state(null);
	let sourceDb = $state('');
	let assetRoot = $state('');
	let bookId = $state('');
	let selected = $state([]);
	let jobs = $state([]);
	let error = $state('');
	let message = $state('');
	let loading = $state(false);
	let starting = $state(false);
	let sourceOpen = $state(false);
	let usage = $state(null);
	const book = $derived(catalogue?.books?.find(b => b.id === bookId));
	const phases = {queued:'Queued', preparing:'Reading mapped source images', converting:'Converting questions and solutions',
		diagrams:'Exporting diagram PNGs', formatting:'Checking display format', syllabus:'Loading current syllabus',
		classifying:'Running fresh topic classification', verifying:'Verifying collection', publishing:'Adding to EJEE library', done:'Complete'};

	async function refreshCatalogue() {
		const result = await api.getEjeeCatalogue();
		catalogue = result;
		sourceDb = result.settings.source_db;
		assetRoot = result.settings.asset_root;
		if (!result.books.some(b => b.id === bookId)) bookId = result.books[0]?.id || '';
		sourceOpen = !result.connected;
	}
	async function connect() {
		loading = true; error = ''; message = '';
		try {
			catalogue = await api.setEjeeSource({source_db:sourceDb, asset_root:assetRoot});
			bookId = catalogue.books[0]?.id || ''; selected = []; sourceOpen = false;
			message = 'EJEE source connected. Filter and select questions below.';
		} catch(e) { error = e.message; } finally { loading = false; }
	}
	async function refreshJobs() {
		const previous = jobs;
		jobs = await api.getEjeeJobs();
		usage = await api.getEjeeUsage();
		if (jobs.some(j => j.status === 'done' && !previous.some(p => p.id === j.id && p.status === 'done'))) await refreshCatalogue();
	}
	async function start() {
		starting = true; error = ''; message = '';
		try {
			await api.importEjeeChapters(bookId, selected);
			selected = []; message = 'Chapters queued. You can leave this page; imports continue in the background.';
			await refreshJobs();
		} catch(e) { error = e.message; } finally { starting = false; }
	}
	async function resume(id) {
		error = '';
		try { await api.resumeEjeeJob(id); await refreshJobs(); }
		catch(e) { error = e.message; }
	}
	function toggle(id, checked) {
		selected = checked ? [...new Set([...selected,id])] : selected.filter(v => v !== id);
	}
	$effect(() => {
		if (!admin) { catalogue = null; jobs = []; return; }
		let active = true, timer;
		(async () => {
			loading = true;
			try { await refreshCatalogue(); await refreshJobs(); if(active) error = ''; }
			catch(e) { if(active) error = e.message; }
			finally { if(active) loading = false; }
		})();
		timer = setInterval(() => {
			if (active) refreshJobs().catch(e => { if(active) error = e.message; });
		}, 3000);
		return () => { active = false; clearInterval(timer); };
	});
</script>

<svelte:head><title>EJEE Import - PaperLab</title></svelte:head>
<h1>EJEE question import</h1>
<p><a class="pl-btn" href="/ejee/library">Open EJEE collections →</a></p>
<p class="pl-sub">Filter your EJEE database and process only the questions you select. Named collections, mapped solutions and diagrams use a separate database and folder.</p>

{#if !admin}
	<div class="pl-card"><p>Log in as archivist to connect your EJEE database and import selected questions.</p>
		<button class="pl-btn pl-btn-primary" onclick={() => loginOpen.set(true)}>Archivist login</button></div>
{:else}
	{#if error}<div class="pl-error" role="alert">{error}</div>{/if}
	{#if message}<p class="notice" role="status">{message}</p>{/if}
	<section class="pl-card connection">
		<div class="row"><div><h2>EJEE source</h2><p>{catalogue?.connected ? 'Connected · database is read-only' : 'Connect a database and its image folder on this computer.'}</p></div>
			<button class="pl-btn" onclick={() => sourceOpen = !sourceOpen}>{sourceOpen ? 'Hide settings' : 'Source settings'}</button></div>
		{#if sourceOpen}
			<form onsubmit={e => {e.preventDefault(); connect();}}>
				<label>EJEE database file<input class="pl-input" bind:value={sourceDb} placeholder="C:/EJEE-data/ejee.db" required /></label>
				<label>EJEE image folder<input class="pl-input" bind:value={assetRoot} placeholder="C:/EJEE-data/uploads" required /></label>
				<button class="pl-btn pl-btn-primary" disabled={loading}>{loading ? 'Reading database…' : 'Connect source'}</button>
			</form>
		{/if}
	</section>
	{#if loading && !catalogue}<p role="status">Reading EJEE catalogue…</p>{/if}
	{#if catalogue?.connected}
		{#key catalogue.settings.source_db + '|' + catalogue.settings.asset_root}
			<EjeeSelection aiReady={catalogue.ai_ready} onQueued={refreshJobs} />
		{/key}
		<details class="pl-card"><summary>Optional: import complete mapped textbook chapters</summary>
		<section>
			<h2>Choose chapters</h2>
			<label>Textbook<select class="pl-input" bind:value={bookId} onchange={() => selected = []}>
				{#each catalogue.books as b}<option value={b.id}>{b.source}</option>{/each}
			</select></label>
			{#if !catalogue.books.length}<p>No supported textbook chapter mappings were found in this database.</p>{/if}
			{#if book}
				<p class="pl-sub">{book.chapters.length} chapters · Select up to 20. Existing chapter papers are kept as they are.</p>
				{#if book.excluded_question_parts}<p class="hint">{book.excluded_question_parts} source parts use a different numbering format and are excluded from this adapter.</p>{/if}
				<div class="chapters">
					{#each book.chapters as ch (ch.id)}
						<div class="chapter">
							<label class="chapter-label"><input type="checkbox" checked={selected.includes(ch.id)} disabled={!!ch.paper_id || starting} onchange={e => toggle(ch.id,e.currentTarget.checked)} />
								<span><strong>{ch.title}</strong><small>{ch.questions} questions · {ch.solution_groups} mapped solutions{ch.excluded_groups ? ` · ${ch.excluded_groups} groups need mapping review` : ''}</small></span></label>
							{#if ch.paper_id}<a href={`/ejee/library/${ch.paper_id}`}>Open paper →</a>{/if}
						</div>
					{/each}
				</div>
				<p class="hint">Uses the configured PaperLab AI service for text/diagram conversion and fresh topic classification. Usage is recorded in the ledger. Missing source solutions remain explicitly missing.</p>
				{#if !catalogue.ai_ready}<p class="pl-error">Configure the PaperLab Meta API key to enable imports.</p>{/if}
				<button class="pl-btn pl-btn-primary" disabled={!selected.length || selected.length > 20 || starting || !catalogue.ai_ready} onclick={start}>{starting ? 'Queuing…' : `Import ${selected.length || ''} selected chapter${selected.length === 1 ? '' : 's'}`}</button>
			{/if}
		</section>
		</details>
	{/if}
	<section class="pl-card">
		<h2>Import progress</h2>
		{#if usage}<p class="hint">EJEE imports only: ${usage.total_usd.toFixed(4)} estimated API cost · recorded separately from question-paper processing.</p>{/if}
		{#if !jobs.length}<p>No EJEE imports started from this app yet.</p>{/if}
		{#each jobs as job (job.id)}
			<article class="job">
				<div class="row"><div><strong>{job.chapter}</strong><small>{job.book}</small></div><span class="badge">{job.status}</span></div>
				<p>{phases[job.phase] || job.phase} · {job.converted || 0}/{job.total} converted · {job.classified || 0}/{job.total} classified</p>
				<p class="hint">Estimated API usage: ${(job.estimated_cost_usd || 0).toFixed(4)}</p>
				<progress max={job.total * 2 || 1} value={(job.converted || 0)+(job.classified || 0)} aria-label={`${job.chapter} progress`}></progress>
				{#if job.error}<p class="pl-error">{job.error}</p>{/if}
				{#if ['failed','interrupted'].includes(job.status)}<button class="pl-btn" onclick={() => resume(job.id)}>Resume import</button>{/if}
				{#if job.status === 'done' && job.paper_id}<a class="pl-btn" href={`/ejee/library/${job.paper_id}`}>Open imported collection →</a>{/if}
			</article>
		{/each}
	</section>
{/if}

<style>
	.pl-card { margin-top: 18px; padding: 22px; }
	h2 { margin: 0 0 12px; font-size: 1.25rem; }
	.row { display:flex; justify-content:space-between; align-items:center; gap:16px; }
	form { display:grid; gap:14px; margin-top:16px; }
	label { display:grid; gap:7px; }
	input:not([type=checkbox]), select { width:100%; padding:10px 12px; color:inherit; background:var(--pl-bg); border:1px solid var(--pl-line); border-radius:8px; }
	.chapters { max-height:420px; overflow:auto; margin:16px 0; border:1px solid var(--pl-line); border-radius:10px; }
	.chapter { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px; border-bottom:1px solid var(--pl-line); }
	.chapter:last-child { border-bottom:0; }
	.chapter-label { display:flex; align-items:center; gap:12px; flex:1; cursor:pointer; }
	small { display:block; margin-top:4px; opacity:.72; }
	.hint { font-size:.9rem; opacity:.8; line-height:1.6; }
	.notice { padding:12px; border:1px solid var(--pl-line); border-radius:8px; }
	.job { border-top:1px solid var(--pl-line); padding:18px 0; }
	progress { width:100%; margin-bottom:12px; accent-color:var(--pl-accent); }
	.badge { font-size:.85rem; padding:5px 9px; border:1px solid var(--pl-line); border-radius:20px; }
	.pl-error { margin:12px 0; }
	@media(max-width:650px) { .row,.chapter { align-items:flex-start; flex-direction:column; } .chapter-label { flex-direction:row; } }
</style>
