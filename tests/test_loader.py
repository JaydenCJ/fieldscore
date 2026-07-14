"""Loading JSONL / JSON files and aligning gold with predictions."""

import pytest

from fieldscore.errors import AlignmentError, DataError
from fieldscore.loader import align_records, load_records


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_jsonl_loads_records_and_skips_blank_lines(tmp_path):
    path = write(tmp_path, "a.jsonl", '{"a": 1}\n\n{"a": 2}\n')
    assert load_records(path) == [{"a": 1}, {"a": 2}]
    assert load_records(write(tmp_path, "b.jsonl", "\n\n")) == []


def test_json_array_and_single_object_load(tmp_path):
    path = write(tmp_path, "a.json", '[{"a": 1}, {"a": 2}]')
    assert load_records(path) == [{"a": 1}, {"a": 2}]
    path = write(tmp_path, "b.json", '{"a": 1}')
    assert load_records(path) == [{"a": 1}]


def test_bad_input_raises_data_errors_with_context(tmp_path):
    path = write(tmp_path, "a.jsonl", '{"a": 1}\nnot json\n')
    with pytest.raises(DataError) as exc:
        load_records(path)
    assert ":2:" in str(exc.value)  # the offending line number
    with pytest.raises(DataError):
        load_records(write(tmp_path, "b.json", "[1, 2, 3]"))


def test_positional_alignment_pads_length_mismatches():
    pairs = align_records([{"a": 1}, {"a": 2}], [{"a": 1}])
    assert len(pairs) == 2
    assert pairs[1].gold == {"a": 2} and pairs[1].pred is None


def test_id_alignment_joins_out_of_order():
    gold = [{"id": "x", "v": 1}, {"id": "y", "v": 2}]
    pred = [{"id": "y", "v": 2}, {"id": "x", "v": 1}]
    pairs = align_records(gold, pred, id_field="id")
    by_id = {p.record_id: p for p in pairs}
    assert by_id["x"].pred == {"id": "x", "v": 1}
    assert by_id["y"].pred == {"id": "y", "v": 2}


def test_id_alignment_surfaces_missing_and_extra_records():
    gold = [{"id": "x"}, {"id": "y"}]
    pred = [{"id": "y"}, {"id": "z"}]
    pairs = {p.record_id: p for p in align_records(gold, pred, id_field="id")}
    assert pairs["x"].pred is None       # model skipped a document
    assert pairs["z"].gold is None       # model invented a document
    assert pairs["y"].gold is not None and pairs["y"].pred is not None


def test_duplicate_id_is_an_alignment_error():
    with pytest.raises(AlignmentError):
        align_records([{"id": "x"}, {"id": "x"}], [], id_field="id")


def test_record_without_the_id_field_is_an_alignment_error():
    with pytest.raises(AlignmentError):
        align_records([{"a": 1}], [{"a": 1}], id_field="id")
