"""`X | None` is the same argument as `Optional[X]`, and a driver asking for a tuple gets one."""
import inspect
import json
import sys
from enum import Enum
from typing import Dict, Literal, Optional, Tuple

import pytest
from werkzeug.datastructures import MultiDict
from wtforms import FloatField, IntegerField

from ivoryos.forms.dynamic_forms import (
    FlexibleEnumField, FlexibleLiteralField, VariableOrFloatField, create_form_for_method, is_list_type,
    parse_annotation,
)
from ivoryos.parsers.structured_types import is_tuple_annotation, to_containers, to_tuple
from ivoryos.parsers.type_conversions import _convert_by_class, convert_config_type
from ivoryos.runtime.task_runner import TaskRunner
from ivoryos.script import Script, ScriptRenderer
from tests.unit.test_runner_missing_method import _execute, _step

pep604 = pytest.mark.skipif(sys.version_info < (3, 10), reason="X | None needs Python 3.10")


class Mode(Enum):
    SLOW = 1
    FAST = 2


def _form(annotation, data, default=inspect.Parameter.empty, design=False, script=None):
    signature = inspect.Signature([inspect.Parameter(
        "value", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation, default=default)])
    form_class = create_form_for_method(signature, autofill=False, script=script, design=design)
    return form_class(formdata=MultiDict(data))


# --- X | None -------------------------------------------------------------------------------

@pep604
def test_x_or_none_parses_like_optional():
    assert parse_annotation(float | None) == ([float], True)
    assert parse_annotation(int | None) == ([int], True)
    assert is_list_type(list[int] | None)


@pep604
@pytest.mark.parametrize("annotation, field_class", [
    (lambda: float | None, FloatField),
    (lambda: int | None, IntegerField),
    (lambda: Mode | None, FlexibleEnumField),
    (lambda: Literal["low", "high"] | None, FlexibleLiteralField),
])
def test_x_or_none_gets_the_field_of_its_type(app, annotation, field_class):
    with app.test_request_context("/", method="POST"):
        assert isinstance(_form(annotation(), {"value": ""}).value, field_class)


@pep604
def test_x_or_none_gets_the_design_field_of_its_type(app):
    with app.test_request_context("/", method="POST"):
        form = _form(float | None, {"value": "1.5"}, design=True, script=Script(author="tester"))
        assert isinstance(form.value, VariableOrFloatField)
        assert form.validate() and form.value.data == 1.5


@pep604
def test_x_or_none_left_blank_is_none_and_a_bad_value_is_refused(app):
    with app.test_request_context("/", method="POST"):
        blank = _form(float | None, {"value": ""})
        assert blank.validate() and blank.value.data is None
        assert not _form(float | None, {"value": "x"}).validate()


@pep604
def test_a_new_device_argument_of_x_or_none_is_converted():
    assert _convert_by_class("1.5", float | None) == 1.5
    with pytest.raises(TypeError):
        _convert_by_class("x", float | None)


# --- tuples ---------------------------------------------------------------------------------

@pytest.mark.parametrize("annotation", [tuple, Tuple[float, float], Tuple[int, ...], Optional[Tuple[float, float]]])
def test_tuple_annotations_are_recognised(annotation):
    assert is_tuple_annotation(annotation)


@pytest.mark.parametrize("annotation", [list, float, Optional[float], Optional[list], inspect.Parameter.empty])
def test_other_annotations_are_not_tuples(annotation):
    assert not is_tuple_annotation(annotation)


