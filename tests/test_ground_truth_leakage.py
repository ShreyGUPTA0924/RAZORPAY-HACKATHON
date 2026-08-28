"""
Guards the one hard split-hygiene invariant from eval/build_ground_truth.py:
the seller's own "Specifications of ..." spec-table dump must never survive
into extractor_eval_description, for any held-out SKU. This re-checks
whatever is actually committed in labels_template.json, not just the moment
build_ground_truth.py last ran -- so a future hand-edit that accidentally
pastes the spec block back in gets caught here, not discovered later as a
silently inflated eval score.

Deliberately does NOT assert that no ground-truth value string appears
anywhere in extractor_eval_description -- sellers routinely restate the
compatible phone model in the description's own prose, and that's the
extraction signal this eval measures, not a leak. See the module docstring
in eval/build_ground_truth.py for the full reasoning.
"""

import json
from pathlib import Path

from eval.build_ground_truth import SPEC_BLOCK_MARKER

LABELS_TEMPLATE = Path(__file__).resolve().parent.parent / "eval" / "ground_truth" / "labels_template.json"


def _load_entries():
    return json.loads(LABELS_TEMPLATE.read_text(encoding="utf-8"))


def test_every_entry_has_an_extractor_eval_description():
    entries = _load_entries()
    assert entries, "labels_template.json is empty"
    for entry in entries:
        assert "extractor_eval_description" in entry, f"{entry['sku_id']}: missing extractor_eval_description"


def test_no_spec_block_marker_survives_the_strip():
    entries = _load_entries()
    leaked = [
        entry["sku_id"]
        for entry in entries
        if SPEC_BLOCK_MARKER.search(entry["extractor_eval_description"])
    ]
    assert not leaked, f"'Specifications of' marker survived the strip for: {leaked}"


def test_extractor_eval_description_is_a_prefix_of_raw_description():
    """extractor_eval_description must be exactly raw_description truncated at
    the marker (or unchanged if no marker) -- never something else entirely,
    e.g. from a stale/hand-edited value that no longer matches its source."""
    entries = _load_entries()
    for entry in entries:
        raw = entry["raw_description"]
        stripped = entry["extractor_eval_description"]
        assert raw.startswith(stripped), (
            f"{entry['sku_id']}: extractor_eval_description is not a prefix of raw_description "
            "-- did raw_description change without regenerating via eval/build_ground_truth.py?"
        )
