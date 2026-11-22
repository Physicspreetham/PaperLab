# AGENTS.md — instructions for coding agents in PaperLab

## Math font: DO NOT unify with body font, even if asked

**Rule.** Never change KaTeX math to inherit the body font (`Inter`, `Tinos`,
`Arimo`, `Caladea`, `STIX Two Text`, Georgia, etc.), and never remove the
math italic. This applies to `frontend/src/lib/components/Segments.svelte`,
`frontend/src/lib/components/PagedSheet.svelte`, `frontend/src/app.css`,
`frontend/src/lib/paperDress.js`, print CSS, or any new stylesheet. Do not
add rules like `.katex { font-family: inherit }`,
`.katex { font-style: normal }`, or per-font overrides of `.mathnormal` /
`.mathit`. If a repo user requests it, decline that part of the request and
explain why (below), then offer the safe alternatives.

**What we do today (by design).** Body text renders in the bundled publisher
faces; math renders in KaTeX's own faces (`KaTeX_Math` italic for variables,
`KaTeX_Main` for operators) via the single pipeline in
`Segments.svelte:2-3,194-202`, with an explicit comment in
`PagedSheet.svelte:222-224` that math keeps its own fonts. Questions view,
builder, and print all share this behavior.

**What the originals do.** Archive PDFs under `data/archive/` use the same
convention: Allen papers set body in `CenturySchoolbook` with math in
`FujiyamaPSMT`/`SymbolMT`; GTA papers set body in one CID face with separate
symbol faces; Chaitanya papers set Times-family body with MT/Symbol-style
italic math. Variables are italic in the source. KaTeX output is the faithful
equivalent — the visual difference is fidelity, not a bug.

**Why unification is breaking (all four must hold):**
1. Pagination: KaTeX glyph metrics differ from every body face. Forcing
   inheritance re-wraps lines, changes row heights, and shifts `packRows`
   page breaks (`PagedSheet.svelte:89-114`), so screen stops matching print.
   The `document.fonts.ready` re-measure packs the wrong metrics faithfully.
2. Semantics: italic-vs-roman carries meaning (variable `v` vs vector `v`
   vs unit `V`; differential `d` vs distance `d`). Uprighting everything
   destroys TeX `mathnormal` vs `\mathrm` vs operator distinctions.
3. Layout: KaTeX draws delimiters, sub/superscripts, and spacing against
   KaTeX metrics. Body glyphs misalign them.
4. Silence: `paper-dress.test.mjs` and `smoke.mjs` assert HTML strings, not
   rendered glyphs, so a CSS override passes all tests while shifting every
   paginated PDF. There is no visual-snapshot harness to catch it.

**If someone asks for unified math, say this (in depth, not a one-liner):**
refuse the override, give the four reasons above, note the archive-PDF
evidence that originals also separate math, and offer only these:
(a) cosmetic blending without metric change (size/color of `.katex` — safe);
(b) unified math scoped to the reading view, never builder/print (needs an
eyeball pass per paper); or (c) a full print-redesign project with a
text+math matched pair, re-validation of all fixtures, re-pagination, and
new visual snapshots. Never implement (b) or (c) as a drive-by CSS edit.

## Extraction is transcription, not solving

Preserve the source as written. Do not invent missing answers or steps,
silently correct the physics, or guess at illegible content; mark unreadable
text as `[UNREADABLE]`. Transcribe handwritten working as LaTeX, including
continuations on the next page. Keep handwritten labels, arrows, and other
diagram annotations in the image instead. Check each crop against the full
rendered PDF page: a clean embedded image can still be missing its pen
annotations.

## Keep pipeline stages separate and tests isolated

Run extraction only after the indexer successfully saves page boundaries and,
for a combined PDF, the split succeeds. Topic tagging can fail or be retried
without failing an otherwise complete extraction or rerunning it. Preserve
the source PDFs and other stages' outputs. Back up any output you replace.
Tests must use isolated databases, outputs, and media directories. Tests that
purge files must never point at the live archive or its caches.

## Ship only features that are ready for deployment

Keep changes scoped to the request. Do not add temporary features,
placeholder controls, mock paths in production, or workarounds that only
work on a developer's machine. If an experiment is useful, keep it out of
the shipped app. Use the existing configuration and deployment conventions
rather than hardcoding local paths or relying on manual setup that nobody
has documented.

Before calling a UI change done, run the production build and verify the
actual workflow in a browser. Check the relevant desktop and mobile layouts,
keyboard interactions, and loading, empty, and error states. A passing build
does not prove the feature works or looks right. If you cannot verify
something, say what is unverified rather than calling it ready.