@pytest.mark.parametrize("value, annotation, expected", [
    ([1, 2], Tuple[float, float], (1.0, 2.0)),              # as a saved step holds it
    ((1.0, 2.0), Tuple[float, float], (1.0, 2.0)),
    ("[1, 2]", Tuple[float, float], (1.0, 2.0)),            # text from a form or a cell
    ("(1, 2)", Tuple[float, float], (1.0, 2.0)),
    ("1, 2", Tuple[float, float], (1.0, 2.0)),
    (["1", "2.5"], Tuple[float, float], (1.0, 2.5)),
    ([1, 2.0], Tuple[int, int], (1, 2)),
    (["a", 2], Tuple[str, int], ("a", 2)),
    ("a, b", Tuple[str, str], ("a", "b")),
    (["true", False], Tuple[bool, bool], (True, False)),
    ([1, 2, 3], Tuple[float, ...], (1.0, 2.0, 3.0)),
    (5, Tuple[int, ...], (5,)),
    ([1, "a"], tuple, (1, "a")),                            # nothing to cast by
    ([[1, 2], 3], Tuple[Tuple[float, float], int], ((1.0, 2.0), 3)),
    ([None, 1], Tuple[Optional[float], float], (None, 1.0)),
    (None, Optional[Tuple[float, float]], None),
    ("None", Optional[Tuple[float, float]], None),
    ([1, 2], Optional[Tuple[float, float]], (1.0, 2.0)),
    ("#plate", Tuple[float, float], "#plate"),              # a workflow input, filled in by the run
])
def test_to_tuple(value, annotation, expected):
    result = to_tuple(value, annotation)
    assert result == expected
    assert type(result) is type(expected)
    if isinstance(expected, tuple):
        assert [type(item) for item in result] == [type(item) for item in expected]


@pytest.mark.parametrize("value, annotation", [
    ([1], Tuple[float, float]),             # wrong length
    ([1, 2, 3], Tuple[float, float]),
    ("1, x", Tuple[float, float]),          # an element that cannot be its type
    ([2.5, 1], Tuple[int, int]),            # never truncated
    (["2.5", 1], Tuple[int, int]),
    (["maybe", True], Tuple[bool, bool]),
])
def test_to_tuple_refuses_what_cannot_be_the_type(value, annotation):
    with pytest.raises(ValueError):
        to_tuple(value, annotation)


def test_to_containers_leaves_arguments_that_are_not_containers():
    def move(position: Tuple[float, float], gains: Dict[int, float], speed: float = 1.0, name=None):
        return position

    assert to_containers(move, {"position": [1, 2], "gains": {"1": 2}, "speed": 3, "name": [4]}) == {
        "position": (1.0, 2.0), "gains": {1: 2.0}, "speed": 3, "name": [4]}


def test_the_instruments_page_calls_with_a_tuple():
    def move(position: Tuple[float, float] = (1.0, 2.0)):
        return position

    for sent in ("(1.0, 2.0)", "[1, 2]", "1, 2", [1, 2]):
        converted = TaskRunner._convert_kwargs_type({"position": sent}, move)
        assert converted == {"position": (1.0, 2.0)} and isinstance(converted["position"], tuple)


def test_the_instruments_page_refuses_a_tuple_of_the_wrong_length():
    def move(position: Tuple[float, float]):
        return position

    with pytest.raises(ValueError):
        TaskRunner._convert_kwargs_type({"position": "1, 2, 3"}, move)


def test_a_run_calls_the_driver_with_a_tuple(app, init_database, test_deck):
    received = []

    def move(position: Tuple[float, float] = (1.0, 2.0)):
        received.append(position)

    test_deck.move = move

    # a saved workflow is JSON, which turns the tuple into a list
    saved = json.loads(json.dumps({"position": (1, 2)}))
    _, row = _execute(app, _step("move", saved, {"position": "tuple"}))

    assert row.run_error is False
    assert received == [(1.0, 2.0)] and isinstance(received[0], tuple)


@pytest.mark.parametrize("recorded", ["tuple", ["Tuple", "NoneType"], ["tuple", "NoneType"]])
def test_a_config_cell_may_hold_a_tuple(recorded):
    assert convert_config_type({"position": "(1, 2)"}, {"position": recorded}) == {"position": (1, 2)}


def test_exported_code_writes_a_saved_tuple_as_a_tuple():
    renderer = ScriptRenderer(Script(author="tester"))
    assert renderer._process_dict_args({"position": [1.0, 2.0]}, {"position": "tuple"}) == "{'position': (1.0, 2.0)}"
    assert renderer._process_dict_args(
        {"position": [1.0, 2.0]}, {"position": ["Tuple", "NoneType"]}) == "{'position': (1.0, 2.0)}"
    # a list stays a list
    assert renderer._process_dict_args({"position": [1.0, 2.0]}, {"position": "list"}) == "{'position': [1.0, 2.0]}"
