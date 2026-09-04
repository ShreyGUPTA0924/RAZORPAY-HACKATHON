from surface.refusal import Refusal, RefusalCategory, RefusalCode, refusal_codes_table


def test_every_code_has_a_category():
    for code in RefusalCode:
        assert Refusal(code=code, detail="x").category in RefusalCategory


def test_refusal_codes_table_covers_every_code_exactly_once():
    table = refusal_codes_table()
    assert len(table) == len(list(RefusalCode))
    codes_in_table = {row["code"] for row in table}
    assert codes_in_table == {c.value for c in RefusalCode}


def test_thirteen_codes_across_six_categories():
    # 12 original + CUMULATIVE_CEILING_EXCEEDED, added to close the
    # cumulative-ceiling bypass -- see docs/what-broke.md.
    assert len(list(RefusalCode)) == 13
    assert len(list(RefusalCategory)) == 6


def test_to_dict_includes_code_category_detail_context():
    r = Refusal(code=RefusalCode.OVER_PRICE_CEILING, detail="cart total 5000 > ceiling 3000", context={"total": 5000, "ceiling": 3000})
    d = r.to_dict()
    assert d["code"] == "over_price_ceiling"
    assert d["category"] == "policy"
    assert d["detail"] == "cart total 5000 > ceiling 3000"
    assert d["context"] == {"total": 5000, "ceiling": 3000}


def test_refusal_context_defaults_to_empty_dict():
    r = Refusal(code=RefusalCode.INTERNAL_ERROR, detail="x")
    assert r.context == {}
