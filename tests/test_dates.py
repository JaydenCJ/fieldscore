"""Date parsing and the DateComparator.

Date fields are where exact-match scoring lies the most: the same calendar
day has a dozen legitimate surface forms. These tests pin the accepted
formats and, just as importantly, the strings that must NOT parse.
"""

from datetime import date, datetime

from fieldscore.comparators import DateComparator, parse_date


def test_iso_forms_and_python_objects_parse():
    assert parse_date("2024-03-05") == date(2024, 3, 5)
    assert parse_date("2024-03-05T10:22:00Z") == date(2024, 3, 5)
    assert parse_date(date(2024, 3, 5)) == date(2024, 3, 5)
    assert parse_date(datetime(2024, 3, 5, 14, 0)) == date(2024, 3, 5)


def test_structured_numeric_formats_parse():
    assert parse_date("2024/03/05") == date(2024, 3, 5)
    assert parse_date("20240305") == date(2024, 3, 5)
    assert parse_date("2024年3月5日") == date(2024, 3, 5)


def test_month_name_forms_parse_in_either_order():
    # "March 5th, 2024" and "5-Mar-2024" both appear constantly in model
    # output; ordinal suffixes and hyphens must not break parsing.
    assert parse_date("March 5, 2024") == date(2024, 3, 5)
    assert parse_date("5 Mar 2024") == date(2024, 3, 5)
    assert parse_date("5-Mar-2024") == date(2024, 3, 5)
    assert parse_date("March 5th, 2024") == date(2024, 3, 5)


def test_unambiguous_day_first_wins_regardless_of_flag():
    # 25 cannot be a month, so dayfirst=False must not misread it.
    assert parse_date("25/03/2024", dayfirst=False) == date(2024, 3, 25)


def test_ambiguous_date_respects_dayfirst_flag():
    assert parse_date("03/05/2024", dayfirst=False) == date(2024, 3, 5)
    assert parse_date("03/05/2024", dayfirst=True) == date(2024, 5, 3)


def test_garbage_and_invalid_dates_return_none():
    # An out-of-range day must be rejected, not silently clamped.
    assert parse_date("hello world") is None
    assert parse_date("2024-13-45") is None
    assert parse_date("") is None
    assert parse_date(12345) is None


def test_comparator_matches_across_formats_and_rejects_other_days():
    comparator = DateComparator()
    assert comparator.match("2024-03-05", "March 5, 2024")
    assert comparator.match("2024/03/05", "20240305")
    assert not comparator.match("2024-03-05", "2024-03-06")


def test_comparator_one_side_unparseable_is_a_mismatch():
    # If gold is a date and the prediction is prose, that is a wrong value,
    # not a formatting difference.
    assert not DateComparator().match("2024-03-05", "sometime in spring")


def test_comparator_falls_back_to_text_when_neither_side_is_a_date():
    # Both unparseable but identical: treat as equal strings rather than
    # punishing a field that was never a date to begin with.
    comparator = DateComparator()
    assert comparator.match("Q1 FY24", "q1 fy24")
    assert not comparator.match("Q1 FY24", "Q2 FY24")
