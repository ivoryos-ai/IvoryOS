"""A list, set or tuple argument means the same on the Instruments page and in a workflow: `List[str]` gets text, a
bare `list` reads each item, brackets follow Python, and a driver asking for a set or a tuple gets one."""
import inspect
import json
from typing import Dict, List, Optional, Set, Tuple

import pytest
from werkzeug.datastructures import MultiDict

from ivoryos.forms.dynamic_forms import CollectionField, create_form_for_method, create_form_from_action
from ivoryos.parsers.structured_types import parse_collection_text, to_containers, to_dict, to_list, to_set
from ivoryos.parsers.type_conversions import convert_config_type
from ivoryos.runtime.safety import check_value
from ivoryos.runtime.task_runner import TaskRunner
from ivoryos.script import Script, ScriptRenderer
from tests.unit.test_runner_missing_method import _execute, _step


def _form(annotation, text, design=False, script=None, default=inspect.Parameter.empty):
    signature = inspect.Signature([inspect.Parameter(
        "value", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation, default=default)])
    form_class = create_form_for_method(signature, autofill=False, script=script, design=design)
    return form_class(formdata=MultiDict({"value": text}))


def _both_paths(annotation, text):
    """What the driver gets from the Instruments page, and from a step saved by the Designer and then run."""
    def method(value):
        return value
    method.__annotations__["value"] = annotation

    results = []
    for design in (False, True):
        form = _form(annotation, text, design=design, script=Script(author="tester") if design else None)
        assert form.validate(), form.errors
        if design:
            saved = json.loads(json.dumps({"value": form.value.data}))
            results.append(to_containers(method, saved)["value"])
        else:
            results.append(TaskRunner._convert_kwargs_type({"value": form.value.data}, method)["value"])
    return results


@pytest.mark.parametrize("text, expected", [
    ("A1, B2", ["A1", "B2"]),
    ("A1", ["A1"]),
    ("1, 2", ["1", "2"]),
    ("1", ["1"]),
    ("A1, 2", ["A1", "2"]),
    ("1, A1", ["1", "A1"]),
    ("1E5", ["1E5"]),                   # not 100000.0
    ("A1, 1E5", ["A1", "1E5"]),
    ("1.50, 2", ["1.50", "2"]),
    ("001, 002", ["001", "002"]),
    ("True, None", ["True", "None"]),
    ("'1', '2'", ["1", "2"]),           # quotes are not part of the text
    ("'a, b', 'c'", ["a, b", "c"]),
    ("it's, ok", ["it's", "ok"]),
    ("a,", ["a", ""]),
    ("['A1', 'B2']", ["A1", "B2"]),
    ("['A1', 2]", ["A1", "2"]),
    ("('A1', 'B2')", ["A1", "B2"]),
])
def test_a_list_of_text_gets_text(app, text, expected):
    with app.test_request_context("/", method="POST"):
        instruments, workflow = _both_paths(List[str], text)
    assert instruments == expected
    assert workflow == expected


@pytest.mark.parametrize("text, expected", [
    ("A1, 2", ["A1", 2]),
    ("1, A1", [1, "A1"]),
    ("1, 2", [1, 2]),
    ("1", [1]),
    ("1.5, a", [1.5, "a"]),
    ("A1, B2", ["A1", "B2"]),
    ("A1, 1E5", ["A1", 100000.0]),
    ("'1', 2", ["1", 2]),               # quotes keep it text
    ("[1, 'a', True]", [1, "a", True]),
    ("1, [2, 3]", [1, [2, 3]]),
])
def test_a_bare_list_reads_each_item(app, text, expected):
    with app.test_request_context("/", method="POST"):
        instruments, workflow = _both_paths(list, text)
    assert instruments == expected
    assert workflow == expected


@pytest.mark.parametrize("annotation, text", [
    (List[str], "[A1, B2]"),
    (list, "[A1, B2]"),
    (List[str], "(A1, B2)"),
    (Set[str], "{A1, B2}"),
    (set, "[A1, B2]"),
    (List[str], "[1, 2"),
    (List[str], '{"a": 1}'),
    (List[int], "a, b"),
    (List[int], "1.5, 2"),
    (List[float], "1.5, a"),
    (Set[int], "a, b"),
])
def test_what_cannot_be_the_type_is_refused_by_the_form(app, annotation, text):
    with app.test_request_context("/", method="POST"):
        for design in (False, True):
            form = _form(annotation, text, design=design, script=Script(author="tester") if design else None)
            assert not form.validate()
            assert "value" in form.errors


