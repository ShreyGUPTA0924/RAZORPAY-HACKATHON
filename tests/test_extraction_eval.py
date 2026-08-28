from eval.extraction_eval import expected_quarantine_skus, score_field, values_match


def test_values_match_is_case_insensitive_for_strings():
    assert values_match("USB-C", "usb-c")
    assert not values_match("USB-C", "Lightning")


def test_values_match_is_set_based_for_lists():
    assert values_match(["Xiaomi Mi 4i", "Mi 4i"], ["mi 4i", "xiaomi mi 4i"])
    assert not values_match(["Xiaomi Mi 4i"], ["Xiaomi Mi 4S"])


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
