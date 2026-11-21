<script>
	import { tick } from 'svelte';
	import { carts } from '$lib/carts.js';
	import { modelPaperList, modelPapers } from '$lib/modelPapers.js';
	import {
		isParagraphType, LEGACY_PARAGRAPH_TYPE, MAX_MODEL_QUESTIONS, MODEL_PAPER_TYPES, modelQuantity, modelTypeLabel
	} from '$lib/modelPaperModel.js';

	const typeGroups = [
		{ label: 'Standalone questions', types: MODEL_PAPER_TYPES.filter((type) => !isParagraphType(type)) },
		{ label: 'Paragraph groups', types: MODEL_PAPER_TYPES.filter(isParagraphType) }
	];

	let editing = $state(false);
	let editingId = $state(null);
	let name = $state('');
	let counts = $state({});
	let nameInput = $state(null);
	let typePicker = $state(null);
	let legacyParagraphCount = $state(0);
	let error = $state('');
	let notice = $state('');
	let confirmingId = $state(null);
	const selectedTypes = $derived(MODEL_PAPER_TYPES.filter((type) => type in counts));
	const total = $derived(selectedTypes.reduce((sum, type) => sum + (counts[type] ?? 0), 0));

	async function openEditor(paper = null) {
		editing = true;
		editingId = paper?.id ?? null;
		name = paper?.name ?? '';
		counts = { ...paper?.counts };
		legacyParagraphCount = counts[LEGACY_PARAGRAPH_TYPE] ?? 0;
		delete counts[LEGACY_PARAGRAPH_TYPE];
		error = '';
		notice = '';
		confirmingId = null;
		await tick();
		nameInput?.focus();
	}

	async function addType(event) {
		const picker = event.currentTarget;
		const type = picker.value;
		picker.value = '';
		if (!MODEL_PAPER_TYPES.includes(type) || type in counts) return;
		counts[type] = 1;
		error = '';
		await tick();
		const input = document.getElementById(`target-${type}`);
		input?.focus();
		input?.select();
	}

	async function removeType(type) {
		delete counts[type];
		error = '';
		await tick();
		typePicker?.focus();
	}

	function save(event) {
		event.preventDefault();
		if (legacyParagraphCount && !selectedTypes.some(isParagraphType)) {
			error = 'Add a specific paragraph type or remove the old paragraph target before saving.';
			return;
		}
		const result = modelPapers.save(editingId, name, counts);
		if (result.error) {
			error = result.error;
			return;
		}
		notice = `${result.paper.name} saved.`;
		editing = false;
	}

	function remove(paper) {
		modelPapers.remove(paper.id);
		carts.unlinkModelPaper(paper.id);
		if (editing && editingId === paper.id) editing = false;
		confirmingId = null;
		notice = `${paper.name} deleted.`;
	}
</script>

<svelte:head><title>Model Papers - PaperLab</title></svelte:head>

<a class="back" href="/cart">
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
		<path d="M19 12H5m6-6-6 6 6 6" />
	</svg>
	Back to cart
</a>