def test_the_refusal_says_how_to_write_it():
    with pytest.raises(ValueError, match="needs quotes"):
        parse_collection_text("[A1, B2]")


@pytest.mark.parametrize("text, annotation, expected", [
    ("1.5, 2", List[float], [1.5, 2.0]),
    ("1, 2.0", List[int], [1, 2]),
    ("true, false", List[bool], [True, False]),
])
def test_items_are_cast(text, annotation, expected):
    result = to_list(text, annotation)
    assert result == expected
    assert [type(item) for item in result] == [type(item) for item in expected]


def test_nested_collections_are_cast():
    assert to_list([["1", 2.0]], List[List[int]]) == [[1, 2]]
    assert to_dict({"a": ["x", "x"]}, Dict[str, Set[str]]) == {"a": {"x"}}
    assert to_dict({"a": [1, "2"]}, Dict[str, List[float]]) == {"a": [1.0, 2.0]}


@pytest.mark.parametrize("value, expected", [
    ("#ids", "#ids"),       # filled in by the run
    (None, None),
    ("None", None),
    ("", None),
    ("a, b", ["a", "b"]),
    (["a", 1], ["a", "1"]),
])
def test_optional_list(value, expected):
    assert to_list(value, Optional[List[str]]) == expected


@pytest.mark.parametrize("annotation, text, expected", [
    (Set[str], "a, b, a", {"a", "b"}),
    (Set[str], "1, 2", {"1", "2"}),
    (Set[int], "1, 2", {1, 2}),
    (set, "1, a", {1, "a"}),
    (set, "{1, 2}", {1, 2}),
    (Optional[Set[str]], "a", {"a"}),
])
def test_a_driver_asking_for_a_set_gets_one(app, annotation, text, expected):
    with app.test_request_context("/", method="POST"):
        instruments, workflow = _both_paths(annotation, text)
    assert instruments == expected and type(instruments) is set
    assert workflow == expected and type(workflow) is set


@pytest.mark.parametrize("annotation, text, expected", [
    (Tuple[str, str], "A1, 2", ("A1", "2")),
    (Tuple[str, str], "1E5, 2", ("1E5", "2")),
    (Tuple[str, int], "1E5, 2", ("1E5", 2)),        # text stays as typed, and a number is still a number
    (Tuple[str, float], "A1, 2", ("A1", 2.0)),
    (Tuple[str, ...], "1, 2, 3", ("1", "2", "3")),
    (Tuple[int, ...], "1, 2, 3", (1, 2, 3)),
    (Tuple[float, float], "1, 2", (1.0, 2.0)),
    (Tuple[float, float], "[1, 2]", (1.0, 2.0)),
    (Tuple[float, float], "(1, 2)", (1.0, 2.0)),
    (Tuple[str, str], "['A1', 'B2']", ("A1", "B2")),
    (Tuple[str, str], "('A1', 2)", ("A1", "2")),
    (tuple, "A1, 2", ("A1", 2)),
    (tuple, "1, 2", (1, 2)),
    (tuple, "A1, 1E5", ("A1", 100000.0)),
    (Optional[Tuple[str, int]], "a, 1", ("a", 1)),
])
def test_a_driver_asking_for_a_tuple_gets_one(app, annotation, text, expected):
    with app.test_request_context("/", method="POST"):
        instruments, workflow = _both_paths(annotation, text)
    assert instruments == expected and type(instruments) is tuple
    assert workflow == expected and type(workflow) is tuple


@pytest.mark.parametrize("annotation, text", [
    (Tuple[str, str], "[A1, B2]"),
    (Tuple[str, str], "(A1, B2)"),
    (tuple, "[A1, B2]"),
    (Tuple[float, float], "1, x"),
    (Tuple[float, float], "1, 2, 3"),
    (Tuple[str, str], '{"a": 1}'),
    (Tuple[int, ...], "a, b"),
])
def test_what_cannot_be_the_tuple_is_refused_by_the_form(app, annotation, text):
    with app.test_request_context("/", method="POST"):
        for design in (False, True):
            form = _form(annotation, text, design=design, script=Script(author="tester") if design else None)
            assert not form.validate()
            assert "value" in form.errors


