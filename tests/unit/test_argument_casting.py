"""What a driver receives for what a person typed. Nothing typed is evaluated, a value that cannot
be the annotated type is refused rather than truncated or flipped, and text stays as typed."""
import inspect
import json
import sys
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import pytest
from werkzeug.datastructures import MultiDict

from ivoryos.forms.dynamic_forms import create_form_for_method
from ivoryos.parsers.introspection import get_arg_type
from ivoryos.parsers.structured_types import to_bool, to_dict, to_int
from ivoryos.parsers.type_conversions import convert_config_type
from ivoryos.runtime.task_conditions import accepts_none
from ivoryos.runtime.task_runner import TaskRunner
from ivoryos.script import Script, ScriptEditor, ScriptRenderer
from ivoryos.utils.enums import NOT_AN_OPTION, find_option, to_members
from tests.conftest import DummyModule
from tests.unit.test_runner_missing_method import _execute, _step


class Speed(Enum):
    SLOW = 1
    FAST = 3


def _instruments(function, value):
    """What the Instruments page calls a method with for a value sent to it."""
    return TaskRunner._convert_kwargs_type({"value": value}, function)["value"]


def _cell(text, recorded):
    return convert_config_type({"value": text}, {"value": recorded})["value"]


# --- nothing is evaluated -------------------------------------------------------------------

def test_a_config_cell_is_never_evaluated():
    ran = []
    sys.modules["__casting_marker"] = ran
    try:
        with pytest.raises(TypeError):
            _cell('0") or __import__("sys").modules["__casting_marker"].append(1) or int("1', "int")
    finally:
        del sys.modules["__casting_marker"]
    assert ran == []


def test_a_recorded_type_is_never_evaluated():
    ran = []
    sys.modules["__casting_marker"] = ran
    try:
        with pytest.raises(TypeError):
            _cell("x", '__import__("sys").modules["__casting_marker"].append')
    finally:
        del sys.modules["__casting_marker"]
    assert ran == []


# --- bool -----------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["True", "true", "TRUE", "t", "yes", "Y", "1", True])
def test_what_reads_as_true(text):
    assert to_bool(text) is True


@pytest.mark.parametrize("text", ["False", "false", "FALSE", "f", "no", "N", "0", "", False])
def test_what_reads_as_false(text):
    assert to_bool(text) is False


@pytest.mark.parametrize("text", ["maybe", "2", "on?", "None"])
def test_a_bool_refuses_anything_else(text):
    with pytest.raises(ValueError):
        to_bool(text)


@pytest.mark.parametrize("text, expected", [("FALSE", False), ("false", False), ("no", False), ("0", False),
                                            ("TRUE", True), ("true", True), ("yes", True), ("1", True)])
def test_a_spreadsheet_bool_is_what_it_says(text, expected):
    assert _cell(text, "bool") is expected
    assert _cell(text, ["bool", "NoneType"]) is expected


def test_a_spreadsheet_bool_refuses_anything_else():
    with pytest.raises(TypeError):
        _cell("maybe", "bool")


def _design_form(app, value):
    def toggle(value: bool):
        pass

    with app.test_request_context("/", method="POST", data=MultiDict({"value": value})):
        script = Script(author="tester")
        form = create_form_for_method(inspect.signature(toggle), autofill=False, script=script, design=True)()
        return form.validate(), form.value.data


@pytest.mark.parametrize("text, expected", [("FALSE", False), ("no", False), ("0", False), ("", False),
                                            ("False", False), ("TRUE", True), ("true", True)])
def test_a_designer_bool_is_what_it_says(app, text, expected):
    assert _design_form(app, text) == (True, expected)


def test_a_designer_bool_refuses_anything_else(app):
    valid, _ = _design_form(app, "maybe")
    assert valid is False


def test_a_designer_bool_may_be_a_variable(app):
    assert _design_form(app, "#ready") == (True, "#ready")


