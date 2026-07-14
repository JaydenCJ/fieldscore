"""Record flattening: nested objects to dot paths, absence semantics."""

from fieldscore.flatten import canonical_path, flatten, is_absent, is_object_list


def test_nested_objects_become_dot_paths():
    record = {"vendor": {"address": {"city": "Springfield"}}, "total": 5}
    assert flatten(record) == {"vendor.address.city": "Springfield", "total": 5}


def test_lists_are_kept_whole_as_leaf_values():
    record = {"tags": ["a", "b"], "items": [{"sku": "X"}]}
    flat = flatten(record)
    assert flat["tags"] == ["a", "b"]
    assert flat["items"] == [{"sku": "X"}]


def test_absent_values_are_dropped():
    # None, "", [], {} all mean "nothing extracted" and must not create
    # a field the prediction is then punished for omitting.
    record = {"a": None, "b": "", "c": [], "d": {}, "e": "   ", "keep": 0}
    assert flatten(record) == {"keep": 0}
    assert is_absent(None) and is_absent("") and is_absent([]) and is_absent({})


def test_zero_and_false_are_present_values():
    # 0 and False are real extractions, not absence.
    assert flatten({"count": 0, "paid": False}) == {"count": 0, "paid": False}
    assert not is_absent(0)
    assert not is_absent(False)


def test_is_object_list_requires_all_dict_elements():
    assert is_object_list([{"a": 1}, {"b": 2}])
    assert not is_object_list([{"a": 1}, "b"])
    assert not is_object_list([])
    assert not is_object_list("not a list")


def test_canonical_path_generalizes_indexes():
    assert canonical_path("items[2].sku") == "items[].sku"
    assert canonical_path("plain.path") == "plain.path"