<header class="heading">
	<div>
		<h1>Model papers</h1>
		<p class="pl-sub">Save a question mix, then select it in a cart to see what to add or remove.</p>
	</div>
	{#if !editing}
		<button type="button" class="pl-btn pl-btn-primary" onclick={() => openEditor()}>New model paper</button>
	{/if}
</header>

<div class="notice" role="status">{notice}</div>

{#if editing}
	<form class="pl-card editor" onsubmit={save}>
		<h2>{editingId ? 'Edit model paper' : 'New model paper'}</h2>
		<label class="name-field">
			<span>Name</span>
			<input type="text" required maxlength="80" bind:this={nameInput} bind:value={name} />
		</label>
		<fieldset>
			<legend>Question mix</legend>
			{#if legacyParagraphCount}
				<div class="legacy">
					<p>This model has an older target of {modelQuantity(LEGACY_PARAGRAPH_TYPE, legacyParagraphCount)}. Replace it with one or more specific paragraph types.</p>
					<button type="button" class="pl-btn" onclick={() => { legacyParagraphCount = 0; error = ''; }}>Remove old target</button>
				</div>
			{/if}
			{#each selectedTypes as type (type)}
				<div class="count">
					<label for={`target-${type}`}>{modelTypeLabel(type)}</label>
					<input id={`target-${type}`} type="number" min="1" max={MAX_MODEL_QUESTIONS} step="1" required bind:value={counts[type]} />
					<button type="button" class="remove-type" aria-label={`Remove ${modelTypeLabel(type)}`} onclick={() => removeType(type)}>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
							<path d="m6 6 12 12M18 6 6 18" />
						</svg>
					</button>
				</div>
			{/each}
			{#if selectedTypes.length < MODEL_PAPER_TYPES.length}
				<select class="type-picker" aria-label="Add question type" bind:this={typePicker} onchange={addType}>
					<option value="" selected>Add question type…</option>
					{#each typeGroups as group (group.label)}
						{@const available = group.types.filter((type) => !(type in counts))}
						{#if available.length}
							<optgroup label={group.label}>
								{#each available as type (type)}
									<option value={type}>{modelTypeLabel(type)}</option>
								{/each}
							</optgroup>
						{/if}
					{/each}
				</select>
			{/if}
		</fieldset>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
		<footer class="form-actions">
			<span class="pl-sub total">{total} {total === 1 ? 'item' : 'items'} total</span>
			<button type="button" class="pl-btn" onclick={() => (editing = false)}>Cancel</button>
			<button type="submit" class="pl-btn pl-btn-primary">Save model paper</button>
		</footer>
	</form>
{/if}

{#if $modelPaperList.length}
	<section class="pl-card saved" aria-label="Saved model papers">
		{#each $modelPaperList as paper (paper.id)}
			<article>
				<div class="summary">
					<h2>{paper.name}</h2>
					<p class="pl-sub">
						{Object.entries(paper.counts).map(([type, count]) => modelQuantity(type, count)).join(' · ')}
					</p>
				</div>
				<div class="row-actions">
					{#if confirmingId === paper.id}
						<button type="button" class="pl-btn" onclick={() => (confirmingId = null)}>Keep</button>
						<button type="button" class="pl-btn danger" onclick={() => remove(paper)}>Confirm delete</button>
					{:else}
						<button type="button" class="pl-btn" aria-label={`Edit ${paper.name}`} onclick={() => openEditor(paper)}>Edit</button>
						<button type="button" class="pl-btn" aria-label={`Delete ${paper.name}`} onclick={() => (confirmingId = paper.id)}>Delete</button>
					{/if}
				</div>
			</article>
		{/each}
	</section>
{:else if !editing}
	<div class="pl-card empty">
		<h2>No model papers yet</h2>
		<p class="pl-sub">Create one to compare your cart against a target mix.</p>
	</div>
{/if}

<style>
	.back {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
		text-decoration: none;
		margin-bottom: 16px;
	}
	.back:hover { text-decoration: underline; }
	.back svg { width: 16px; height: 16px; }
	.heading {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 12px 24px;
		margin-bottom: 16px;
	}
	h1 { font-size: 2rem; margin: 0 0 4px; }
	h2 { font-size: 1.2rem; margin: 0 0 4px; }
	p { margin: 0; }
	.notice:not(:empty) { margin-bottom: 12px; color: var(--pl-pine); }
	.editor { max-width: 700px; margin-bottom: 16px; }
	.editor h2 { margin-bottom: 16px; }
	.name-field { display: grid; gap: 6px; }
	.name-field span, legend { font-weight: 600; }
	fieldset { border: 0; padding: 0; margin: 16px 0; min-width: 0; }
	legend { padding: 0; }
	.count {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 4.5rem 32px;
		align-items: center;
		gap: 10px;
		border-bottom: 1px solid var(--pl-line);
		padding: 3px 0;
		font-size: 0.85rem;
	}
	.count input {
		width: 100%;
		min-width: 0;
		min-height: 32px;
		padding: 3px 8px;
		font-variant-numeric: tabular-nums;
	}
	.remove-type {
		display: grid;
		place-items: center;
		width: 100%;
		min-height: 32px;
		padding: 0;
		border: 0;
		border-radius: var(--pl-radius-sm);
		background: transparent;
		color: var(--pl-ink-soft);
	}
	.remove-type:hover { background: var(--pl-raised); color: var(--pl-seal-deep); }
	.remove-type svg { width: 16px; height: 16px; }
	.type-picker { margin-top: 10px; width: min(100%, 20rem); }
	.legacy {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px 16px;
		padding-block: 10px;
		border-bottom: 1px solid var(--pl-line);
		font-size: 0.85rem;
		color: var(--pl-ink-soft);
	}
	.legacy p { flex: 1 1 15rem; }
	.form-actions, .row-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
	.total { margin-right: auto; font-variant-numeric: tabular-nums; }
	.saved { padding-block: 0; }
	.saved article {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 8px 16px;
		padding-block: 14px;
	}
	.saved article + article { border-top: 1px solid var(--pl-line); }
	.summary { flex: 1 1 15rem; min-width: 0; overflow-wrap: anywhere; }
	.error { color: var(--pl-seal-deep); margin-bottom: 12px; }
	.danger { color: var(--pl-seal-deep); }
	@media (any-pointer: coarse) {
		.count {
			grid-template-columns: minmax(0, 1fr) 4.5rem 44px;
			padding-block: 1px;
		}
		.count input, .remove-type { min-height: 44px; }
	}
	@media (max-width: 420px) {
		.count { gap: 6px; }
		.total { flex-basis: 100%; }
		.form-actions .pl-btn { padding-inline: 12px; }
	}
</style>
