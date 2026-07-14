"""Person-name normalization and the NameComparator.

"Dr. Jane A. Smith", "Smith, Jane A.", and "jane smith" may all point at
the same person. The comparator must equate legitimate reorderings and
honorific noise while still rejecting genuinely different people.
"""

from fieldscore.comparators import NameComparator, name_tokens, names_match


def test_tokens_strip_honorifics_suffixes_and_accents():
    assert name_tokens("Dr. Jane Smith, Jr.") == ["jane", "smith"]
    assert name_tokens("José García") == ["jose", "garcia"]


def test_comma_reorders_unless_it_precedes_a_suffix():
    assert name_tokens("Smith, Jane") == ["jane", "smith"]
    # "John Smith, Jr." is not "Jr. John Smith".
    assert name_tokens("John Smith, Jr.") == ["john", "smith"]


def test_hyphenated_surname_splits():
    assert name_tokens("Mary Smith-Jones") == ["mary", "smith", "jones"]


def test_order_case_and_punctuation_are_irrelevant():
    assert names_match("Sato Yuki", "Yuki Sato")
    assert names_match("JANE SMITH", "jane smith")
    assert names_match("O'Brien, Patrick", "Patrick O Brien")


def test_initial_matches_full_token_with_the_same_letter():
    assert names_match("J. Smith", "John Smith")
    assert names_match("John Q. Smith", "John Quincy Smith")
    assert not names_match("J. Smith", "Karl Smith")


def test_extra_token_is_a_mismatch_by_default():
    # Strict mode: "Jane A. Smith" has a token "Smith, Jane" cannot account for.
    assert not names_match("Jane A. Smith", "Smith, Jane")


def test_subset_ok_allows_dropped_middle_names():
    assert names_match("Jane A. Smith", "Smith, Jane", subset_ok=True)
    assert names_match("Jane Smith", "Jane Alice Smith", subset_ok=True)


def test_different_people_never_match_even_with_subset_ok():
    assert not names_match("Jane Smith", "Jane Jones", subset_ok=True)
    assert not names_match("Virginia Potts", "Pepper Potts")


def test_comparator_wraps_names_match_and_survives_non_strings():
    assert NameComparator().match("Dr. Jane Smith", "smith, jane")
    assert not NameComparator().match("Jane Smith", "John Smith")
    # A numeric "name" is nonsense, but identical nonsense should not crash.
    assert NameComparator().match(42, "42")
