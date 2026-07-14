"""Number, bool, string, and auto comparators.

The "boring" comparators carry most fields in a real schema, so their edge
behavior (percent signs, yes/no booleans, fuzzy thresholds, auto-detection
order) is pinned here.
"""

import pytest

from fieldscore.comparators import (
    AutoComparator,
    BoolComparator,
    NumberComparator,
    StringComparator,
    parse_bool,
    parse_number,
)
from fieldscore.errors import ConfigError


def test_parse_number_separators_percent_and_rejections():
    assert parse_number("1,234.5") == 1234.5
    assert parse_number("12%") == 12.0
    assert parse_number("-3") == -3.0
    # bool is an int subclass in Python; True must not become 1.0 silently.
    assert parse_number(True) is None
    assert parse_number("about 5") is None


def test_number_comparator_int_vs_float_string_and_abs_tolerance():
    assert NumberComparator().match(10, "10.0")
    comparator = NumberComparator(abs_tol=0.5)
    assert comparator.match(10, 10.4)
    assert not comparator.match(10, 10.6)


def test_number_comparator_rel_tolerance():
    comparator = NumberComparator(rel_tol=0.01)
    assert comparator.match(1000, 1009)
    assert not comparator.match(1000, 1020)


def test_bool_vocabulary_and_comparator():
    assert parse_bool("yes") is True
    assert parse_bool("No") is False
    assert parse_bool(1) is True
    assert parse_bool("maybe") is None
    assert parse_bool(2) is None
    comparator = BoolComparator()
    assert comparator.match(True, "yes")
    assert comparator.match(False, "0")
    assert not comparator.match(True, "no")
    assert not comparator.match(True, "maybe")


def test_string_exact_and_normalized_modes():
    exact = StringComparator(mode="exact")
    assert exact.match("Acme", "Acme")
    assert not exact.match("Acme", "acme")
    normalized = StringComparator(mode="normalized")
    assert normalized.match("  Acme   Corp ", "acme corp")
    assert normalized.match("ＡＣＭＥ", "acme")  # full-width forms


def test_string_fuzzy_mode_respects_threshold():
    loose = StringComparator(mode="fuzzy", threshold=0.8)
    strict = StringComparator(mode="fuzzy", threshold=0.95)
    assert loose.match("Widget, large", "Widget large")
    assert not strict.match("Widget, large", "Widget largo")


def test_string_invalid_mode_or_threshold_is_a_config_error():
    with pytest.raises(ConfigError):
        StringComparator(mode="soundex")
    with pytest.raises(ConfigError):
        StringComparator(mode="fuzzy", threshold=0.0)


def test_auto_detects_typed_values_in_priority_order():
    comparator = AutoComparator()
    # "1" vs "true" must be judged as booleans, not the number 1 vs NaN.
    assert comparator.match("1", "true")
    assert comparator.match("2024-03-05", "March 5, 2024")
    assert comparator.match("$1,234.50", "1234.5 USD")
    assert not comparator.match("100 USD", "100 EUR")


def test_auto_falls_back_to_normalized_text():
    comparator = AutoComparator()
    assert comparator.match("Net 30", "net 30")
    assert not comparator.match("Net 30", "Net 60")