@pytest.mark.parametrize("posted, expected", [({"value": "False"}, False), ({"value": "y"}, True), ({}, False)])
def test_the_instruments_checkbox_reads_a_posted_false(app, posted, expected):
    # requests.post(url, data={"value": False}) sends the text False; a ticked box sends y
    def toggle(value: bool):
        pass

    with app.test_request_context("/", method="POST", data=MultiDict(posted)):
        form = create_form_for_method(inspect.signature(toggle), autofill=False, design=False)()
        assert form.value.type == "BooleanField"
        assert (form.validate(), form.value.data) == (True, expected)


def test_the_instruments_page_reads_a_json_bool():
    def toggle(value: bool):
        pass

    assert _instruments(toggle, "false") is False
    assert _instruments(toggle, False) is False
    assert _instruments(toggle, "TRUE") is True
    with pytest.raises(ValueError):
        _instruments(toggle, "maybe")


# --- numbers --------------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [("3", 3), (3, 3), (3.0, 3), ("3.0", 3), ("1e3", 1000), (" 3 ", 3)])
def test_a_whole_number_is_an_int(value, expected):
    result = to_int(value)
    assert result == expected and type(result) is int


@pytest.mark.parametrize("value", [2.5, "2.5", "x", "", float("inf")])
def test_an_int_is_never_truncated(value):
    with pytest.raises(ValueError):
        to_int(value)


@pytest.mark.parametrize("recorded", ["int", ["int", "NoneType"]])
def test_a_spreadsheet_int_is_never_truncated(recorded):
    assert _cell("3", recorded) == 3
    with pytest.raises(TypeError):
        _cell("2.5", recorded)


def test_the_instruments_page_refuses_what_is_not_the_type():
    def take_int(value: int):
        pass

    def take_float(value: float):
        pass

    assert _instruments(take_int, "3") == 3
    assert _instruments(take_float, "2") == 2.0
    for function, value in [(take_int, 2.5), (take_int, "2.5"), (take_int, "x"), (take_float, "x")]:
        with pytest.raises(ValueError):
            _instruments(function, value)


def test_an_optional_number_left_blank_is_none():
    def take(value: Optional[int] = None):
        pass

    def take_plain(value: int = None):
        pass

    assert _instruments(take, None) is None
    assert _instruments(take, "None") is None
    assert _instruments(take_plain, None) is None


def test_a_choice_outside_the_annotation_is_refused_by_the_instruments_page():
    def take_enum(value: Speed):
        pass

    def take_literal(value: Literal["fast", "slow"]):
        pass

    for function in (take_enum, take_literal):
        with pytest.raises(ValueError):
            _instruments(function, "warp")


# --- text -----------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["  two spaces  ", "a, b", "1e3", "0x10", "1_000", "'quoted'", "1.5", "True", "[1, 2]",
                                  "007", "{'a': 1}"])
def test_text_stays_as_typed(text):
    def take(value: str):
        pass

    def take_optional(value: Optional[str] = None):
        pass

    assert _instruments(take, text) == text
    assert _instruments(take_optional, text) == text
    assert _cell(text, "str") == text
    assert _cell(text, ["str", "NoneType"]) == text


def test_text_is_kept_where_a_union_does_not_take_what_it_parses_to():
    assert _cell("1.5", ["str", "int"]) == "1.5"
    assert _cell("5", ["str", "int"]) == 5


def test_the_word_none_keeps_its_meaning():
    def take(value: str):
        pass

    def take_optional(value: Optional[str] = None):
        pass

    assert _instruments(take, "None") == "None"
    assert _instruments(take_optional, "None") is None
    # an untouched `str = None` on the Instruments page: known, and left as it is
    assert _instruments(take, None) == "None"


@pytest.mark.parametrize("text", ["'quoted'", "1.5", "True", "a, b"])
def test_a_designer_step_keeps_text_as_typed(text):
    editor = ScriptEditor(Script(author="tester"))
    assert editor.validate_variables({"value": text}, {"value": "str"}) == {"value": text}


def test_an_untyped_parameter_is_still_guessed():
    def take(value):
        pass

    assert _instruments(take, "1.5") == 1.5
    assert _instruments(take, "True") is True
    assert _instruments(take, "a, b") == ["a", "b"]
    assert _cell("1.5", "any") == 1.5
    assert _cell("a, b", "any") == "a, b"


# --- Literal --------------------------------------------------------------------------------

