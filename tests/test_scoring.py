"""The scoring engine: counts, list alignment, and metric math.

These tests build tiny record sets by hand and assert on exact tallies —
if any of them drifts, the headline numbers users gate CI on drift too.
"""

from fieldscore.config import FieldConfig, parse_config
from fieldscore.loader import AlignedPair
from fieldscore.scoring import score_pairs


def pair(gold, pred, record_id="r1"):
    return AlignedPair(record_id=record_id, gold=gold, pred=pred)


def test_perfect_match_scores_one():
    report = score_pairs([pair({"a": "x"}, {"a": "x"})])
    counts = report.per_field["a"]
    assert (counts.gold, counts.pred, counts.correct) == (1, 1, 1)
    assert counts.f1 == 1.0


def test_wrong_value_hurts_both_precision_and_recall():
    report = score_pairs([pair({"a": "x"}, {"a": "y"})])
    counts = report.per_field["a"]
    assert (counts.gold, counts.pred, counts.correct) == (1, 1, 0)
    assert counts.precision == 0.0 and counts.recall == 0.0


def test_missing_field_hurts_recall_only():
    report = score_pairs([pair({"a": "x", "b": "y"}, {"a": "x"})])
    assert report.per_field["b"].gold == 1
    assert report.per_field["b"].pred == 0
    kinds = {(m.path, m.kind) for m in report.mismatches}
    assert ("b", "missing") in kinds


def test_spurious_field_hurts_precision_only():
    report = score_pairs([pair({"a": "x"}, {"a": "x", "hallucinated": "z"})])
    counts = report.per_field["hallucinated"]
    assert (counts.gold, counts.pred, counts.correct) == (0, 1, 0)
    kinds = {(m.path, m.kind) for m in report.mismatches}
    assert ("hallucinated", "spurious") in kinds


def test_absent_records_score_every_field_on_the_present_side():
    # A skipped document is all misses; an invented one is all spurious.
    report = score_pairs([pair({"a": "x", "b": "y"}, None)])
    assert report.per_field["a"].gold == 1 and report.per_field["a"].pred == 0
    assert report.per_field["b"].gold == 1 and report.per_field["b"].pred == 0
    report = score_pairs([pair(None, {"a": "x"})])
    assert report.per_field["a"].pred == 1 and report.per_field["a"].correct == 0


def test_id_field_is_never_scored():
    config = FieldConfig(id_field="id")
    report = score_pairs([pair({"id": "1", "a": "x"}, {"id": "1", "a": "x"})], config)
    assert "id" not in report.per_field


def test_scalar_list_matches_as_multiset_by_default():
    report = score_pairs([pair({"tags": ["a", "b"]}, {"tags": ["b", "a"]})])
    assert report.per_field["tags"].correct == 2
    # Extra and missing elements count individually, not as one wrong list.
    report = score_pairs([pair({"tags": ["a", "b", "c"]}, {"tags": ["a", "z"]})])
    counts = report.per_field["tags"]
    assert (counts.gold, counts.pred, counts.correct) == (3, 2, 1)


def test_scalar_list_ordered_option_pins_positions():
    config = parse_config(
        {"fields": {"tags": {"type": "string", "ordered": True}}}
    )
    report = score_pairs([pair({"tags": ["a", "b"]}, {"tags": ["b", "a"]})], config)
    assert report.per_field["tags"].correct == 0


def test_scalar_vs_singleton_list_shape_mismatch_is_forgiven():
    # "net30" against ["net30"] is a shape quibble, not a wrong extraction.
    report = score_pairs([pair({"tag": "net30"}, {"tag": ["net30"]})])
    assert report.per_field["tag"].correct == 1


def test_object_lists_align_out_of_order():
    gold = {"items": [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 2}]}
    pred = {"items": [{"sku": "B", "qty": 2}, {"sku": "A", "qty": 1}]}
    report = score_pairs([pair(gold, pred)])
    assert report.per_field["items[].sku"].correct == 2
    assert report.per_field["items[].qty"].correct == 2


def test_object_list_partial_element_scores_per_leaf():
    # One wrong leaf in one element must not poison the other columns.
    gold = {"items": [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 2}]}
    pred = {"items": [{"sku": "A", "qty": 9}, {"sku": "B", "qty": 2}]}
    report = score_pairs([pair(gold, pred)])
    assert report.per_field["items[].sku"].correct == 2
    assert report.per_field["items[].qty"].correct == 1


def test_object_list_unrelated_element_is_spurious_not_wrong():
    gold = {"items": [{"sku": "A", "qty": 1}]}
    pred = {"items": [{"sku": "A", "qty": 1}, {"sku": "ZZZ", "qty": 99}]}
    report = score_pairs([pair(gold, pred)])
    counts = report.per_field["items[].sku"]
    assert (counts.gold, counts.pred, counts.correct) == (1, 2, 1)
    kinds = {m.kind for m in report.mismatches}
    assert kinds == {"spurious"}


def test_object_list_leaf_comparators_come_from_config():
    config = parse_config(
        {"fields": {"items[].price": {"type": "money", "tolerance": 0.01}}}
    )
    gold = {"items": [{"price": "$10.00"}]}
    pred = {"items": [{"price": "10.01 USD"}]}
    report = score_pairs([pair(gold, pred)], config)
    assert report.per_field["items[].price"].correct == 1


def test_micro_pools_counts_and_macro_averages_f1():
    report = score_pairs([
        pair({"a": "x", "b": "y"}, {"a": "x", "b": "wrong"}),
        pair({"a": "x", "b": "y"}, {"a": "x", "b": "y"}, record_id="r2"),
    ])
    micro = report.micro
    assert (micro.gold, micro.pred, micro.correct) == (4, 4, 3)
    # a: f1=1.0, b: f1=0.5 -> macro 0.75
    assert abs(report.macro_f1 - 0.75) < 1e-9
    assert abs(micro.f1 - 0.75) < 1e-9
    # And an empty run must yield zeros, not a ZeroDivisionError.
    empty = score_pairs([])
    assert empty.micro.f1 == 0.0 and empty.macro_f1 == 0.0
