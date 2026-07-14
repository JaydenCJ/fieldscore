"""Money parsing and the MoneyComparator.

Currency values arrive as "$1,234.50", "1234.5 USD", "EUR 1.234,50" and
worse. The parser must resolve separators, symbols, codes, and accounting
negatives — and the comparator must respect tolerances and currency clashes.
"""

from decimal import Decimal

from fieldscore.comparators import MoneyComparator, parse_money


def test_symbol_and_code_notations_parse():
    assert parse_money("$1,234.56") == (Decimal("1234.56"), "USD")
    assert parse_money("1234.56 USD") == (Decimal("1234.56"), "USD")
    assert parse_money("EUR 99") == (Decimal("99"), "EUR")
    assert parse_money("¥50,000") == (Decimal("50000"), "JPY")


def test_separator_disambiguation():
    # European: dot groups thousands, comma is decimal. A lone comma is
    # decimal only with 1-2 trailing digits; otherwise it groups thousands.
    assert parse_money("€1.234,56") == (Decimal("1234.56"), "EUR")
    assert parse_money("12,50") == (Decimal("12.50"), None)
    assert parse_money("1,234") == (Decimal("1234"), None)


def test_negatives_in_both_conventions():
    assert parse_money("(45.00)") == (Decimal("-45.00"), None)
    assert parse_money("-45.00") == (Decimal("-45.00"), None)


def test_bare_numbers_parse_without_currency():
    assert parse_money(1234.5) == (Decimal("1234.5"), None)
    assert parse_money(99) == (Decimal("99"), None)


def test_non_monetary_values_return_none():
    assert parse_money("no charge") is None
    assert parse_money(True) is None
    assert parse_money(None) is None
    assert parse_money("") is None


def test_multichar_symbols_win_over_bare_dollar():
    # "R$" must resolve to BRL even though it contains "$"; a symbol-table
    # ordering slip here silently turned Brazilian reais into US dollars.
    assert parse_money("R$100") == (Decimal("100"), "BRL")
    assert parse_money("US$100") == (Decimal("100"), "USD")
    assert not MoneyComparator().match("R$100", "$100")


def test_comparator_matches_across_notations():
    comparator = MoneyComparator()
    assert comparator.match("$1,234.50", "1234.50 USD")
    assert comparator.match("€2,000.00", "EUR 2.000,00")
    # Models often drop the symbol; by default amount alone then decides.
    assert comparator.match("$1,234.50", "1234.5")


def test_comparator_currency_clash_is_a_mismatch():
    # Same amount, different currency: never equal.
    assert not MoneyComparator().match("100 USD", "100 EUR")


def test_comparator_require_currency_rejects_bare_amounts():
    comparator = MoneyComparator(require_currency=True)
    assert not comparator.match("$1,234.50", "1234.5")
    assert comparator.match("$1,234.50", "1,234.50 USD")


def test_comparator_tolerance_absorbs_rounding_only():
    comparator = MoneyComparator(tolerance=0.01)
    assert comparator.match("$10.00", "$10.01")
    assert not comparator.match("$10.00", "$10.02")
    # Default tolerance is exact.
    assert not MoneyComparator().match("$10.00", "$10.01")
