"""Exception types raised by fieldscore.

All errors that fieldscore raises deliberately derive from
:class:`FieldscoreError`, so callers can catch one type at the CLI boundary
and turn it into a clean exit code instead of a traceback.
"""

from __future__ import annotations


class FieldscoreError(Exception):
    """Base class for all fieldscore errors."""


class ConfigError(FieldscoreError):
    """The field configuration file is malformed or references an unknown
    comparator type or option."""


class DataError(FieldscoreError):
    """An input file could not be parsed as JSON/JSONL, or the records are
    not JSON objects."""


class AlignmentError(FieldscoreError):
    """Gold and predicted records could not be aligned (e.g. a duplicate id
    value when joining on ``id_field``)."""
