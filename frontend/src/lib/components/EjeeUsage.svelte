<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import StatCard from '$lib/components/StatCard.svelte';
	let { currency = 'INR', rate = 95 } = $props();
	let ledger = $state(null), loading = $state(true), error = $state('');
	const number = value => Number(value || 0).toLocaleString('en-US');
	const money = usd => `${currency === 'INR' ? '₹' : '$'}${(usd * (currency === 'INR' ? rate : 1)).toFixed(4)}`;
	async function refresh() {
		loading = true; error = '';
		try { ledger = await api.getEjeeSelectionUsage(); }
		catch(e) { error = e.message; }
		finally { loading = false; }
	}
	onMount(refresh);
</script>

<section class="pl-card ejee-usage" aria-labelledby="ejee-usage-title">
	<div class="heading"><h2 id="ejee-usage-title">EJEE Selection Process</h2><button class="pl-btn" disabled={loading} onclick={refresh}>Refresh EJEE usage</button></div>
	<p class="pl-sub">Selected-question imports · separate EJEE database and usage. Includes conversion, diagram tool-loop calls and fresh PaperLab topic classification, including failed or unfinished runs.</p>
	{#if loading}<p role="status">Loading EJEE selection usage…</p>{/if}
	{#if error}<p class="pl-error" role="alert">{error}</p>{/if}
	{#if ledger}
		<div class="metrics">
			<StatCard label="EJEE selection cost" value={money(ledger.totals.cost_usd)} />
			<StatCard label="Conversion" value={money(ledger.totals.extraction_usd)} />
			<StatCard label="Fresh classification" value={money(ledger.totals.classification_usd)} />
			<StatCard label="API calls" value={number(ledger.totals.calls)} />
		</div>
		<p class="pl-sub">{ledger.collections} collections · {number(ledger.totals.input)} input tokens ({number(ledger.totals.cached)} cached) · {number(ledger.totals.output)} output · {number(ledger.totals.reasoning)} reasoning</p>
		<div class="pl-table-wrap"><table class="pl-table">
			<caption>Usage by selected collection</caption>
			<thead><tr><th>Collection</th><th>Status</th><th>Questions</th><th>Calls</th><th>Input</th><th>Cached</th><th>Output</th><th>Reasoning</th><th>Conversion</th><th>Classification</th><th>Total</th></tr></thead>
			<tbody>{#each ledger.rows as row (row.id)}<tr>
				<td>{#if row.paper_id}<a href={`/ejee/library/${row.paper_id}`}>{row.name}</a>{:else}{row.name}{/if}<small>{row.source}</small></td>
				<td>{row.status}</td><td class="num">{row.questions}</td><td class="num">{number(row.calls)}</td><td class="num">{number(row.input)}</td><td class="num">{number(row.cached)}</td><td class="num">{number(row.output)}</td><td class="num">{number(row.reasoning)}</td><td class="num">{money(row.extraction_usd)}</td><td class="num">{money(row.classification_usd)}</td><td class="num">{money(row.cost_usd)}</td>
			</tr>{/each}</tbody>
		</table></div>
		{#if !ledger.rows.length}<p>No EJEE selections processed yet.</p>{/if}
		<details><summary>Breakdown by EJEE phase</summary><div class="pl-table-wrap"><table class="pl-table">
			<thead><tr><th>Phase</th><th>Calls</th><th>Fresh input</th><th>Cached</th><th>Output</th><th>Cost</th></tr></thead>
			<tbody>{#each ledger.phases as row (row.phase)}<tr><td>{row.phase}</td><td class="num">{number(row.calls)}</td><td class="num">{number(row.input-row.cached)}</td><td class="num">{number(row.cached)}</td><td class="num">{number(row.output)}</td><td class="num">{money(row.cost_usd)}</td></tr>{/each}</tbody>
		</table></div></details>
		<p class="note">Costs use recorded tokens and configured API rates. Cached tokens are part of input; reasoning is part of output and is not charged twice. Completed jobs are counted from the EJEE library once. Local crop repairs without AI calls add zero API cost.</p>
		{#each ledger.warnings as warning}<p class="pl-error" role="alert">{warning}</p>{/each}
	{/if}
</section>

<style>
	.ejee-usage { padding:22px; margin:24px 0; min-width:0; }
	.heading { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; }
	h2 { font-size:1.25rem; margin:0; }
	.metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:20px 0; }
	.num { text-align:right; font-family:var(--pl-font-mono); white-space:nowrap; }
	small { display:block; font-size:.78rem; opacity:.7; margin-top:4px; }
	caption { text-align:left; padding:10px 0; font-weight:600; }
	details { margin-top:16px; }
	summary { cursor:pointer; font-weight:600; }
	.note { font-size:.82rem; opacity:.75; line-height:1.6; }
	@media(max-width:900px) { .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } }
	@media(max-width:500px) { .ejee-usage { padding:14px; } .heading .pl-btn { width:100%; justify-content:center; } }
</style>
