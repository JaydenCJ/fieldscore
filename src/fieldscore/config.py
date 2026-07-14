"""Field configuration: which comparator scores which field.

A config is a small JSON file mapping field paths to comparator specs:

    {
      "id_field": "invoice_id",
      "default_type": "auto",
      "dayfirst": false,
      "fields": {
        "date":        {"type": "date"},
        "total":       {"type": "money", "tolerance": 0.01},
        "vendor.name": {"type": "name"},
        "line_items[].description": {"type": "string", "mode": "fuzzy",
                                     "threshold": 0.8}
      }
    }

Unknown types and unknown option keys are hard errors — a typo in a config
should fail loudly, not silently fall back to exact matching. Fields without
a spec use ``default_type`` (``auto`` unless overridden).
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .comparators import (
    AutoComparator,
    BoolComparator,
    Comparator,
    DateComparator,
    MoneyComparator,
    NameComparator,
    NumberComparator,
    StringComparator,
    parse_bool,
    parse_date,
    parse_money,
    parse_number,
)
from .errors import ConfigError

# type name -> (factory, allowed option keys)
_TYPES: Dict[str, Any] = {
    "string": (StringComparator, {"mode", "threshold"}),
    "date": (DateComparator, {"dayfirst"}),
    "money": (MoneyComparator, {"tolerance", "require_currency"}),
    "number": (NumberComparator, {"abs_tol", "rel_tol"}),
    "bool": (BoolComparator, set()),
    "name": (NameComparator, {"subset_ok"}),
    "auto": (AutoComparator, {"dayfirst"}),
}

TYPE_NAMES = tuple(sorted(_TYPES))


def build_comparator(spec: Mapping[str, Any], dayfirst: bool = False) -> Comparator:
    """Instantiate a comparator from one field spec dict."""
    if not isinstance(spec, Mapping):
        raise ConfigError(f"field spec must be an object, got {type(spec).__name__}")
    type_name = spec.get("type")
    if type_name not in _TYPES:
        raise ConfigError(
            f"unknown field type {type_name!r}; expected one of {', '.join(TYPE_NAMES)}"
        )
    factory, allowed = _TYPES[type_name]
    options = {k: v for k, v in spec.items() if k not in ("type", "ordered")}
    unknown = set(options) - allowed
    if unknown:
        raise ConfigError(
            f"unknown option(s) {sorted(unknown)} for type {type_name!r}; "
            f"allowed: {sorted(allowed) or 'none'}"
        )
    if type_name in ("date", "auto") and "dayfirst" not in options:
        options["dayfirst"] = dayfirst
    return factory(**options)


@dataclass
class FieldConfig:
    """Resolved scoring configuration for one run."""

    id_field: Optional[str] = None
    default_type: str = "auto"
    dayfirst: bool = False
    fields: Dict[str, Comparator] = field(default_factory=dict)
    ordered: Dict[str, bool] = field(default_factory=dict)
    _default: Optional[Comparator] = None

    def __post_init__(self) -> None:
        if self.default_type not in _TYPES:
            raise ConfigError(
                f"unknown default_type {self.default_type!r}; "
                f"expected one of {', '.join(TYPE_NAMES)}"
            )
        self._default = build_comparator(
            {"type": self.default_type}, dayfirst=self.dayfirst
        )

    def comparator_for(self, path: str) -> Comparator:
        """Comparator for a canonical field path (``a.b`` or ``items[].x``)."""
        found = self.fields.get(path)
        if found is not None:
            return found
        assert self._default is not None
        return self._default

    def is_ordered(self, path: str) -> bool:
        """Whether a list field must match element order (default: no)."""
        return self.ordered.get(path, False)

    def type_name_for(self, path: str) -> str:
        return self.comparator_for(path).type_name


def load_config(path: Path, dayfirst: Optional[bool] = None) -> FieldConfig:
    """Load and validate a JSON config file into a :class:`FieldConfig`.

    ``dayfirst=True`` (from the CLI ``--dayfirst`` flag) overrides the
    file's top-level ``dayfirst``; a per-field explicit ``dayfirst`` option
    still wins over both.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    return parse_config(raw, dayfirst=dayfirst)


