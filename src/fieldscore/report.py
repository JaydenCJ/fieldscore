"""Render a :class:`~fieldscore.scoring.ScoreReport` for humans and machines.

Four formats: an aligned plain-text ``table`` (the default, made for
terminals), ``markdown`` (paste into a PR), ``csv`` (spreadsheets), and
``json`` (dashboards / CI gates). All four contain the same numbers; JSON
additionally carries the raw counts so downstream tooling never has to
re-derive precision from a rounded string.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List

from .config import FieldConfig
from .scoring import Mismatch, ScoreReport

FORMATS = ("table", "markdown", "csv", "json")


def _rows(report: ScoreReport, config: FieldConfig) -> List[Dict[str, Any]]:
    rows = []
    for path in sorted(report.per_field):
        counts = report.per_field[path]
        rows.append({
            "field": path,
            "type": config.type_name_for(path),
            "gold": counts.gold,
            "pred": counts.pred,
            "correct": counts.correct,
            "precision": counts.precision,
            "recall": counts.recall,
            "f1": counts.f1,
        })
    return rows


def _summary_rows(report: ScoreReport) -> List[Dict[str, Any]]:
    micro = report.micro
    return [
        {
            "field": "micro avg", "type": "", "gold": micro.gold,
            "pred": micro.pred, "correct": micro.correct,
            "precision": micro.precision, "recall": micro.recall,
            "f1": micro.f1,
        },
        {
            "field": "macro avg", "type": "", "gold": "", "pred": "",
            "correct": "", "precision": report.macro_precision,
            "recall": report.macro_recall, "f1": report.macro_f1,
        },
    ]


_COLUMNS = ("field", "type", "gold", "pred", "correct",
            "precision", "recall", "f1")
_FLOATS = ("precision", "recall", "f1")


def _fmt(row: Dict[str, Any], column: str) -> str:
    value = row[column]
    if column in _FLOATS and value != "":
        return f"{value:.3f}"
    return str(value)


def render_table(report: ScoreReport, config: FieldConfig) -> str:
    """Aligned plain-text table with a separator before the averages."""
    rows = _rows(report, config)
    summary = _summary_rows(report)
    widths = {
        c: max([len(c)] + [len(_fmt(r, c)) for r in rows + summary])
        for c in _COLUMNS
    }

    def line(row: Dict[str, Any]) -> str:
        cells = []
        for c in _COLUMNS:
            text = _fmt(row, c)
            cells.append(text.ljust(widths[c]) if c in ("field", "type")
                         else text.rjust(widths[c]))
        return "  ".join(cells).rstrip()

    header = "  ".join(
        c.ljust(widths[c]) if c in ("field", "type") else c.rjust(widths[c])
        for c in _COLUMNS
    ).rstrip()
    rule = "-" * len(header)
    out = [header, rule]
    out.extend(line(r) for r in rows)
    out.append(rule)
    out.extend(line(r) for r in summary)
    out.append("")
    out.append(
        f"records: {report.record_count} scored "
        f"({report.gold_records} gold, {report.pred_records} predicted)"
    )
    return "\n".join(out)


def render_markdown(report: ScoreReport, config: FieldConfig) -> str:
    """GitHub-flavored Markdown table (averages in bold)."""
    rows = _rows(report, config)
    out = ["| " + " | ".join(_COLUMNS) + " |",
           "|" + "|".join("---" for _ in _COLUMNS) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_fmt(row, c) for c in _COLUMNS) + " |")
    for row in _summary_rows(report):
        cells = [_fmt(row, c) for c in _COLUMNS]
        cells[0] = f"**{cells[0]}**"
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def render_csv(report: ScoreReport, config: FieldConfig) -> str:
    """RFC-4180 CSV, one row per field plus the two average rows."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_COLUMNS)
    for row in _rows(report, config) + _summary_rows(report):
        writer.writerow(_fmt(row, c) for c in _COLUMNS)
    return buffer.getvalue().rstrip("\n")


def render_json(report: ScoreReport, config: FieldConfig) -> str:
    """Machine-readable report with raw counts and full-precision metrics."""
    micro = report.micro
    payload = {
        "records": {
            "scored": report.record_count,
            "gold": report.gold_records,
            "pred": report.pred_records,
        },
        "fields": {
            path: {
                "type": config.type_name_for(path),
                "gold": c.gold,
                "pred": c.pred,
                "correct": c.correct,
                "precision": c.precision,
                "recall": c.recall,
                "f1": c.f1,
            }
            for path, c in sorted(report.per_field.items())
        },
        "micro": {
            "gold": micro.gold, "pred": micro.pred, "correct": micro.correct,
            "precision": micro.precision, "recall": micro.recall,
            "f1": micro.f1,
        },
        "macro": {
            "precision": report.macro_precision,
            "recall": report.macro_recall,
            "f1": report.macro_f1,
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


RENDERERS = {
    "table": render_table,
    "markdown": render_markdown,
    "csv": render_csv,
    "json": render_json,
}


def render(report: ScoreReport, config: FieldConfig, fmt: str) -> str:
    return RENDERERS[fmt](report, config)


# ---------------------------------------------------------------------------
# `fieldscore explain` — human-readable mismatch listing
# ---------------------------------------------------------------------------

def _preview(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) \
        if isinstance(value, (dict, list)) else str(value)
    return text if len(text) <= 60 else text[:57] + "..."


def render_explain(mismatches: List[Mismatch]) -> str:
    """Group mismatches by record and describe each one on one line."""
    if not mismatches:
        return "no mismatches - every extracted field matched"
    out: List[str] = []
    current: str = ""
    for miss in mismatches:
        if miss.record_id != current:
            if current:
                out.append("")
            out.append(f"record {miss.record_id}")
            current = miss.record_id
        if miss.kind == "wrong":
            detail = f"gold {_preview(miss.gold)} != pred {_preview(miss.pred)}"
        elif miss.kind == "missing":
            detail = f"gold {_preview(miss.gold)} not extracted"
        else:
            detail = f"pred {_preview(miss.pred)} not in gold"
        out.append(f"  {miss.kind:<8} {miss.path}  [{miss.type_name}]  {detail}")
    return "\n".join(out)
