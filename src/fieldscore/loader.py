"""Load gold/predicted records and align them into scoring pairs.

Input files may be JSONL (one object per line — the common shape for
extraction eval sets), a JSON array of objects, or a single JSON object.
Alignment is either positional (line *i* of gold vs line *i* of pred) or —
far safer — by a shared ``id_field`` value, in which case missing and extra
records are scored honestly instead of shifting every later pair.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import AlignmentError, DataError

Record = Dict[str, Any]


def load_records(path: Path) -> List[Record]:
    """Read a JSONL / JSON-array / single-object file into a record list."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataError(f"cannot read {path}: {exc}") from exc
    stripped = text.strip()
    if not stripped:
        return []

    # Whole-file JSON first: arrays and single objects.
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return [_require_object(item, path, i) for i, item in enumerate(data)]
    if isinstance(data, dict):
        return [data]

    # JSONL: one JSON object per non-empty line.
    records: List[Record] = []
    for lineno, line in enumerate(stripped.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DataError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        records.append(_require_object(item, path, lineno - 1))
    return records


def _require_object(item: Any, path: Path, index: int) -> Record:
    if not isinstance(item, dict):
        raise DataError(
            f"{path}: record {index} is {type(item).__name__}, expected a JSON object"
        )
    return item


@dataclass
class AlignedPair:
    """One scoring unit: a gold record and its predicted counterpart.

    Either side may be ``None``: a missing prediction scores every gold
    field as a miss; a prediction with no gold record scores every predicted
    field as spurious.
    """

    record_id: str
    gold: Optional[Record]
    pred: Optional[Record]


def align_records(
    gold: List[Record],
    pred: List[Record],
    id_field: Optional[str] = None,
) -> List[AlignedPair]:
    """Pair gold and predicted records for scoring.

    With ``id_field``, records join on that field's value (as a string);
    duplicate ids on either side are an :class:`AlignmentError` because they
    make the join ambiguous. Without it, records pair by position and length
    mismatches become missing/spurious tails.
    """
    if id_field is None:
        pairs: List[AlignedPair] = []
        for i in range(max(len(gold), len(pred))):
            pairs.append(
                AlignedPair(
                    record_id=f"#{i}",
                    gold=gold[i] if i < len(gold) else None,
                    pred=pred[i] if i < len(pred) else None,
                )
            )
        return pairs

    def index_by_id(records: List[Record], side: str) -> Dict[str, Record]:
        indexed: Dict[str, Record] = {}
        for i, record in enumerate(records):
            if id_field not in record:
                raise AlignmentError(
                    f"{side} record {i} has no {id_field!r} field; "
                    "cannot align by id"
                )
            key = str(record[id_field])
            if key in indexed:
                raise AlignmentError(
                    f"duplicate {id_field}={key!r} in {side} records"
                )
            indexed[key] = record
        return indexed

    gold_by_id = index_by_id(gold, "gold")
    pred_by_id = index_by_id(pred, "predicted")
    ids = list(gold_by_id)
    ids.extend(k for k in pred_by_id if k not in gold_by_id)
    return [
        AlignedPair(record_id=key, gold=gold_by_id.get(key), pred=pred_by_id.get(key))
        for key in ids
    ]


def load_and_align(
    gold_path: Path,
    pred_path: Path,
    id_field: Optional[str] = None,
) -> Tuple[List[AlignedPair], int, int]:
    """Convenience wrapper: load both files, align, return pair + counts."""
    gold = load_records(gold_path)
    pred = load_records(pred_path)
    return align_records(gold, pred, id_field=id_field), len(gold), len(pred)
