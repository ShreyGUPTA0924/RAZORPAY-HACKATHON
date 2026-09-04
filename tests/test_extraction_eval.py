import json

from eval.extraction_eval import (
    expected_quarantine_skus,
    load_predictions,
    score_field,
    values_match,
)

# ---------------------------------------------------------------------------
# load_predictions -- adapts pipeline/extract.py's REAL output shape (a list
# of {sku_id, attributes: {field: {value, confidence}}, error} records,
# exactly what eval/extraction_results.json contains) into the
# {sku_id: {field: value}} shape score_field() works with. Regression
# coverage for a real bug: this previously assumed an abstract
# already-flat shape nothing in the codebase ever actually produced,
# written before pipeline/extract.py existed and never reconciled against
# its real output -- caught by actually running the eval against the real
# file, not by any test, since no test exercised load_predictions at all.
# ---------------------------------------------------------------------------


def test_load_predictions_unwraps_confidence_from_the_real_extract_output_shape(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "sku_id": "SKU-1",
                    "error": None,
                    "attributes": {
                        "accessory_type": {"value": "cable", "confidence": 0.95},
                        "material": {"value": None, "confidence": 0.0},
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    predictions = load_predictions(path)
    assert predictions == {"SKU-1": {"accessory_type": "cable", "material": None}}


def test_load_predictions_skips_errored_extractions(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text(
        json.dumps(
            [
                {"sku_id": "SKU-1", "error": "extraction call failed: boom", "attributes": {}},
                {"sku_id": "SKU-2", "error": None, "attributes": {"material": {"value": "plastic", "confidence": 0.9}}},
            ]
        ),
        encoding="utf-8",
    )
    predictions = load_predictions(path)
    assert "SKU-1" not in predictions
    assert predictions["SKU-2"] == {"material": "plastic"}


def test_values_match_is_case_insensitive_for_strings():
    assert values_match("USB-C", "usb-c")
    assert not values_match("USB-C", "Lightning")


def test_values_match_is_set_based_for_lists():
    assert values_match(["Xiaomi Mi 4i", "Mi 4i"], ["mi 4i", "xiaomi mi 4i"])
    assert not values_match(["Xiaomi Mi 4i"], ["Xiaomi Mi 4S"])


def test_values_match_bridges_space_vs_underscore_and_hyphen():
    """Regression test for a real bug: ground truth is hand-labeled as
    human-readable text straight off the listing ("Samsung Galaxy J7"),
    while pipeline/extract.py emits canonical snake_case
    ("samsung_galaxy_j7") -- without this, every real model_compat
    comparison failed, scoring a flat 0.00 precision/recall across 13 real
    support rows despite the predictions being correct. Mirrors
    pipeline/verify.py's own _normalize()."""
    assert values_match("samsung_galaxy_j7", "Samsung Galaxy J7")
    assert values_match(["samsung_galaxy_j7"], ["Samsung Galaxy J7"])
    assert values_match("htc-one-s", "HTC One S")


def test_score_field_true_positive():
    gt = {"SKU-1": {"material": "plastic"}}
    pred = {"SKU-1": {"material": "plastic"}}
    m = score_field("material", pred, gt)
    assert (m.tp, m.fp, m.fn, m.support) == (1, 0, 0, 1)
    assert m.precision == 1.0
    assert m.recall == 1.0
    assert m.f1 == 1.0


def test_score_field_false_negative_when_prediction_missing():
    gt = {"SKU-1": {"material": "plastic"}}
    pred = {"SKU-1": {"material": None}}
    m = score_field("material", pred, gt)
    assert (m.tp, m.fp, m.fn) == (0, 0, 1)
    assert m.precision is None  # tp+fp == 0
    assert m.recall == 0.0


def test_score_field_wrong_value_counts_as_both_fp_and_fn():
    gt = {"SKU-1": {"material": "plastic"}}
    pred = {"SKU-1": {"material": "metal"}}
    m = score_field("material", pred, gt)
    assert (m.tp, m.fp, m.fn) == (0, 1, 1)
    assert m.precision == 0.0
    assert m.recall == 0.0


def test_score_field_extra_prediction_where_ground_truth_is_null_is_false_positive():
    gt = {"SKU-1": {"material": None}}
    pred = {"SKU-1": {"material": "plastic"}}
    m = score_field("material", pred, gt)
    assert (m.tp, m.fp, m.fn, m.support) == (0, 1, 0, 0)


def test_score_field_both_null_is_not_counted():
    gt = {"SKU-1": {"material": None}}
    pred = {"SKU-1": {"material": None}}
    m = score_field("material", pred, gt)
    assert (m.tp, m.fp, m.fn, m.support) == (0, 0, 0, 0)
    assert m.precision is None
    assert m.recall is None
    assert m.f1 is None


def test_score_field_aggregates_across_skus():
    gt = {
        "SKU-1": {"material": "plastic"},
        "SKU-2": {"material": "metal"},
        "SKU-3": {"material": None},
    }
    pred = {
        "SKU-1": {"material": "plastic"},  # tp
        "SKU-2": {"material": "leather"},  # fp + fn (wrong value)
        "SKU-3": {"material": "metal"},  # fp (claimed where gt is null)
    }
    m = score_field("material", pred, gt)
    assert (m.tp, m.fp, m.fn, m.support) == (1, 2, 1, 2)


def test_expected_quarantine_skus_finds_all_null_rows():
    gt = {
        "SKU-1": {"material": "plastic", "connector_type": None},
        "SKU-2": {"material": None, "connector_type": None},
    }
    assert expected_quarantine_skus(gt) == ["SKU-2"]
