"""The ``fieldscore`` command-line interface.

Three subcommands:

* ``score``   — the main event: per-field precision/recall/F1 between a
  gold file and a predictions file, in table/markdown/csv/json, with an
  optional ``--fail-under`` CI gate on micro-F1.
* ``explain`` — every mismatch, grouped by record, with the comparator type
  that judged it, so "why is recall 0.6?" takes one command.
* ``infer``   — generate a starter config from the gold file's values.

Exit codes: 0 success, 1 score below ``--fail-under``, 2 bad usage or bad
input data. No network is ever touched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import FieldConfig, infer_config, load_config
from .errors import FieldscoreError
from .flatten import flatten
from .loader import load_and_align, load_records
from .report import FORMATS, render, render_explain
from .scoring import score_pairs

EXIT_OK = 0
EXIT_GATE = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fieldscore",
        description=(
            "Per-field precision/recall scoring for JSON extraction tasks "
            "with type-aware fuzzy matching."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"fieldscore {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("gold", type=Path, help="gold (expected) JSON/JSONL file")
        p.add_argument("pred", type=Path, help="predicted JSON/JSONL file")
        p.add_argument("--config", type=Path, default=None,
                       help="field config JSON (types, tolerances, id_field)")
        p.add_argument("--id-field", default=None,
                       help="align records by this field instead of by position")
        p.add_argument("--dayfirst", action="store_true",
                       help="read ambiguous 03/05/2024 dates as day-first")

    p_score = sub.add_parser(
        "score", help="score predictions against gold, field by field")
    add_common(p_score)
    p_score.add_argument("--format", choices=FORMATS, default="table",
                         help="output format (default: table)")
    p_score.add_argument("--fail-under", type=float, default=None,
                         metavar="F1",
                         help="exit 1 if micro-F1 is below this value")

    p_explain = sub.add_parser(
        "explain", help="list every mismatch, grouped by record")
    add_common(p_explain)
    p_explain.add_argument("--record", default=None,
                           help="only show mismatches for this record id")

    p_infer = sub.add_parser(
        "infer", help="generate a starter field config from a gold file")
    p_infer.add_argument("gold", type=Path, help="gold JSON/JSONL file")
    p_infer.add_argument("--id-field", default=None,
                         help="record id field to write into the config")
    return parser


def _resolve_config(args: argparse.Namespace) -> FieldConfig:
    # --dayfirst overrides the file's top-level setting for every date/auto
    # field; passing None leaves the file's own value in force.
    dayfirst = True if getattr(args, "dayfirst", False) else None
    if args.config is not None:
        config = load_config(args.config, dayfirst=dayfirst)
    else:
        config = FieldConfig(dayfirst=bool(dayfirst))
    if getattr(args, "id_field", None):
        config.id_field = args.id_field
    return config


def _cmd_score(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    pairs, _, _ = load_and_align(args.gold, args.pred, id_field=config.id_field)
    report = score_pairs(pairs, config)
    print(render(report, config, args.format))
    if args.fail_under is not None:
        micro_f1 = report.micro.f1
        if micro_f1 < args.fail_under:
            print(
                f"FAIL: micro-F1 {micro_f1:.3f} < required {args.fail_under:.3f}",
                file=sys.stderr,
            )
            return EXIT_GATE
    return EXIT_OK


def _cmd_explain(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    pairs, _, _ = load_and_align(args.gold, args.pred, id_field=config.id_field)
    report = score_pairs(pairs, config)
    mismatches = report.mismatches
    if args.record is not None:
        mismatches = [m for m in mismatches if m.record_id == args.record]
    print(render_explain(mismatches))
    return EXIT_OK


def _cmd_infer(args: argparse.Namespace) -> int:
    import json

    records = load_records(args.gold)
    flats = [flatten(r) for r in records]
    config = infer_config(flats, id_field=args.id_field)
    print(json.dumps(config, indent=2))
    return EXIT_OK


_COMMANDS = {"score": _cmd_score, "explain": _cmd_explain, "infer": _cmd_infer}


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_ERROR
    try:
        return _COMMANDS[args.command](args)
    except FieldscoreError as exc:
        print(f"fieldscore: error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
