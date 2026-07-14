"""Report rendering: table, markdown, csv, json, and explain output."""

import csv
import io
import json

from fieldscore.config import FieldConfig
from fieldscore.loader import AlignedPair
from fieldscore.report import (
    render_csv,
    render_explain,
    render_json,
    render_markdown,
    render_table,
)
from fieldscore.scoring import score_pairs


def make_report():
    pairs = [
        AlignedPair("r1", {"a": "x", "b": "$10"}, {"a": "x", "b": "$11"}),
        AlignedPair("r2", {"a": "y", "b": "$5"}, {"a": "y", "b": "$5"}),
    ]
    return score_pairs(pairs), FieldConfig()


def test_table_contains_fields_averages_and_three_decimal_floats():
    report, config = make_report()
    text = render_table(report, config)
    lines = text.splitlines()
    assert lines[0].startswith("field")
    assert any(line.startswith("a ") for line in lines)
    assert any(line.startswith("micro avg") for line in lines)
    assert any(line.startswith("macro avg") for line in lines)
    assert "records: 2 scored" in text
    assert "0.500" in text  # field b: 1 of 2 correct


def test_markdown_is_a_well_formed_pipe_table():
    report, config = make_report()
    lines = render_markdown(report, config).splitlines()
    assert lines[0].startswith("| field |")
    assert set(lines[1].replace("|", "")) == {"-"}
    # header, separator, 2 fields, micro, macro
    assert len(lines) == 6
    assert "**micro avg**" in lines[-2]


def test_csv_round_trips_through_the_csv_module():
    report, config = make_report()
    rows = list(csv.reader(io.StringIO(render_csv(report, config))))
    assert rows[0][:3] == ["field", "type", "gold"]
    assert rows[-2][0] == "micro avg"
    b_row = next(r for r in rows if r[0] == "b")
    assert b_row[4] == "1"  # correct count


def test_json_carries_raw_counts_and_full_precision():
    report, config = make_report()
    payload = json.loads(render_json(report, config))
    assert payload["fields"]["b"]["correct"] == 1
    assert payload["fields"]["b"]["precision"] == 0.5
    assert payload["micro"]["gold"] == 4
    assert payload["records"]["scored"] == 2
    assert 0 <= payload["macro"]["f1"] <= 1


def test_explain_groups_by_record_and_names_the_comparator():
    report, _ = make_report()
    text = render_explain(report.mismatches)
    assert "record r1" in text
    assert "wrong" in text and "b" in text
    assert "[auto]" in text


def test_explain_with_no_mismatches_says_so():
    pairs = [AlignedPair("r1", {"a": "x"}, {"a": "x"})]
    report = score_pairs(pairs)
    assert "no mismatches" in render_explain(report.mismatches)


def test_explain_truncates_huge_values():
    pairs = [AlignedPair("r1", {"a": "g" * 500}, {"a": "p" * 500})]
    report = score_pairs(pairs)
    text = render_explain(report.mismatches)
    assert "..." in text
    assert len(max(text.splitlines(), key=len)) < 200