@pytest.mark.parametrize("key, options, expected", [
    ("1.0", (0.5, 1.0, 2.0), 1.0),         # the text a form and a saved step hold
    (1.0, (0.5, 1.0, 2.0), 1.0),
    (1, (0.5, 1.0, 2.0), 1.0),             # what JSON made of 1.0
    ("4", (1, 2, 4, 8), 4),
    ("False", (True, False), False),
    (False, (True, False), False),
    ("a,b", ("a,b", "c"), "a,b"),
    ("slow", ("fast", "slow"), "slow"),
    (1, (True, 1), 1),                     # 1 is not the option True
    ("x", (1, 2), NOT_AN_OPTION),
    (True, (1, 2), NOT_AN_OPTION),
])
def test_an_option_is_found_by_itself_or_its_text(key, options, expected):
    result = find_option(options, key)
    assert result is expected or (result == expected and type(result) is type(expected))


def test_the_driver_gets_the_option():
    def take(flag: Literal[True, False], count: Literal[1, 2, 4, 8], gain: Optional[Literal[0.5, 1.0]] = None):
        pass

    converted = to_members(take, {"flag": "False", "count": "4", "gain": "1.0"})
    assert converted == {"flag": False, "count": 4, "gain": 1.0}
    assert converted["flag"] is False and type(converted["count"]) is int and type(converted["gain"]) is float
    # what names no option is passed as it is, as for an Enum, and None for an untouched Optional
    assert to_members(take, {"count": "3", "gain": None}) == {"count": "3", "gain": None}


def test_the_instruments_page_calls_with_the_option():
    def take(value: Literal[1, 2, 4, 8]):
        pass

    def take_comma(value: Literal["a,b", "c"]):
        pass

    def take_optional(value: Optional[Literal["a", "b"]] = None):
        pass

    assert _instruments(take, "4") == 4 and type(_instruments(take, "4")) is int
    assert _instruments(take_comma, "a,b") == "a,b"
    assert _instruments(take_optional, None) is None


def test_a_literal_field_takes_a_json_body_without_failing(app):
    def take(value: Literal[1, 2, 4]):
        pass

    # Flask-WTF hands a JSON body to every form on the page, whatever its fields are
    for sent, valid, data in [(4, True, "4"), (3, False, None), (2.5, False, None)]:
        with app.test_request_context("/", method="POST", json={"value": sent}):
            form = create_form_for_method(inspect.signature(take), autofill=False, design=False)()
            assert form.validate() is valid
            assert form.value.data == data


def test_a_run_calls_the_driver_with_the_option(app, init_database, test_deck):
    received = []

    def take(flag: Literal[True, False], count: Literal[1, 2, 4, 8]):
        received.append((flag, count))

    test_deck.take = take

    # a workflow saved before this holds the same text, so it needs no migration
    _, row = _execute(app, _step("take", {"flag": "False", "count": "4"},
                                 {"flag": "Literal:True,False", "count": "Literal:1,2,4,8"}))

    assert row.run_error is False
    assert received == [(False, 4)]
    assert received[0][0] is False


def test_exported_code_writes_the_option():
    renderer = ScriptRenderer(Script(author="tester"))
    arg_types = {"flag": "Literal:True,False", "count": ["Literal:1,2,4,8", "NoneType"], "mode": "Literal:fast,slow"}
    assert renderer._process_dict_args({"flag": "False", "count": "4", "mode": "fast"}, arg_types) == (
        "{'flag': False, 'count': 4, 'mode': 'fast'}")
    assert ScriptRenderer._literal_annotation("Literal:True,False") == "Literal[True, False]"
    assert ScriptRenderer._literal_annotation("Literal:a,-1,1.5") == "Literal['a', -1, 1.5]"


# --- dicts ------------------------------------------------------------------------------------

