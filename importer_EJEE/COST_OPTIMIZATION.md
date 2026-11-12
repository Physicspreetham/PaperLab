# EJEE import cost optimization

The recorded six-question EJEE collection cost $0.026426618, approximately
$0.004404 per question. The ordinary question-paper ledger had $0.568657354 across
239 stored questions, approximately $0.002379 per stored question. The sets and
cache conditions differ, so these averages are diagnostic, not a controlled
comparison. Failed/unfinished paper calls can also contribute to that ledger.

The EJEE traces exposed avoidable round trips: question and solution were saved
in separate model turns, page images already supplied were requested again, and
diagram retries repeatedly resent previous previews. Some hard figures required
seven or eight crop calls. Full source images and both original and replacement
crop previews accumulated in the conversation.

## Changes

- The default `mapped-pair-v1` profile exposes the original `assisted_crop` and
  `exact_crop` tools plus `submit_pair`. The pair tool invokes the same native
  question validator/save first and solution validator/save second. A failure
  is returned for correction and never treated as completion. Question headings
  and rendering normalization still run on both fields before native saving.
- The full upstream extraction prompt and mapped quality rules remain. A final
  execution override explains the paired tool and that all pages are already
  supplied; repeated page-fetch calls are removed from this tool set. Original
  source resolution and final PNG pixels are preserved.
- Each crop sends one final raster preview at the native crop-preview size.
  Older previews of the same filename lose only their image block; correction
  text, tool-call history, the latest preview and all original source images stay.
- Five visually reviewed diagram rectangles are reusable only when the exact
  source image SHA-256 matches. The fifth was the previously repaired and
  inspected soap-bubble solution figure. No source labels or coordinates are
  inferred from a different image or copied without a hash match.
- A question stops for review after at most 12 model calls by default, instead
  of allowing a 36-turn retry spiral. Invalid/clipped/incomplete output is not
  published. `cost_max_turns_per_question` can adjust that ceiling in run config;
  `extractor_mode: legacy-pdf` retains the earlier tools for controlled diagnosis.
- Fresh classification continues through the actual current PaperLab Node 3.
  Neither the model/provider nor source image fidelity was reduced. Existing
  billed usage remains in the ledger unchanged.

## Controlled source comparison

Three actual source questions from the same collection were used: a text-only
question, a reviewed plate diagram, and the reviewed soap-bubble solution figure.
Their source resource IDs were 45130, 44329 and 42763. The old cost was reconstructed
from the original run's ordered token rows using its per-question extraction turn
counts (2, 11, 5) and the corresponding three fresh classification calls.

| Same three questions | Previous run | Optimized run |
|---|---:|---:|
| Extraction calls | 18 | 3 |
| Fresh Node 3 calls | 3 | 3 |
| Total calls | 21 | 6 |
| Estimated recorded API cost | $0.01310936 | $0.00443198 |
| Estimated cost/question | $0.00436979 | $0.00147733 |

This is a **66.2% cost reduction** and **71.4% fewer calls** in this run, including
fresh classification. Reviewed-coordinate reuse and different prompt-cache warmth
contribute; this is not a guarantee for new complex diagrams. All three questions,
both figure exports, native validators and fresh classification passed verification.
The benchmark stayed isolated in `runs/cost-final-benchmark/`; it was not published
as a duplicate collection or merged into the ordinary Archive.

Exploratory coordinate-cropping trials were also isolated and retained with their
paid usage/traces. They recorded $0.01191500 and $0.00384099 before being stopped;
they showed that direct coordinate guessing could still increase crop retries,
so the shipped profile retains the native crop tools. Including the final run,
optimization experiments recorded **$0.02018797**. These are recorded token costs,
not a provider invoice or a claim about unfinished requests. Experimental costs
are separate from the live imported-collection ledger, which remains unchanged.

Validation: 40 focused tests passed, including paired save ordering/failures,
scoped identities, original crop-tool retention and selective preview pruning.
