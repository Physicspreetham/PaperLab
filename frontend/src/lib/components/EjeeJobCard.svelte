<script>
	import { api } from '$lib/api.js';
	import FigurePanel from './FigurePanel.svelte';
	let { job, onChange = async () => {}, onError = () => {} } = $props();
	const phases = {queued:'Queued', preparing:'Reading mapped source images', converting:'Converting questions and solutions',
		diagrams:'Exporting diagram PNGs', formatting:'Checking display format', syllabus:'Loading current syllabus',
		classifying:'Running fresh topic classification', verifying:'Verifying collection', publishing:'Adding to EJEE library',
		preserving_tags:'Keeping original EJEE tags', needs_review:'Crop/content review required', failed:'Import stopped', done:'Complete'};
	const stopped = $derived(['failed', 'interrupted'].includes(job.status));
	// Original-tag imports never run classification, so it must not count towards progress.
	const reclassifies = $derived(job.tagging_mode === 'paperlab');
	const max = $derived((job.total || 0) * (reclassifies ? 2 : 1) || 1);
	const value = $derived((job.converted || 0) + (reclassifies ? job.classified || 0 : 0));
	let questions = $state(null), open = $state(false), busy = $state(false);
	const labels = {done:'Converted', review:'Needs crop review', failed:'Failed', pending:'Waiting'};

	async function loadQuestions() {
		try { questions = await api.getEjeeJobQuestions(job.id); } catch(e) { onError(e.message); }
	}
	function toggleTable(e) {
		open = e.currentTarget.open;
	}
	$effect(() => { if (open && (job.converted || 0) >= 0 && job.status) loadQuestions(); });
	async function run(action, confirmText) {
		if (confirmText && !window.confirm(confirmText)) return;
		busy = true;
		try { await action(); await onChange(); } catch(e) { onError(e.message); } finally { busy = false; }
	}
	const resume = () => run(() => api.resumeEjeeJob(job.id),
		job.phase === 'needs_review'
			? 'Resume will retry only the questions that still need attention. Saved conversions are reused. Continue?' : null);
	const cancel = () => run(() => api.cancelEjeeJob(job.id), 'Stop this import? Saved progress is kept and you can resume it later.');
	const remove = () => run(() => api.deleteEjeeJob(job.id), `Remove "${job.chapter}" and its saved progress? Questions converted so far will need to be converted again.`);
</script>

<article class="job">
	<div class="row"><div><strong>{job.chapter}</strong><small>{job.book}</small></div><span class="badge">{job.status}</span></div>
	<p>{phases[job.phase] || job.phase} · {job.converted || 0}/{job.total} converted{reclassifies ? ` · ${job.classified || 0}/${job.total} classified` : ''}</p>
	<p class="hint">Estimated API usage: ${(job.estimated_cost_usd || 0).toFixed(4)}</p>
	<progress {max} {value} aria-label={`${job.chapter} progress`}></progress>
	{#if job.error}<p class="pl-error">{job.error}</p>{/if}
	{#if job.auto_accepted_crops}
		<p class="notice">{job.auto_accepted_crops} diagram{job.auto_accepted_crops === 1 ? '' : 's'} could not be cropped perfectly and {job.auto_accepted_crops === 1 ? 'was' : 'were'} kept automatically. Please check {job.auto_accepted_crops === 1 ? 'it' : 'them'} in the collection.</p>
	{/if}
	<div class="buttons">
		{#if job.can_cancel}<button class="pl-btn" disabled={busy} onclick={cancel}>Stop import</button>{/if}
		{#if stopped}<button class="pl-btn" disabled={busy} onclick={resume}>Resume import</button>
			<button class="pl-btn" disabled={busy} onclick={remove}>Remove</button>{/if}
		{#if job.status === 'done' && job.paper_id && job.kind === 'selection'}
			<a class="pl-btn" href={`/ejee?append=${job.paper_id}`}>Add more questions</a>
		{/if}
		{#if job.status === 'done' && job.paper_id}<a class="pl-btn" href={`/ejee/library/${job.paper_id}`}>Open imported collection →</a>{/if}
	</div>
	{#if job.phase === 'needs_review' && stopped}
		<details>
			<summary>Review diagram crops</summary>
			<FigurePanel reviewJobId={job.id} />
		</details>
	{/if}
	{#if job.total > 0 && job.phase !== 'queued'}
		<details ontoggle={toggleTable}>
			<summary>Question-by-question status</summary>
			{#if !questions}<p class="hint">Loading…</p>
			{:else if !questions.length}<p class="hint">Questions are listed once the sources have been read.</p>
			{:else}
				<table>
					<thead><tr><th>#</th><th>Source</th><th>Status</th><th>Model calls</th></tr></thead>
					<tbody>
						{#each questions as q (q.number)}
							<tr class={q.status}>
								<td>{q.number}</td>
								<td>{q.label}{#if q.auto_accepted.length}<small>Check crop: {q.auto_accepted.join(', ')}</small>{/if}{#if q.error && q.status !== 'done'}<small>{q.error}</small>{/if}</td>
								<td>{labels[q.status]}</td>
								<td>{q.turns ?? '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</details>
	{/if}
</article>

<style>
	.job { border-top:1px solid var(--pl-line); padding:18px 0; }
	.row { display:flex; justify-content:space-between; align-items:center; gap:16px; }
	small { display:block; margin-top:4px; opacity:.72; }
	.hint { font-size:.9rem; opacity:.8; line-height:1.6; }
	progress { width:100%; margin-bottom:12px; accent-color:var(--pl-accent); }
	.badge { font-size:.85rem; padding:5px 9px; border:1px solid var(--pl-line); border-radius:20px; }
	.pl-error { margin:12px 0; }
	.notice { padding:10px 12px; border:1px solid var(--pl-line); border-radius:8px; font-size:.9rem; }
	.buttons { display:flex; flex-wrap:wrap; gap:10px; margin:10px 0; }
	details { margin-top:10px; }
	summary { cursor:pointer; font-weight:600; }
	table { width:100%; border-collapse:collapse; margin-top:10px; font-size:.9rem; }
	th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--pl-line); vertical-align:top; }
	tr.review td:nth-child(3), tr.failed td:nth-child(3) { color:var(--pl-seal, #b3261e); font-weight:600; }
	tr.pending { opacity:.6; }
</style>
