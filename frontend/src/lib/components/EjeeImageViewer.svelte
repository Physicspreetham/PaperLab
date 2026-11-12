<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { createWheelPager } from '$lib/ejeeGallery.js';
	import EjeeImportCartButton from './EjeeImportCartButton.svelte';
	let { row, index, total, sourceToken, selected, disabled, navigating = false, onToggle, onClose, onMove } = $props();
	let dialog = $state(null), details = $state(null), detailError = $state('');
	let zoomed = $state(false), showDetails = $state(true), imageLoading = $state(true), imageError = $state(false);
	const imageUrl = $derived(`/api/ejee/questions/${row.id}/preview?size=full&source_token=${encodeURIComponent(sourceToken)}`);
	const info = $derived(details || row);
	$effect(() => {
		const id=row.id,token=sourceToken;let active=true;
		details=null;detailError='';zoomed=false;imageLoading=true;imageError=false;
		api.getEjeeQuestionDetails(id,token).then(data=>{if(active) details=data;}).catch(e=>{if(active)detailError=e.message;});
		return ()=>{active=false;};
	});
	onMount(()=>{showDetails=window.matchMedia('(min-width:900px)').matches;dialog.showModal();return ()=>dialog?.close();});
	function keydown(event) {
		if (['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName)) return;
		if (event.key==='ArrowRight' || event.key==='ArrowLeft') { event.preventDefault(); if(!navigating) onMove(event.key==='ArrowRight' ? 1 : -1); }
	}
	function wheelSlides(node) {
		const slide=createWheelPager();
		const handler=event=>{
			if(zoomed || event.ctrlKey || event.metaKey) return;
			event.preventDefault();
			const step=slide(event,performance.now());if(step && !navigating) onMove(step);
		};
		node.addEventListener('wheel',handler,{passive:false});
		return {destroy(){node.removeEventListener('wheel',handler);}};
	}
</script>

<dialog bind:this={dialog} aria-labelledby="ejee-viewer-title" onkeydown={keydown}
	oncancel={event=>{event.preventDefault();onClose();}} onclick={event=>{if(event.target===dialog)onClose();}}>
	<div class="viewer">
		<header><div class="title"><h2 id="ejee-viewer-title">{row.title}</h2><span>{index+1} / {total.toLocaleString()} · {row.source || 'Unspecified source'}</span></div>
			<button class="button close" type="button" aria-label="Close question viewer" onclick={onClose}>✕</button></header>
		<div class="toolbar">
			<label class="choose"><input type="checkbox" checked={selected} {disabled} onchange={event=>onToggle(event.currentTarget.checked)} /> Select for import</label>
			<EjeeImportCartButton {selected} {disabled} title={row.title} onToggle={()=>onToggle(!selected)} />
			<button class="button" type="button" aria-pressed={zoomed} onclick={()=>zoomed=!zoomed}>{zoomed ? 'Fit image' : 'Original size'}</button>
			<button class="button" type="button" aria-expanded={showDetails} onclick={()=>showDetails=!showDetails}>{showDetails ? 'Hide details' : 'Show details'}</button>
			<nav aria-label="Slide questions"><button class="button" type="button" disabled={index===0 || navigating} onclick={()=>onMove(-1)}>← Previous</button><span aria-live="polite">{index+1} / {total}</span><button class="button" type="button" disabled={index+1>=total || navigating} onclick={()=>onMove(1)}>Next →</button></nav>
		</div>
		<div class="viewer-body" class:show-details={showDetails}>
			<div class="image-area" class:zoomed use:wheelSlides aria-busy={imageLoading || navigating}>
				{#if imageLoading || navigating}<p class="image-status" role="status">Loading question image…</p>{/if}
				{#if imageError}<p role="alert">Could not load this source image. Close the viewer and refresh the results.</p>{/if}
				{#key row.id}<img src={imageUrl} alt={`Full source question: ${row.title}`} onload={()=>imageLoading=false} onerror={()=>{imageLoading=false;imageError=true;}} />{/key}
			</div>
			{#if showDetails}<aside aria-label="Question details">
				<h3>Question details</h3>
				<dl>{#each [['Source',info.source],['Syllabus',info.path],['Model',info.qtype],['Level',info.difficulty],['Section',info.type],['Exam',info.exam],['Year',info.year],['Shift',info.shift],['Status',info.status || 'Not attempted'],['Favourite',info.fav ? 'Yes' : 'No'],['Altered',info.altered ? 'Yes' : 'No'],['Review',info.review],['Mapped solutions',info.solution_parts],['Tags',info.tags],['Source ID',info.id],['Group',info.grp],['UID',info.uid],['Created',info.created_at]] as [label,value]}
					{#if value !== null && value !== undefined && value !== ''}<div><dt>{label}</dt><dd>{value}</dd></div>{/if}
				{/each}</dl>
				{#if info.question_parts?.length>1}<p>{info.question_parts.length} question continuation cards; selecting one keeps its linked parts.</p>{/if}
				{#if info.question}<details><summary>Question transcription</summary><p>{info.question}</p></details>{/if}
				{#if info.answer}<details><summary>Source answer</summary><p>{info.answer}</p></details>{/if}
				{#if info.solution}<details><summary>Source solution text</summary><p>{info.solution}</p></details>{/if}
				{#if detailError}<p role="alert">{detailError}</p>{/if}
				<p class="hint">The cart icon adds to this import selection. Processing starts only when you name the collection and click Process selected questions.</p>
			</aside>{/if}
		</div>
		<footer>{zoomed ? 'Original pixels · scroll to read the image · use Previous/Next or arrow keys to slide.' : 'Scroll over the image to slide questions · ← → keys · Esc to close.'}</footer>
	</div>
</dialog>

<style>
	dialog { width:calc(100vw - 28px); max-width:1800px; height:calc(100dvh - 28px); max-height:none; padding:0; border:1px solid var(--pl-line); border-radius:14px; background:var(--pl-surface); color:var(--pl-ink); overflow:hidden; box-shadow:0 24px 100px #0006; }
	dialog::backdrop { background:#000b; backdrop-filter:blur(3px); }
	.viewer { display:grid; grid-template-rows:auto auto minmax(0,1fr) auto; height:100%; }
	header { display:flex; align-items:center; gap:14px; padding:12px 18px; border-bottom:1px solid var(--pl-line); }
	.title { flex:1; min-width:0; }.title h2 { margin:0; font-size:1.1rem; }.title span { display:block; margin-top:4px; font-size:.8rem; opacity:.75; overflow-wrap:anywhere; }
	.toolbar { display:flex; align-items:center; flex-wrap:wrap; gap:10px; padding:10px 18px; border-bottom:1px solid var(--pl-line); }
	.button { min-height:40px; padding:8px 12px; border:1px solid var(--pl-line); border-radius:8px; background:var(--pl-surface); color:inherit; font:inherit; font-size:.85rem; cursor:pointer; }.button:disabled { opacity:.4; cursor:default; }
	.close { font-size:1.1rem; }.choose { display:flex; align-items:center; gap:8px; font-size:.9rem; font-weight:600; }
	input[type=checkbox] { width:17px; height:17px; min-height:17px; padding:0; margin:0; }
	nav { display:flex; align-items:center; gap:10px; margin-left:auto; } nav span { font-size:.8rem; white-space:nowrap; }
	.viewer-body { display:grid; grid-template-columns:minmax(0,1fr); min-height:0; }.viewer-body.show-details { grid-template-columns:minmax(0,1fr) 300px; }
	.image-area { display:flex; justify-content:center; align-items:center; position:relative; min-width:0; min-height:0; padding:16px; background:#e9e9e9; overflow:hidden; overscroll-behavior:contain; }
	.image-area img { display:block; width:auto; height:auto; max-width:100%; max-height:100%; object-fit:contain; background:white; box-shadow:0 2px 12px #0002; }
	.image-area.zoomed { display:block; overflow:auto; }.image-area.zoomed img { max-width:none; max-height:none; }
	.image-status { position:absolute; top:8px; left:16px; padding:6px 10px; background:var(--pl-surface); border-radius:6px; z-index:1; }
	aside { padding:18px; overflow:auto; border-left:1px solid var(--pl-line); font-size:.85rem; }h3 { margin:0 0 14px; }dl { margin:0; }dl div { padding:8px 0; border-bottom:1px solid var(--pl-line); }dt { opacity:.65; font-size:.75rem; }dd { margin:4px 0 0; overflow-wrap:anywhere; line-height:1.5; }details { margin-top:14px; }summary { cursor:pointer; font-weight:600; }details p { white-space:pre-wrap; overflow-wrap:anywhere; }.hint { opacity:.65; line-height:1.5; }
	footer { padding:8px 18px; font-size:.75rem; opacity:.7; border-top:1px solid var(--pl-line); }
	@media(max-width:760px) { dialog { width:100vw; height:100dvh; max-width:none; margin:0; border-radius:0; border:0; }header,.toolbar { padding:10px; }.viewer-body.show-details { grid-template-columns:1fr; grid-template-rows:minmax(0,1fr) minmax(0,180px); }aside { padding:12px; border-left:0; border-top:1px solid var(--pl-line); }.image-area { padding:8px; }nav { width:100%; justify-content:space-between; margin:0; }.toolbar { gap:8px; }footer { padding:8px 10px; } }
</style>
