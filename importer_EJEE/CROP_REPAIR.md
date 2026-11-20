# Raster figure cropping repair

The selected `surfacetention` collection exposed three defects: a plate diagram
included a nearby statement fragment, another included descenders from the
preceding text line, and a bubble figure retained a wide empty right margin.
Some strokes and dimension labels had almost no clearance from the image edge.

The importer now uses the same lossless raster exporter for the model's updated
preview and the final PNG. It trims only blank margins and adds white display
clearance. It retains disconnected labels, numbers, colour fills and arrowheads;
it never selects only the largest connected component or redraws the diagram.
Ink touching the requested source rectangle is recorded separately from the new
white output margin. Extraction asks the model to correct that crop before
completion, and final export refuses unresolved edge contact. A padded canvas
cannot make a clipped source rectangle pass this check.

The mapped extractor prompt explicitly requires comparison with the full source
for foreign text and missing labels. Edge detection cannot determine semantic
ownership of an isolated text fragment, so it is not presented as a guarantee
that every future AI crop will be correct.

`reviewed_figure_crops.json` contains four visually reviewed rectangles bound to
the exact source-body SHA-256, source group and figure filename. They are reused
only for identical source pixels. Explicit run-specific reviews take precedence.
This includes the three question figures and the upper-plate force diagram.
The fifth existing solution figure was losslessly trimmed and padded.

All five PNGs in the live separate EJEE collection were repaired; worker and
published provenance were updated, and original worker/published files remain
under the run's `before-crop-repair/` backup. The live archive contains a
`crop-repair.json` audit record. The source EJEE database, original images,
question/solution text, fresh classifications and usage records were unchanged.
No additional AI calls were needed for this repair.

Validation: 33 focused tests passed, including exact content-pixel preservation,
detached labels, colour, blank-margin removal, edge-contact detection and invalid
bounds. The six-question worker collection passed its native verification again.

## Why Resume kept failing on the same questions (second repair)

Analysis of a failed 144-question run (13 questions in review) found that most
"edge touching" verdicts were false, produced by the ink detector rather than the
model's boxes:

1. Every EJEE question page has a faint full-height 2px vertical divider between
   the question and the options. Only horizontal rules were ignored, so any box
   crossing the page centre reported ink on top *and* bottom, whatever the model did.
2. Black-board solution pages (video frames) were scanned as "dark = ink" on a
   white-page assumption, so the whole canvas was ink and all four edges always touched.

`content_ink` now drops thin page-spanning vertical rules and detects dark pages
(background read from the page border; ink = clearly different from it). Clearance
padding uses the page background colour. For diagrams that truly abut prose, after 3
failed attempts the best attempt is auto-accepted (`auto_crop_reviews.json`, flagged
`auto_accepted`, still reviewable) instead of parking the whole import.
The crop review signature was bumped (v8) so earlier needs-review questions retry on Resume.
