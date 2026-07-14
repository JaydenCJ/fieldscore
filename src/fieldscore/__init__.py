"""fieldscore — per-field precision/recall scoring for JSON extraction.

Public API::

    from fieldscore import score_files, score_pairs, FieldConfig

    report = score_files("gold.jsonl", "pred.jsonl", config_path="fields.json")
    print(report.micro.f1)
    for path, counts in report.per_field.items():
        print(path, counts.precision, counts.recall)

Everything runs offline on the standard library; no model, no API, no
telemetry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

__version__ = "0.1.0"

from .comparators import (  # noqa: F401
    AutoComparator,
    BoolComparator,
    Comparator,
    DateComparator,
    MoneyComparator,
    NameComparator,
    NumberComparator,
    StringComparator,
    names_match,
    normalize_text,
    parse_bool,
    parse_date,
    parse_money,
    parse_number,
)
from .config import FieldConfig, build_comparator, load_config, parse_config  # noqa: F401
from .errors import (  # noqa: F401
    AlignmentError,
    ConfigError,
    DataError,
    FieldscoreError,
)
from .flatten import flatten, is_absent  # noqa: F401
from .loader import AlignedPair, align_records, load_records  # noqa: F401
from .scoring import FieldCounts, Mismatch, ScoreReport, Scorer, score_pairs  # noqa: F401


def score_files(
    gold_path: Union[str, Path],
    pred_path: Union[str, Path],
    config_path: Optional[Union[str, Path]] = None,
    id_field: Optional[str] = None,
) -> ScoreReport:
    """Score two files in one call — the library equivalent of the CLI.

    ``id_field`` overrides the config file's own ``id_field`` when given.
    """
    from .loader import load_and_align

    config = load_config(Path(config_path)) if config_path else FieldConfig()
    if id_field is not None:
        config.id_field = id_field
    pairs, _, _ = load_and_align(
        Path(gold_path), Path(pred_path), id_field=config.id_field
    )
    return score_pairs(pairs, config)
