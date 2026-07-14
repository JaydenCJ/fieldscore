"""Flatten nested JSON records into dot-path leaf maps.

Scoring works on *fields*, not on documents. This module turns

    {"vendor": {"name": "Acme"}, "tags": ["net30", "paid"]}

into

    {"vendor.name": "Acme", "tags": ["net30", "paid"]}

Nested objects become dotted paths; lists are kept whole as the value at
their path — the scorer decides how to align their elements (scalar lists
become multisets, lists of objects are aligned pairwise). Values that mean
"the model extracted nothing" (``None``, ``""``, ``[]``, ``{}``) are dropped
so they count as *absent*, not as a value that must be matched.
"""

from __future__ import annotations

from typing import Any, Dict

# A path segment suffix marking "per element of this list" in field specs
# and in reported field names, e.g. ``line_items[].sku``.
LIST_MARKER = "[]"


def is_absent(value: Any) -> bool:
    """True for values that represent "nothing extracted"."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def flatten(record: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten one JSON object into ``{dot.path: leaf_value}``.

    Leaf values are scalars or lists. Absent values (see :func:`is_absent`)
    are omitted entirely. Keys are joined with ``.``; a literal dot inside a
    key is left as-is (documented limitation — prefer dot-free keys).
    """
    flat: Dict[str, Any] = {}
    for key, value in record.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if is_absent(value):
            continue
        if isinstance(value, dict):
            flat.update(flatten(value, path))
        else:
            flat[path] = value
    return flat


def is_object_list(value: Any) -> bool:
    """True when the value is a non-empty list made entirely of objects."""
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, dict) for item in value)
    )


def canonical_path(path: str) -> str:
    """Field-spec form of a path: indexes generalized to ``[]``.

    ``line_items[2].sku`` → ``line_items[].sku`` (reserved for future
    indexed reporting; scoring itself always attributes to the ``[]`` form).
    """
    import re

    return re.sub(r"\[\d+\]", LIST_MARKER, path)
