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
   re-run, including after changing the suggester rules themselves: a field
   only counts as human-owned (never touched) if it's non-null AND wasn't
   this script's own suggestion last run -- so improving a rule (like the
   A1-A4 fixes below) actually refreshes stale prior output instead of
   freezing it in place. Once a SKU is `verified`, nothing about it is
   touched, ever, by anything.
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

## Suggester rules (eval/build_ground_truth.py)

Tightened after finding real mistakes by actually running the suggester's
output against `pipeline/extract.py`'s real behavior on real data:

- **`wireless_charging` is `true` only on an explicit signal** -- a
  dedicated spec key, or `"wireless"`/`"qi"` literally in a spec value.
  Never inferred `false` from absence. An earlier version returned a
  confident `false` whenever nothing mentioned wireless charging -- that's
  backwards: absence of a mention is *unknown*, not a negative, and this
  field is where the whole "fail closed, never guess" story lives. A real
  extraction run showed the extractor correctly returning `null` here while
  ground truth confidently said `false`, penalizing the *correct* answer.
  The suggester was the bug, not the extractor.
- **`model_compat` rejects device-category words** (`mobile`, `tablet`,
  `smartphone`, `universal`, `all`, and close variants) -- these are
  categories, not models, and useless for a compatibility graph that has to
  verify "this specific accessory fits that specific phone." Rejected
  values are recorded per SKU in `rejected_category_values`, not silently
  dropped.
- **`DESIGNED_FOR_KEYS` is checked in order, falling through past a key
  that yields only category words.** A generic key (`Compatible Devices:
  Mobile`) no longer masks a more specific one (`Suitable For: One Plus
  Two`) present on the same SKU.
- **`scorable: false`** when the SKU has no seller-authored structured
  anchor anywhere in `product_specifications` -- those SKUs get `labels`
  cleared entirely rather than left with a stray title-fallback guess (e.g.
  `accessory_type` guessed from the word "cable" in the title). Still a
  legitimate row to hand-label as a quarantine test case; just excluded
  from `eval/extraction_eval.py`'s precision/recall scoring even if a human
  verifies it anyway, since there's no seller data to hybrid-verify
  against.

## Scoring only fields with real support

Precision/recall on a handful of SKUs is noise, not signal.
`eval/extraction_eval.py` only reports fields with
`support >= MIN_SUPPORT_FOR_SCORING` (currently 5) across the scorable,
verified set; everything else is computed but excluded from the printed
report. As of the last suggestion run (18 scorable SKUs, pre-verification --
these numbers will shift once a human reviews and fills in what the
suggester couldn't):

| field | coverage | reportable? |
|---|---|---|
| `accessory_type` | 18/18 | yes |
| `model_compat` | 11/18 | yes |
| `connector_type` | 7/18 | yes |
| `wireless_charging` | 1/18 | no |
| `material` | 4/18 | no |
| `capacity_mah` | 2/18 | no |
| `wattage_w` | 0/18 | no |
| `screen_size_in` | 0/18 | no |

`wattage_w` and `screen_size_in` are at zero exactly as expected -- neither
is ever stated as a structured field anywhere in this dataset (see
`data/catalog_selection_notes.md`). `wireless_charging` and `material`
being this low is itself a real, reportable finding about the catalog, not
a suggester gap: most sellers simply don't disclose these as structured
data. Hand-labeling from raw text (step 3 in Workflow) can raise these
numbers where a human can confidently determine a value the structured
suggester couldn't see -- these are pre-verification suggester counts, not
a ceiling.

## Label keys

The `labels` object's keys come from `pipeline.schema.ATTRIBUTE_FIELDS` (see
`pipeline/schema.py` for what each field means and its enum vocabulary,
where one applies). Two more keys live alongside `labels` on each SKU:
`scorable` (bool, see above) and `rejected_category_values` (list of raw
strings the suggester dropped from `model_compat` for being a device
category, not a model).

- `accessory_type` -- one of `case`, `pouch`, `screen_protector`, `cable`, `charger`, `headphone`, `power_bank`, `other`
- `model_compat` -- list of phone model strings this accessory fits (use the phone name as written in the raw text; canonicalization happens in the pipeline, not here). An empty list is a valid, confident label for a genuinely universal accessory -- that's different from `null`.
- `connector_type` -- one of `usb_a`, `micro_usb`, `usb_c`, `lightning`, `3_5mm_jack`, `bluetooth`, `other`
- `wattage_w` -- charging wattage, as a number. Convert from stated V/A if both are given in the raw text.
- `capacity_mah` -- battery capacity in mAh (power banks only)
- `screen_size_in` -- screen size in inches this case/protector is cut for. Not present as a structured field anywhere in this dataset -- `eval/build_ground_truth.py` never suggests it; always hand-labelled or left `null`.
- `wireless_charging` -- `true` / `false` / `null`. `null` unless the raw text gives an explicit signal -- never inferred from absence (see Suggester rules above).
- `material` -- one of `plastic`, `silicone_tpu`, `leather`, `metal`, `tempered_glass`, `fabric_nylon`, `other`

## Regenerating

`scripts/build_eval_template.py` **overwrites `labels_template.json` and
destroys any hand-written labels** -- do not re-run it once labeling starts.
If the SKU selection or schema needs to change, do that deliberately and
re-label, don't regenerate over existing work.

`eval/build_ground_truth.py` is safe to re-run at any point, including after
changing its own suggestion rules -- see Workflow step 2 for exactly what it
will and won't touch.