@pytest.mark.parametrize("value, annotation, expected", [
    ({"a": 1}, Dict[str, float], {"a": 1.0}),                       # typed JSON writes a float as 1 (C1)
    ({"a": "1.5"}, Dict[str, float], {"a": 1.5}),
    ({"1": 10}, Dict[int, float], {1: 10.0}),                       # JSON keys are always text (C2)
    ({1: 10}, Dict[str, int], {"1": 10}),
    ({"x": {"1": "2"}}, Dict[str, Dict[int, float]], {"x": {1: 2.0}}),
    ({"x": ["1", 2]}, Dict[str, List[float]], {"x": [1.0, 2.0]}),
    ({"x": [1, 2]}, Dict[str, Tuple[int, int]], {"x": (1, 2)}),
    ({"a": None, "b": "None"}, Dict[str, Optional[float]], {"a": None, "b": None}),
    ({"k": "#kp"}, Dict[str, float], {"k": "#kp"}),                 # a workflow input, filled in by the run
    ({"a": "x"}, Dict[str, Any], {"a": "x"}),                       # nothing to cast by
    ({"1": 1}, dict, {"1": 1}),
    ('{"1": 1}', Optional[Dict[int, float]], {1: 1.0}),             # text from a config cell
    (None, Optional[Dict[int, float]], None),
])
def test_a_dict_is_cast_by_its_annotation(value, annotation, expected):
    result = to_dict(value, annotation)
    assert result == expected
    if isinstance(expected, dict):
        assert [(type(k), type(v)) for k, v in result.items()] == [(type(k), type(v)) for k, v in expected.items()]


@pytest.mark.parametrize("value, annotation, message", [
    ({"x": 1}, Dict[int, float], "['x']: 'x' is not a number"),
    ({"a": "x"}, Dict[str, float], "['a']: 'x' is not a number"),
    ({"a": 2.5}, Dict[str, int], "['a']: 2.5 is not a whole number"),   # never truncated
    ({"x": {"1": "y"}}, Dict[str, Dict[int, float]], "['x']['1']: 'y' is not a number"),
])
def test_a_dict_key_or_value_that_cannot_be_its_type_is_refused(value, annotation, message):
    with pytest.raises(ValueError) as error:
        to_dict(value, annotation)
    assert str(error.value) == message


def test_a_run_calls_the_driver_with_the_dicts_types(app, init_database, test_deck):
    received = []

    def tune(gains: Dict[int, float]):
        received.append(gains)

    test_deck.tune = tune

    # a step saved as {1: 1.5} is stored as JSON, and comes back as {"1": 1.5}
    _, row = _execute(app, _step("tune", json.loads(json.dumps({"gains": {1: 1.5, 2: 3}})), {"gains": "Dict"}))

    assert row.run_error is False
    assert received == [{1: 1.5, 2: 3.0}] and isinstance(received[0][2], float)


def test_the_instruments_page_casts_a_dict():
    def tune(gains: Dict[int, float]):
        pass

    assert TaskRunner._convert_kwargs_type({"gains": {"1": 2}}, tune) == {"gains": {1: 2.0}}
    with pytest.raises(ValueError):
        TaskRunner._convert_kwargs_type({"gains": {"x": 2}}, tune)


def test_a_designer_step_with_a_dict_key_that_cannot_be_its_type_is_refused(app):
    def tune(gains: Dict[int, float]):
        pass

    for typed, valid in [('{"1": 2}', True), ("{1: 2.5}", True), ('{"x": 2}', False), ('{"1": #kp}', True)]:
        with app.test_request_context("/", method="POST", data=MultiDict({"gains": typed})):
            form = create_form_for_method(inspect.signature(tune), autofill=False, script=Script(author="t"),
                                          design=True)()
            assert form.validate() is valid, typed


def test_exported_code_writes_the_dict_the_driver_gets():
    def tune(gains: Dict[int, float], name: str = "a"):
        pass

    annotations = {name: p.annotation for name, p in inspect.signature(tune).parameters.items()}
    renderer = ScriptRenderer(Script(author="tester"))
    assert renderer._process_dict_args({"gains": {"1": 2}}, {"gains": "Dict"}, annotations) == "{'gains': {1: 2.0}}"
    # with no deck to ask, as saved
    assert renderer._process_dict_args({"gains": {"1": 2}}, {"gains": "Dict"}) == "{'gains': {'1': 2}}"


# --- property setters -----------------------------------------------------------------------

