# Ground truth

`labels_template.json` holds 20 SKUs held out from `data/catalog.json` for
evaluation. It's built in two steps:

1. `scripts/build_eval_template.py` selects the 20 SKUs and writes
   `sku_id`, `raw_title`, `raw_description` verbatim from the catalog, with
   every attribute key set to `null`.
2. `eval/build_ground_truth.py` parses the raw dataset's seller-authored
   `product_specifications` column for those same 20 SKUs and **pre-fills
   suggested values** into `labels`, plus an `extractor_eval_description`
   (see "Split hygiene" below) and a `verified` flag defaulting to `false`.

This is a hybrid methodology, not full automation: the parser suggests, a
human still reviews, corrects, and fills in what the parser couldn't. **A
SKU counts as ground truth only once a human sets `"verified": true`** --
`eval/extraction_eval.py` refuses to score any SKU where that flag isn't
set. That's the actual integrity boundary this file enforces, not "no
computer touched it."

Why not fully automate scoring against the seller's spec column directly:
the 20 held-out SKUs were deliberately curated (`data/catalog_selection_notes.md`)
to include cases where that column is vague, absent, or contradicts the
title -- e.g. `Designed For: Mobile` on a listing whose title names a
specific phone. Scoring against the spec column as-is would silently make
those SKUs unscored or, worse, mark a correct extraction wrong. A human
verifying the pre-fill is what catches that; the pre-fill is just there so
that human isn't starting from a blank page.

## Workflow

1. `python scripts/build_eval_template.py` -- run once, or after a catalog/schema
   change (destructive: overwrites the file, see "Regenerating" below).
2. `python eval/build_ground_truth.py` -- pre-fills `labels` and
   `extractor_eval_description` for every SKU not yet `verified`. Safe to
   re-run: never overwrites a value a human already set, and skips any SKU
   already marked `verified`.
3. Open `labels_template.json`. For each SKU:
   - Check `suggested_fields` -- these were auto-filled from
     `product_specifications`; verify each one against `raw_title` /
     `raw_description` (not against the spec column itself -- that's
     circular).
   - Fill in every field not in `suggested_fields` by hand, from
     `raw_title` / `raw_description` only.
   - `null` is a legitimate answer (see Rules below), not a placeholder for
     "haven't gotten to this yet."
   - Set `"verified": true` once the row is done.

## Rules

- **Every value must be true against `raw_title`/`raw_description`, whether
  a human typed it or the parser suggested it.** A suggested value that
  doesn't hold up on inspection gets corrected, same as if you'd mislabeled
  it yourself.
- **Held out.** These 20 SKUs are never used to prompt-engineer, few-shot, or
  otherwise tune the extraction pipeline. If a SKU from this set is used as
  an example anywhere in `pipeline/`, the eval is compromised and the set
  must be replaced.
- **Never revised after seeing pipeline output.** Once a SKU is `verified`,
  its labels don't change because the pipeline disagreed with them. A
  disagreement is either a pipeline bug or a genuinely ambiguous SKU worth
  noting -- it is never a reason to edit the label to make the pipeline look
  better. If a label turns out to be a labelling mistake (not a
  disagreement), fix it before Tier 2 evaluation starts and record why in a
  commit message, not silently.
- **`null` is a real answer, not an unfinished one.** For the `unparseable`
  and some `missing_ambiguous` SKUs in this set, the correct label for a
  field genuinely may be `null` -- e.g. an accessory with no wattage stated
  anywhere in the raw text should be labelled `wattage_w: null`, not guessed.
  Tier 2's quarantine-correctness metric depends on these nulls being honest.
  A SKU with every field `null` is an *expected quarantine candidate* --
  `eval.extraction_eval.expected_quarantine_skus()` finds these
  automatically.

## Split hygiene: what the extractor actually sees

Many raw descriptions embed the seller's own spec table inline, starting at
`"Specifications of ..."`. `extractor_eval_description` is `raw_description`
hard-truncated at that marker -- what `pipeline/extract.py` will actually be
fed during evaluation, so it's never handed the answer key formatted as a
literal table. `tests/test_ground_truth_leakage.py` re-asserts this marker
never survives, against whatever is currently committed -- so a future
hand-edit that reintroduces it gets caught by CI, not discovered later as an
inflated score.

This is a narrower cut than "no ground-truth value appears anywhere in the
text." Sellers routinely restate the compatible phone model in the
description's own opening sentence (`"Key Features of X ... For Y"`), not
just in the structured spec table -- recovering that from prose is the
actual extraction task, not a leak. An earlier version of this pipeline
truncated on any such match and left most descriptions as short, useless
fragments (`"Instyles Back Cover for"` with the model cut off) -- that
defeated the eval instead of protecting it. `prose_restated_fields` on each
SKU records which fields are naturally restated in the (stripped)
description, purely informational.

`raw_description` itself is untouched and always the full original text --
that's what a human labels from. `extractor_eval_description` is the
narrower, stripped view used only when scoring the extractor.

## Label keys

The `labels` object's keys come from `pipeline.schema.ATTRIBUTE_FIELDS` (see
`pipeline/schema.py` for what each field means and its enum vocabulary,
where one applies):

- `accessory_type` -- one of `case`, `pouch`, `screen_protector`, `cable`, `charger`, `headphone`, `power_bank`, `other`
- `model_compat` -- list of phone model strings this accessory fits (use the phone name as written in the raw text; canonicalization happens in the pipeline, not here). An empty list is a valid, confident label for a genuinely universal accessory -- that's different from `null`.
- `connector_type` -- one of `usb_a`, `micro_usb`, `usb_c`, `lightning`, `3_5mm_jack`, `bluetooth`, `other`
- `wattage_w` -- charging wattage, as a number. Convert from stated V/A if both are given in the raw text.
- `capacity_mah` -- battery capacity in mAh (power banks only)
- `screen_size_in` -- screen size in inches this case/protector is cut for. Not present as a structured field anywhere in this dataset -- `eval/build_ground_truth.py` never suggests it; always hand-labelled or left `null`.
- `wireless_charging` -- `true` / `false`
- `material` -- one of `plastic`, `silicone_tpu`, `leather`, `metal`, `tempered_glass`, `fabric_nylon`, `other`

## Regenerating

`scripts/build_eval_template.py` **overwrites `labels_template.json` and
destroys any hand-written labels** -- do not re-run it once labeling starts.
If the SKU selection or schema needs to change, do that deliberately and
re-label, don't regenerate over existing work.

`eval/build_ground_truth.py` is safe to re-run at any point -- it only fills
fields that are still `null` and skips SKUs already `verified`.
