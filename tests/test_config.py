"""Config parsing, validation, and type inference."""

import pytest

from fieldscore.config import build_comparator, infer_config, parse_config
from fieldscore.errors import ConfigError
from fieldscore.flatten import flatten


def test_minimal_config_defaults_to_auto():
    config = parse_config({})
    assert config.type_name_for("anything") == "auto"


def test_field_specs_override_the_default():
    config = parse_config({"fields": {"total": {"type": "money"}}})
    assert config.type_name_for("total") == "money"
    assert config.type_name_for("other") == "auto"


def test_typos_anywhere_in_the_config_fail_loudly():
    # A typo must never silently fall back to exact matching.
    with pytest.raises(ConfigError) as exc:
        parse_config({"fields": {"a": {"type": "datetime"}}})
    assert "datetime" in str(exc.value)
    assert "date" in str(exc.value)  # the message lists the valid types
    with pytest.raises(ConfigError):
        parse_config({"fields": {"a": {"type": "string", "treshold": 0.8}}})
    with pytest.raises(ConfigError):
        parse_config({"felds": {}})


def test_top_level_dayfirst_flows_into_date_comparators():
    config = parse_config({"dayfirst": True, "fields": {"d": {"type": "date"}}})
    assert config.comparator_for("d").match("03/05/2024", "2024-05-03")


def test_build_comparator_passes_options_through():
    comparator = build_comparator({"type": "money", "tolerance": 0.05})
    assert comparator.match("$1.00", "$1.04")


def test_infer_detects_types_and_excludes_the_id_field():
    records = [
        {"id": "r1", "date": "2024-03-05", "total": "$10.00", "qty": 3,
         "paid": True, "note": "hello"},
        {"id": "r2", "date": "2024-04-01", "total": "$99.00", "qty": 1,
         "paid": False, "note": "world"},
    ]
    config = infer_config([flatten(r) for r in records], id_field="id")
    fields = config["fields"]
    assert config["id_field"] == "id"
    assert "id" not in fields
    assert fields["date"]["type"] == "date"
    assert fields["total"]["type"] == "money"
    assert fields["qty"]["type"] == "number"
    assert fields["paid"]["type"] == "bool"
    assert fields["note"]["type"] == "string"


def test_infer_does_not_call_skus_money():
    # "WID-1" contains a digit and three capital letters; the strict
    # inference shape must still classify it as a string.
    records = [{"sku": "WID-1"}, {"sku": "GAD-7"}]
    config = infer_config([flatten(r) for r in records])
    assert config["fields"]["sku"]["type"] == "string"


def test_infer_uses_name_hint_only_for_name_like_keys():
    records = [
        {"contact_name": "Jane Smith", "title": "Annual Report"},
        {"contact_name": "John Doe", "title": "Quarterly Review"},
    ]
    config = infer_config([flatten(r) for r in records])
    assert config["fields"]["contact_name"]["type"] == "name"
    assert config["fields"]["title"]["type"] == "string"


def test_infer_descends_into_object_lists():
    records = [{"items": [{"price": "$5.00", "sku": "A-1"}]}]
    config = infer_config([flatten(r) for r in records])
    assert config["fields"]["items[].price"]["type"] == "money"