class Stage:
    def __init__(self):
        self.received = None

    @property
    def speed(self) -> Speed:
        return Speed.SLOW

    @speed.setter
    def speed(self, value: Speed):
        self.received = value

    @property
    def unannotated(self) -> Speed:
        return Speed.SLOW

    @unannotated.setter
    def unannotated(self, value):
        self.received = value

    @property
    def level(self) -> Literal[1, 2]:
        return 1

    @level.setter
    def level(self, value: Literal[1, 2]):
        self.received = value

    @property
    def position(self) -> Tuple[float, float]:
        return (0.0, 0.0)

    @position.setter
    def position(self, value: Tuple[float, float]):
        self.received = value

    @property
    def label(self) -> str:
        return ""

    @label.setter
    def label(self, value: str):
        self.received = value


@pytest.mark.parametrize("prop, stored, expected", [
    ("speed", "FAST", Speed.FAST),
    ("speed", 3, Speed.FAST),
    ("unannotated", "FAST", Speed.FAST),       # the Designer's form is built from the getter
    ("level", "2", 2),
    ("position", [1, 2], (1.0, 2.0)),
    ("label", "plain", "plain"),
])
def test_a_run_calls_a_setter_with_the_choice(app, init_database, test_deck, monkeypatch, prop, stored, expected):
    received = []
    getter = getattr(Stage, prop)
    monkeypatch.setattr(DummyModule, prop, property(getter.fget, lambda self, value: received.append(value),
                                                    getter.fget.__doc__), raising=False)
    # the fake setter above has no annotation, so this also goes through the getter's
    _, row = _execute(app, _step(f"{prop}_(setter)", {"value": stored}))

    assert row.run_error is False
    assert received == [expected]
    assert type(received[0]) is type(expected)


class _Deck:
    def __init__(self, stage):
        self.stage = stage


@pytest.mark.parametrize("prop, sent, expected", [
    ("speed", "FAST", Speed.FAST),
    ("unannotated", "FAST", Speed.FAST),
    ("level", "2", 2),
    ("position", "1, 2", (1.0, 2.0)),
])
def test_the_instruments_page_calls_a_setter_with_the_choice(prop, sent, expected):
    stage = Stage()
    setter = TaskRunner()._get_executable("deck.stage", _Deck(stage), f"{prop}_(setter)")
    kwargs = TaskRunner._convert_kwargs_type({"value": sent}, setter)
    setter(**kwargs)
    assert stage.received == expected


def test_exported_code_writes_a_setters_member():
    renderer = ScriptRenderer(Script(author="tester"))
    arg_types = {"value": f"Enum:{__name__}.Speed"}
    assert renderer._arg_source("value", "FAST", arg_types) == "Speed.FAST"
    assert renderer._arg_source("value", "#speed", arg_types) == "speed"
    assert renderer._arg_source("value", "plain", {"value": "str"}) == "'plain'"


# --- Python versions ------------------------------------------------------------------------

def _recorded(annotation):
    signature = inspect.Signature([inspect.Parameter(
        "value", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation)])
    return get_arg_type(["value"], {"signature": signature})["value"]


@pytest.mark.parametrize("annotation, recorded", [
    (Optional[float], ["float", "NoneType"]),
    (Union[int, float], ["int", "float"]),
    (Optional[Speed], [f"Enum:{__name__}.Speed", "NoneType"]),
    (Optional[List[int]], ["List", "NoneType"]),
    (Optional[Tuple[float, float]], ["Tuple", "NoneType"]),
    (List[int], "list"),
    (Tuple[float, float], "tuple"),
    (float, "float"),
])
def test_a_type_is_recorded_the_same_on_every_python(annotation, recorded):
    assert _recorded(annotation) == recorded


@pytest.mark.skipif(sys.version_info < (3, 10), reason="X | None needs Python 3.10")
def test_x_or_none_is_recorded_as_optional():
    assert _recorded(float | None) == ["float", "NoneType"]
    assert _recorded(int | float) == ["int", "float"]


def test_a_recorded_optional_runs_from_a_config_cell_on_every_python():
    recorded = _recorded(Optional[float])
    assert accepts_none(recorded)
    assert _cell("2.5", recorded) == 2.5
    assert json.loads(json.dumps(recorded)) == recorded
