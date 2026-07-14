"""The CLI end to end, in process: exit codes, formats, and errors.

Calling ``fieldscore.cli.main`` directly keeps these tests fast and free of
subprocess flakiness while still covering the argparse wiring the console
script uses. (scripts/smoke.sh covers the real ``python -m`` entry point.)
"""

import json

import pytest

import fieldscore
from fieldscore.cli import main


@pytest.fixture()
def dataset(tmp_path):
    gold = tmp_path / "gold.jsonl"
    pred = tmp_path / "pred.jsonl"
    gold.write_text(
        '{"id": "a", "date": "2024-03-05", "total": "$10.00"}\n'
        '{"id": "b", "date": "2024-04-01", "total": "$20.00"}\n',
        encoding="utf-8",
    )
    pred.write_text(
        '{"id": "a", "date": "March 5, 2024", "total": "10 USD"}\n'
        '{"id": "b", "date": "2024-04-02", "total": "$20.00"}\n',
        encoding="utf-8",
    )
    return gold, pred


def test_score_table_exits_zero_and_prints_fields(dataset, capsys):
    gold, pred = dataset
    assert main(["score", str(gold), str(pred), "--id-field", "id"]) == 0
    out = capsys.readouterr().out
    assert "date" in out and "total" in out and "micro avg" in out


def test_score_json_format_is_parseable(dataset, capsys):
    gold, pred = dataset
    assert main(["score", str(gold), str(pred), "--id-field", "id",
                 "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # date: 1 of 2 correct (the 04-02 prediction is a genuinely wrong day).
    assert payload["fields"]["date"]["correct"] == 1
    assert payload["fields"]["total"]["correct"] == 2


def test_fail_under_gates_the_exit_code(dataset, capsys):
    gold, pred = dataset
    assert main(["score", str(gold), str(pred), "--id-field", "id",
                 "--fail-under", "0.99"]) == 1
    assert "FAIL" in capsys.readouterr().err
    assert main(["score", str(gold), str(pred), "--id-field", "id",
                 "--fail-under", "0.5"]) == 0


def test_explain_lists_the_wrong_date(dataset, capsys):
    gold, pred = dataset
    assert main(["explain", str(gold), str(pred), "--id-field", "id"]) == 0
    out = capsys.readouterr().out
    assert "record b" in out
    assert "2024-04-01" in out and "2024-04-02" in out


def test_explain_record_filter(dataset, capsys):
    gold, pred = dataset
    assert main(["explain", str(gold), str(pred), "--id-field", "id",
                 "--record", "a"]) == 0
    out = capsys.readouterr().out
    assert "no mismatches" in out  # record a matched entirely


def test_infer_emits_valid_config_json(dataset, capsys):
    gold, _ = dataset
    assert main(["infer", str(gold), "--id-field", "id"]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["fields"]["date"]["type"] == "date"
    assert config["fields"]["total"]["type"] == "money"


def test_config_file_is_honored(dataset, tmp_path, capsys):
    gold, pred = dataset
    config = tmp_path / "fields.json"
    config.write_text(json.dumps({
        "id_field": "id",
        "fields": {"total": {"type": "money", "tolerance": 0.01}},
    }), encoding="utf-8")
    assert main(["score", str(gold), str(pred), "--config", str(config),
                 "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fields"]["total"]["type"] == "money"


def test_bad_config_and_missing_input_exit_two(dataset, tmp_path, capsys):
    gold, pred = dataset
    config = tmp_path / "fields.json"
    config.write_text('{"fields": {"a": {"type": "nope"}}}', encoding="utf-8")
    assert main(["score", str(gold), str(pred), "--config", str(config)]) == 2
    assert "error" in capsys.readouterr().err
    assert main(["score", str(gold), str(tmp_path / "nope.jsonl")]) == 2
    assert "error" in capsys.readouterr().err


def test_no_command_prints_help_and_version_matches_package(capsys):
    assert main([]) == 2
    assert "score" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"fieldscore {fieldscore.__version__}"


def test_dayfirst_flag_changes_ambiguous_dates(tmp_path, capsys):
    gold = tmp_path / "g.jsonl"
    pred = tmp_path / "p.jsonl"
    gold.write_text('{"d": "2024-05-03"}\n', encoding="utf-8")
    pred.write_text('{"d": "03/05/2024"}\n', encoding="utf-8")
    main(["score", str(gold), str(pred), "--dayfirst", "--format", "json"])
    with_flag = json.loads(capsys.readouterr().out)
    main(["score", str(gold), str(pred), "--format", "json"])
    without_flag = json.loads(capsys.readouterr().out)
    assert with_flag["fields"]["d"]["correct"] == 1
    assert without_flag["fields"]["d"]["correct"] == 0


def test_dayfirst_flag_overrides_config_declared_date_fields(tmp_path, capsys):
    # The flag must reach fields the config file explicitly types as "date",
    # not just the default auto comparator — the file was parsed with its
    # own (false) dayfirst before the CLI flag was ever seen.
    gold = tmp_path / "g.jsonl"
    pred = tmp_path / "p.jsonl"
    config = tmp_path / "fields.json"
    gold.write_text('{"d": "2024-05-03"}\n', encoding="utf-8")
    pred.write_text('{"d": "03/05/2024"}\n', encoding="utf-8")
    config.write_text('{"fields": {"d": {"type": "date"}}}', encoding="utf-8")
    main(["score", str(gold), str(pred), "--config", str(config),
          "--dayfirst", "--format", "json"])
    with_flag = json.loads(capsys.readouterr().out)
    assert with_flag["fields"]["d"]["correct"] == 1