def test_a_tuple_default_can_be_typed_back_in(app):
    with app.test_request_context("/"):
        signature = inspect.Signature([inspect.Parameter(
            "value", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Tuple[float, float], default=(1.0, 2.0))])
        form = create_form_for_method(signature, autofill=False, design=False)()
        assert isinstance(form.value, CollectionField)
        assert form.value._value() == "(1.0, 2.0)"


def test_a_config_cell_holding_a_tuple_follows_the_same_rule():
    assert convert_config_type({"value": "A1, 2"}, {"value": "tuple"}) == {"value": ("A1", 2)}
    with pytest.raises(ValueError):
        convert_config_type({"value": "[A1, B2]"}, {"value": "tuple"})


def test_a_set_cannot_hold_a_list():
    with pytest.raises(ValueError, match="cannot be a set"):
        to_set("[[1], [2]]", set)


def test_a_run_calls_the_driver_with_a_set_and_with_text(app, init_database, test_deck):
    received = []

    def store(tags: Set[str], ids: List[str]):
        received.append((tags, ids))

    test_deck.store = store
    saved = json.loads(json.dumps({"tags": ["a", "a"], "ids": [1, "b"]}))
    _, row = _execute(app, _step("store", saved, {"tags": "set", "ids": "list"}))

    assert row.run_error is False
    assert received == [({"a"}, ["1", "b"])] and type(received[0][0]) is set


def test_a_step_saved_as_text_still_runs():
    def store(ids: Optional[List[str]] = None):
        return ids

    assert to_containers(store, {"ids": "A1, 2"}) == {"ids": ["A1", "2"]}


def test_a_variable_is_kept_for_the_run(app):
    with app.test_request_context("/", method="POST"):
        form = _form(List[str], "#ids", design=True, script=Script(author="tester"))
        assert form.validate()
        assert form.value.data == "#ids"


def test_the_instruments_page_has_no_variables(app):
    with app.test_request_context("/", method="POST"):
        assert not _form(List[str], "#ids").validate()


def test_blank_optional_is_none(app):
    with app.test_request_context("/", method="POST"):
        form = _form(Optional[List[str]], "")
        assert form.validate()
        assert form.value.data is None


def test_a_set_default_can_be_typed_back_in(app):
    with app.test_request_context("/"):
        signature = inspect.Signature([inspect.Parameter(
            "value", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Set[str], default=set())])
        form = create_form_for_method(signature, autofill=False, design=False)()
        assert isinstance(form.value, CollectionField)
        assert form.value._value() == "[]"


def test_editing_a_saved_step_keeps_what_was_saved(app):
    action = {"instrument": "deck.x", "action": "m", "arg_types": {"value": "list"}, "args": {"value": ["A1", "2"]}}
    with app.test_request_context("/", method="POST", data={"value": "['A1', '2']"}):
        form = create_form_from_action(action, script=Script(author="tester"))
        assert isinstance(form.value, CollectionField)
        assert form.value._value() == "['A1', '2']"
        assert form.validate()
        assert form.value.data == ["A1", "2"]


def test_a_config_cell_follows_the_same_rule():
    assert convert_config_type({"value": "A1, 2"}, {"value": "list"}) == {"value": ["A1", 2]}
    assert convert_config_type({"value": "a, b"}, {"value": "set"}) == {"value": {"a", "b"}}
    with pytest.raises(ValueError):
        convert_config_type({"value": "[A1, B2]"}, {"value": "list"})


def test_exported_code_writes_a_saved_set_as_a_set():
    renderer = ScriptRenderer(Script(author="tester"))
    assert renderer._process_dict_args({"tags": ["a", "b"]}, {"tags": "set"}) == "{'tags': {'a', 'b'}}"
    assert renderer._process_dict_args({"tags": ["a"]}, {"tags": ["Set", "NoneType"]}) == "{'tags': {'a'}}"
    assert renderer._process_dict_args({"tags": []}, {"tags": "set"}) == "{'tags': set()}"


def test_limits_look_inside_a_set():
    assert check_value({"max": 5}, {1, 9})
    assert not check_value({"max": 5}, {1, 2})