def parse_config(raw: Any, dayfirst: Optional[bool] = None) -> FieldConfig:
    """Validate an already-decoded config object.

    ``dayfirst``, when not ``None``, overrides the config's own top-level
    ``dayfirst`` setting (see :func:`load_config`).
    """
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a JSON object")
    known_keys = {"id_field", "default_type", "dayfirst", "fields"}
    unknown = set(raw) - known_keys
    if unknown:
        raise ConfigError(
            f"unknown config key(s) {sorted(unknown)}; allowed: {sorted(known_keys)}"
        )
    if dayfirst is None:
        dayfirst = bool(raw.get("dayfirst", False))
    fields_raw = raw.get("fields", {})
    if not isinstance(fields_raw, dict):
        raise ConfigError("config 'fields' must be an object")
    comparators: Dict[str, Comparator] = {}
    ordered: Dict[str, bool] = {}
    for path, spec in fields_raw.items():
        try:
            comparators[path] = build_comparator(spec, dayfirst=dayfirst)
        except ConfigError as exc:
            raise ConfigError(f"field {path!r}: {exc}") from exc
        if isinstance(spec, Mapping) and "ordered" in spec:
            ordered[path] = bool(spec["ordered"])
    return FieldConfig(
        id_field=raw.get("id_field"),
        default_type=raw.get("default_type", "auto"),
        dayfirst=dayfirst,
        fields=comparators,
        ordered=ordered,
    )


# ---------------------------------------------------------------------------
# Type inference (`fieldscore infer`)
# ---------------------------------------------------------------------------

_NAME_KEY_HINTS = ("name", "author", "signee", "attendee", "contact")

# Inference-only strict money shape: an optional currency code/symbol, an
# amount, and nothing else. The runtime money comparator is looser on
# purpose ("Total: $5" still scores), but inference must not label a SKU
# like "WID-1" as money just because it contains a digit.
_MONEY_STRICT_RE = re.compile(
    r"^\(?\s*"
    r"(?:[A-Z]{3}\s+|(?:US|A|C|NZ|HK|R)?\$\s*|[€£¥₹₩₺₫฿]\s*)?"
    r"-?\d[\d.,]*"
    r"(?:\s*[A-Z]{3})?\s*\)?$"
)


def _strict_money(value: Any) -> Optional[Any]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return parse_money(value)
    if isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).strip()
        if _MONEY_STRICT_RE.match(text):
            return parse_money(text)
    return None


def _guess_type(path: str, values: List[Any]) -> str:
    """Guess a comparator type from sample values (and the key, for names).

    A type wins when at least 80% of the non-absent samples parse as it.
    Money outranks number only when a currency marker is actually present in
    at least one sample; name inference additionally requires a name-like
    key, because "two capitalized words" also describes most product titles.
    """
    if not values:
        return "auto"
    threshold = max(1, math.ceil(len(values) * 0.8))

    def hits(parser: Any) -> int:
        return sum(1 for v in values if parser(v) is not None)

    if hits(parse_bool) >= threshold:
        return "bool"
    if hits(parse_date) >= threshold:
        return "date"
    money_hits = [_strict_money(v) for v in values]
    with_currency = sum(1 for m in money_hits if m is not None and m[1] is not None)
    if sum(1 for m in money_hits if m is not None) >= threshold and with_currency >= 1:
        return "money"
    if hits(parse_number) >= threshold:
        return "number"
    leaf = path.rsplit(".", 1)[-1].casefold()
    if any(hint in leaf for hint in _NAME_KEY_HINTS) and all(
        isinstance(v, str) for v in values
    ):
        return "name"
    return "string"


def infer_config(
    flat_records: List[Dict[str, Any]], id_field: Optional[str] = None
) -> Dict[str, Any]:
    """Build a config skeleton (as a plain dict) from flattened gold records.

    Used by ``fieldscore infer`` to give teams a reviewable starting point;
    the output is meant to be edited, not trusted blindly.
    """
    from .flatten import flatten, is_object_list

    samples: Dict[str, List[Any]] = {}

    def collect(paths: Dict[str, Any]) -> None:
        for path, value in paths.items():
            if is_object_list(value):
                for element in value:
                    collect({
                        f"{path}[].{sub}": subvalue
                        for sub, subvalue in flatten(element).items()
                    })
            elif isinstance(value, list):
                samples.setdefault(path, []).extend(
                    v for v in value if not isinstance(v, (list, dict))
                )
            else:
                samples.setdefault(path, []).append(value)

    for flat in flat_records:
        collect(flat)
    fields = {
        path: {"type": _guess_type(path, values)}
        for path, values in sorted(samples.items())
        if path != id_field
    }
    config: Dict[str, Any] = {"default_type": "auto", "fields": fields}
    if id_field:
        config = {"id_field": id_field, **config}
    return config
