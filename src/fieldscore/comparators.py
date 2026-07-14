"""Type-aware value comparators.

Each comparator answers one question: *does this predicted value mean the
same thing as this gold value?* Exact string equality is the wrong tool for
extraction output — ``"2024-03-05"`` and ``"March 5, 2024"`` are the same
date, ``"$1,234.50"`` and ``"1234.5 USD"`` are the same amount, and
``"Dr. Jane A. Smith"`` and ``"Smith, Jane"`` are the same person. The
parsers here are deliberately conservative: when a value cannot be parsed
as the declared type on *both* sides, the comparator falls back to
normalized string equality rather than guessing.

Everything in this module is pure and deterministic: no locale calls, no
clock reads, no network.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, List, Optional, Tuple

from .errors import ConfigError

# ---------------------------------------------------------------------------
# String normalization
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def normalize_text(value: Any) -> str:
    """NFKC-normalize, casefold, and collapse whitespace.

    This is the shared "loose but honest" text form: it erases full-width /
    half-width differences, case, and spacing, but never letters or digits.
    """
    text = value if isinstance(value, str) else _stringify(value)
    text = unicodedata.normalize("NFKC", text)
    return _WS_RE.sub(" ", text).strip().casefold()


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def similarity(a: str, b: str) -> float:
    """Symmetric similarity ratio in [0, 1] over normalized text."""
    return SequenceMatcher(a=normalize_text(a), b=normalize_text(b)).ratio()


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_YMD_RE = re.compile(r"(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})$")
_DMY_RE = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$")
_COMPACT_RE = re.compile(r"(\d{4})(\d{2})(\d{2})$")
_CJK_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日$")
_ORDINAL_RE = re.compile(r"(\d{1,2})(st|nd|rd|th)\b")


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(value: Any, dayfirst: bool = False) -> Optional[date]:
    """Parse a calendar date from the formats extraction output actually uses.

    Supported: ISO 8601 (with or without a time component), ``YYYY/MM/DD``,
    ``DD/MM/YYYY`` / ``MM/DD/YYYY`` (ambiguity resolved by magnitude, then by
    ``dayfirst``), ``YYYYMMDD``, month-name forms in either order
    (``March 5, 2024`` / ``5 Mar 2024``), and CJK ``2024年3月5日``.
    Returns ``None`` when the value is not recognizably a date.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return None

    # ISO 8601, possibly with a time part ("2024-03-05T10:22:00Z").
    iso = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    m = _CJK_RE.match(text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _YMD_RE.match(text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DMY_RE.match(text)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:          # 25/03/2024 can only be day-first
            return _safe_date(year, b, a)
        if b > 12 and a <= 12:          # 03/25/2024 can only be month-first
            return _safe_date(year, a, b)
        if dayfirst:
            return _safe_date(year, b, a)
        return _safe_date(year, a, b)
    m = _COMPACT_RE.match(text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # Month-name forms: "March 5, 2024", "5 Mar 2024", "5-Mar-2024".
    words = _ORDINAL_RE.sub(r"\1", text)
    tokens = [t for t in re.split(r"[\s,\-.]+", words) if t]
    if len(tokens) == 3:
        lowered = [t.casefold() for t in tokens]
        for month_pos in (0, 1):
            month = _MONTH_NAMES.get(lowered[month_pos])
            if month is None:
                continue
            rest = [tokens[i] for i in range(3) if i != month_pos]
            if all(t.isdigit() for t in rest):
                nums = [int(t) for t in rest]
                # The 4-digit number is the year, the other one the day.
                years = [n for n in nums if n >= 1000]
                days = [n for n in nums if n < 1000]
                if len(years) == 1 and len(days) == 1:
                    return _safe_date(years[0], month, days[0])
    return None


# ---------------------------------------------------------------------------
# Money parsing
# ---------------------------------------------------------------------------

# Matching iterates in insertion order, so every multi-character symbol
# must precede the bare "$" or "R$100" would be misread as USD.
_CURRENCY_SYMBOLS = {
    "US$": "USD", "A$": "AUD", "C$": "CAD", "NZ$": "NZD", "HK$": "HKD",
    "R$": "BRL",
    "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR",
    "₩": "KRW", "₺": "TRY", "₫": "VND", "฿": "THB",
}
_CURRENCY_CODE_RE = re.compile(r"\b([A-Z]{3})\b")
_AMOUNT_RE = re.compile(r"-?\d[\d.,]*")


def _parse_amount(digits: str) -> Optional[Decimal]:
    """Resolve thousands/decimal separators in a bare numeric string.

    Heuristics (documented in docs/scoring.md): with both ``,`` and ``.``,
    the rightmost one is the decimal separator. A lone ``,`` is decimal only
    when followed by 1–2 digits (``12,50``); otherwise it groups thousands.
    A lone ``.`` is decimal unless it appears more than once (``1.234.567``).
    """
    if "," in digits and "." in digits:
        dec = "," if digits.rfind(",") > digits.rfind(".") else "."
    elif "," in digits:
        parts = digits.split(",")
        dec = "," if len(parts) == 2 and len(parts[1]) in (1, 2) else ""
    elif "." in digits:
        dec = "." if digits.count(".") == 1 else ""
    else:
        dec = ""
    if dec:
        thousands = "." if dec == "," else ","
        digits = digits.replace(thousands, "").replace(dec, ".")
    else:
        digits = digits.replace(",", "").replace(".", "")
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def parse_money(value: Any) -> Optional[Tuple[Decimal, Optional[str]]]:
    """Parse an amount and an optional ISO currency code.

    Accepts numbers, ``"$1,234.56"``, ``"1234.56 USD"``, ``"EUR 99"``,
    ``"€1.234,56"``, ``"¥1,000"``, and accounting negatives ``"(45.00)"``.
    Returns ``(amount, currency_or_None)``, or ``None`` if no amount is found.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value)), None
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()

    currency: Optional[str] = None
    code = _CURRENCY_CODE_RE.search(text)
    if code:
        currency = code.group(1)
        text = (text[: code.start()] + text[code.end():]).strip()
    else:
        for symbol in _CURRENCY_SYMBOLS:  # multi-char symbols listed first
            if symbol in text:
                currency = _CURRENCY_SYMBOLS[symbol]
                text = text.replace(symbol, " ").strip()
                break

    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    raw = m.group(0)
    if raw.startswith("-"):
        negative = True
        raw = raw[1:]
    amount = _parse_amount(raw)
    if amount is None:
        return None
    if negative:
        amount = -amount
    return amount, currency


# ---------------------------------------------------------------------------
# Number and boolean parsing
# ---------------------------------------------------------------------------


def parse_number(value: Any) -> Optional[float]:
    """Parse a float from a number or a numeric string.

    Tolerates thousands separators and a trailing ``%`` (the percent sign is
    stripped, the magnitude is kept: ``"12%"`` parses as ``12.0``).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    if not text:
        return None
    negative = False
    if text.startswith(("-", "+")):
        negative = text[0] == "-"
        text = text[1:].strip()
    if not re.fullmatch(r"\d[\d.,]*(?:[eE][+-]?\d+)?", text):
        return None
    if "e" in text.casefold():
        try:
            return -float(text) if negative else float(text)
        except ValueError:
            return None
    amount = _parse_amount(text)
    if amount is None:
        return None
    result = float(amount)
    return -result if negative else result


_TRUE_WORDS = frozenset({"true", "yes", "y", "t", "1"})
_FALSE_WORDS = frozenset({"false", "no", "n", "f", "0"})


def parse_bool(value: Any) -> Optional[bool]:
    """Parse a boolean from bools, 0/1 integers, and yes/no-style strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value) if value in (0, 1) else None
    if isinstance(value, str):
        word = normalize_text(value)
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    return None


# ---------------------------------------------------------------------------
# Person-name normalization
# ---------------------------------------------------------------------------

_HONORIFICS = frozenset({
    "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "professor", "sir",
    "dame", "madam", "rev", "hon", "capt", "lt", "sgt",
})
_SUFFIXES = frozenset({
    "jr", "sr", "ii", "iii", "iv", "v", "phd", "md", "esq", "dds", "cpa",
})


def name_tokens(value: Any) -> List[str]:
    """Split a person name into normalized, order-insensitive tokens.

    Strips accents, honorifics, and generational/degree suffixes; treats
    ``"Last, First"`` as a reordering, not different content; splits
    hyphenated surnames so ``"Smith-Jones"`` matches ``"Smith Jones"``.
    """
    if not isinstance(value, str):
        return []
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    # "Last, First [Middle]" — a comma flips the halves unless what follows
    # the comma is only a suffix ("John Smith, Jr.").
    if text.count(",") == 1:
        head, tail = (part.strip() for part in text.split(","))
        tail_words = {w.strip(".") for w in tail.split()}
        if tail_words and not tail_words <= _SUFFIXES:
            text = tail + " " + head
    text = re.sub(r"[.\-,'’]", " ", text)
    tokens = [t for t in text.split() if t]
    return [t for t in tokens if t not in _HONORIFICS and t not in _SUFFIXES]


def _pair_name_tokens(left: List[str], right: List[str]) -> bool:
    """True when every token on both sides pairs up (exact or via initial)."""
    left, right = list(left), list(right)
    # Pass 1: exact token matches.
    for token in list(left):
        if token in right:
            left.remove(token)
            right.remove(token)
    # Pass 2: an initial matches a full token starting with the same letter.
    for token in list(left):
        if len(token) != 1:
            continue
        full = next((r for r in right if r.startswith(token)), None)
        if full is not None:
            left.remove(token)
            right.remove(full)
    for token in list(right):
        if len(token) != 1:
            continue
        full = next((l for l in left if l.startswith(token)), None)
        if full is not None:
            right.remove(token)
            left.remove(full)
    return not left and not right


def names_match(gold: Any, pred: Any, subset_ok: bool = False) -> bool:
    """Compare two person names order-insensitively with initial support.

    With ``subset_ok`` the shorter name may omit tokens (middle names), as
    long as every token it *does* have pairs with the longer name.
    """
    gtokens, ptokens = name_tokens(gold), name_tokens(pred)
    if not gtokens or not ptokens:
        return normalize_text(gold) == normalize_text(pred)
    if _pair_name_tokens(gtokens, ptokens):
        return True
    if subset_ok:
        short, long_ = sorted((gtokens, ptokens), key=len)
        remaining = list(long_)
        for token in short:
            candidate = next(
                (r for r in remaining
                 if r == token
                 or (len(token) == 1 and r.startswith(token))
                 or (len(r) == 1 and token.startswith(r))),
                None,
            )
            if candidate is None:
                return False
            remaining.remove(candidate)
        return True
    return False


# ---------------------------------------------------------------------------
# Comparator objects
# ---------------------------------------------------------------------------


class Comparator:
    """Base comparator: normalized string equality."""

    type_name = "string"

    def match(self, gold: Any, pred: Any) -> bool:
        return normalize_text(gold) == normalize_text(pred)


class StringComparator(Comparator):
    """String comparison in one of four modes.

    ``exact`` is byte-for-byte; ``casefold`` ignores case only;
    ``normalized`` (default) also collapses whitespace and width variants;
    ``fuzzy`` accepts a similarity ratio at or above ``threshold``.
    """

    MODES = ("exact", "casefold", "normalized", "fuzzy")

    def __init__(self, mode: str = "normalized", threshold: float = 0.9):
        if mode not in self.MODES:
            raise ConfigError(
                f"unknown string mode {mode!r}; expected one of {', '.join(self.MODES)}"
            )
        if not 0.0 < threshold <= 1.0:
            raise ConfigError("string threshold must be in (0, 1]")
        self.mode = mode
        self.threshold = threshold

    def match(self, gold: Any, pred: Any) -> bool:
        if self.mode == "exact":
            return _stringify(gold) == _stringify(pred)
        if self.mode == "casefold":
            return _stringify(gold).casefold() == _stringify(pred).casefold()
        if self.mode == "fuzzy":
            return similarity(_stringify(gold), _stringify(pred)) >= self.threshold
        return normalize_text(gold) == normalize_text(pred)


class DateComparator(Comparator):
    """Calendar-date equality across formats; time components are ignored."""

    type_name = "date"

    def __init__(self, dayfirst: bool = False):
        self.dayfirst = dayfirst

    def match(self, gold: Any, pred: Any) -> bool:
        gdate = parse_date(gold, dayfirst=self.dayfirst)
        pdate = parse_date(pred, dayfirst=self.dayfirst)
        if gdate is None and pdate is None:
            return normalize_text(gold) == normalize_text(pred)
        if gdate is None or pdate is None:
            return False
        return gdate == pdate


class MoneyComparator(Comparator):
    """Amount equality within ``tolerance``; currency must agree when known.

    Currency is compared only when both sides carry one, unless
    ``require_currency`` forces both sides to name it explicitly.
    """

    type_name = "money"

    def __init__(self, tolerance: float = 0.0, require_currency: bool = False):
        if tolerance < 0:
            raise ConfigError("money tolerance must be >= 0")
        self.tolerance = Decimal(str(tolerance))
        self.require_currency = require_currency

    def match(self, gold: Any, pred: Any) -> bool:
        gmoney, pmoney = parse_money(gold), parse_money(pred)
        if gmoney is None and pmoney is None:
            return normalize_text(gold) == normalize_text(pred)
        if gmoney is None or pmoney is None:
            return False
        (gamount, gcur), (pamount, pcur) = gmoney, pmoney
        if self.require_currency and (gcur is None or pcur is None):
            return False
        if gcur is not None and pcur is not None and gcur != pcur:
            return False
        return abs(gamount - pamount) <= self.tolerance


class NumberComparator(Comparator):
    """Numeric closeness via ``math.isclose`` with configurable tolerances."""

    type_name = "number"

    def __init__(self, abs_tol: float = 0.0, rel_tol: float = 1e-9):
        if abs_tol < 0 or rel_tol < 0:
            raise ConfigError("number tolerances must be >= 0")
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol

    def match(self, gold: Any, pred: Any) -> bool:
        gnum, pnum = parse_number(gold), parse_number(pred)
        if gnum is None and pnum is None:
            return normalize_text(gold) == normalize_text(pred)
        if gnum is None or pnum is None:
            return False
        return math.isclose(gnum, pnum, rel_tol=self.rel_tol, abs_tol=self.abs_tol)


class BoolComparator(Comparator):
    """Boolean equality across ``true``/``yes``/``1`` spellings."""

    type_name = "bool"

    def match(self, gold: Any, pred: Any) -> bool:
        gbool, pbool = parse_bool(gold), parse_bool(pred)
        if gbool is None or pbool is None:
            return False
        return gbool == pbool


class NameComparator(Comparator):
    """Person-name equality: order, case, accents, initials, honorifics."""

    type_name = "name"

    def __init__(self, subset_ok: bool = False):
        self.subset_ok = subset_ok

    def match(self, gold: Any, pred: Any) -> bool:
        return names_match(gold, pred, subset_ok=self.subset_ok)


class AutoComparator(Comparator):
    """Infer the comparison per value pair.

    Tried in order: bool, date, money, number; each applies only when *both*
    sides parse as that type. Falls back to normalized string equality. This
    is the default for fields without an explicit spec.
    """

    type_name = "auto"

    def __init__(self, dayfirst: bool = False):
        self.dayfirst = dayfirst

    def match(self, gold: Any, pred: Any) -> bool:
        gbool, pbool = parse_bool(gold), parse_bool(pred)
        if gbool is not None and pbool is not None:
            return gbool == pbool
        gdate = parse_date(gold, dayfirst=self.dayfirst)
        pdate = parse_date(pred, dayfirst=self.dayfirst)
        if gdate is not None and pdate is not None:
            return gdate == pdate
        gmoney, pmoney = parse_money(gold), parse_money(pred)
        if gmoney is not None and pmoney is not None:
            (gamount, gcur), (pamount, pcur) = gmoney, pmoney
            if gcur is not None and pcur is not None and gcur != pcur:
                return False
            return gamount == pamount
        return normalize_text(gold) == normalize_text(pred)
