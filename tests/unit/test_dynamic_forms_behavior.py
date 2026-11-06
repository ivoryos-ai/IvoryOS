import inspect
import sys
from enum import Enum
from typing import Literal, Optional

import pytest
from werkzeug.datastructures import MultiDict
from wtforms import IntegerField, StringField
from wtforms.validators import ValidationError

from ivoryos.forms.dynamic_forms import (
    BATCH_ACTION_FIELD,
    WORKFLOW_NAME_FIELD,
    DynamicBaseForm,
    FlexibleEnumField,
    FlexibleLiteralField,
    VariableOrBoolField,
    VariableOrFloatField,
    VariableOrIntField,
    VariableOrStringField,
    create_action_button,
    create_add_form,
    create_all_builtin_forms,
    create_form_for_method,
    create_form_from_action,
    create_workflow_forms,
    parse_annotation,
)
from ivoryos.parsers.introspection import get_arg_type
from ivoryos.runtime.state import global_state
from ivoryos.script import Script


class Choice(Enum):
    RED = "red"
    BLUE = "blue"


def typed_method(count: int, amount: float = 1.5, enabled: bool = False, color: Choice = Choice.RED, items: list = None, **extra):
    return count, amount, enabled, color, items, extra


def method_with_batch_action_param(amount: float, batch_action: bool = False):
    return amount, batch_action


def test_parse_annotation_detects_optional_types():
    types, optional = parse_annotation(Optional[int])

    assert types == [int]
    assert optional is True


def test_create_form_for_method_uses_expected_fields_and_metadata(app):
    script = Script(author="tester")

    with app.app_context():
        form_class = create_form_for_method(
            inspect.signature(typed_method),
            autofill=False,
            script=script,
            design=True,
        )
        form = form_class()

    assert isinstance(form.count, VariableOrIntField)
    assert isinstance(form.amount, VariableOrFloatField)
    assert isinstance(form.enabled, VariableOrBoolField)
    assert isinstance(form.color, FlexibleEnumField)
    assert isinstance(form.items, VariableOrStringField)
    assert form.color.choices == ["RED", "BLUE"]
    assert form_class.has_kwargs is True
    assert form_class.arg_types["items"] == "list"


def test_create_form_from_action_preserves_arg_order_and_return_fields(app):
    action = {
        "id": 7,
        "uuid": 99,
        "instrument": "deck.pump",
        "action": "dose",
        "args": {"second": 2, "first": "alpha"},
        "arg_types": {"first": "str", "second": "int"},
        "arg_order": ["second", "first"],
        "return": ["volume", ""],
        "return_format": {"types": ["float", "str"]},
    }

    with app.app_context():
        form = create_form_from_action(action, script=Script(author="tester"), design=True)

    assert list(form._fields.keys())[:2] == ["second", "first"]
    assert form.second.data == 2
    assert form.first.data == "alpha"
    assert form.return_0.data == "volume"
    assert form.return_1.data == ""
    assert form.return_0.render_kw["placeholder"] == "float"


def test_batch_action_parameter_is_not_shadowed_by_batch_toggle(app):
    """
    A method parameter literally named `batch_action` must keep its own field
    instead of being replaced by the "run once per batch" toggle.
    """
    script = Script(author="tester")
    attr = {"signature": inspect.signature(method_with_batch_action_param), "docstring": ""}

    with app.app_context():
        form = create_add_form(attr, "dose", autofill=False, script=script, design=True)()

    assert isinstance(form.batch_action, VariableOrBoolField)
    assert form.batch_action.label.text == "batch_action"
    assert form[BATCH_ACTION_FIELD].label.text == "run once per batch"


def test_edit_form_keeps_batch_action_argument_alongside_toggle(app):
    action = {
        "id": 1,
        "uuid": 1,
        "instrument": "deck.pump",
        "action": "dose",
        "args": {"amount": 1.0, "batch_action": True},
        "arg_types": {"amount": "float", "batch_action": "bool"},
        "arg_order": ["amount", "batch_action"],
        "batch_action": False,
    }

    with app.app_context():
        form = create_form_from_action(action, script=Script(author="tester"), design=True)

    assert form.batch_action.data is True
    assert form[BATCH_ACTION_FIELD].data is False


def test_workflow_variable_named_workflow_name_is_not_shadowed(app, init_database):
    """
    A workflow input variable named `workflow_name` compiles to a parameter of
    that name; it must not collide with the hidden field carrying the workflow
    name, which would otherwise break step dispatch.
    """
    from ivoryos.models import Script as ScriptModel, db

    registered = ScriptModel(author="tester", name="myflow", deck="mydeck", registered=True)
    registered.script_dict["script"] = [
        {"id": 1, "uuid": 1, "instrument": "deck.pump", "action": "dose",
         "args": {"amount": "#workflow_name"}, "arg_types": {"amount": "float"},
         "return": ""},
    ]
    db.session.add(registered)
    db.session.commit()

    draft = Script(author="tester", name="draft", deck="mydeck")
    _functions, forms = create_workflow_forms(draft, design=True)

    form = list(forms.values())[0]
    assert "workflow_name" in form._fields
    assert form._fields["workflow_name"].type != "HiddenField"
    assert form[WORKFLOW_NAME_FIELD].type == "HiddenField"


def test_create_all_builtin_forms_exposes_expected_controls(app):
    script = Script(author="tester")

    with app.app_context():
        forms = create_all_builtin_forms(script)

    assert set(forms) == {"if", "while", "variable", "input", "wait", "repeat", "pause", "math", "comment"}
    assert hasattr(forms["wait"], BATCH_ACTION_FIELD)
    assert hasattr(forms["variable"], "variable_type")
    assert hasattr(forms["input"], "variable_type")
    assert hasattr(forms["math"], "math_variable")


def test_create_action_button_formats_variables_returns_and_missing_outputs():
    script = Script(author="tester")
    script.script_dict["script"] = [
        {
            "id": 1,
            "uuid": 10,
            "instrument": "variable",
            "action": "sample_count",
            "args": {"statement": 3},
            "return": "",
            "arg_types": {"statement": "int"},
        },
        {
            "id": 2,
            "uuid": 11,
            "instrument": "deck.pump",
            "action": "dose",
            "args": {"amount": {"missing_output": "function_output"}},
            "arg_types": {"amount": "float"},
            "arg_order": ["amount"],
            "return": ["measured", ""],
        },
    ]

    buttons = create_action_button(script)

    assert buttons[0]["label"] == "sample_count = 3"
    assert "measured, _ = pump.dose" in buttons[1]["label"]
    assert "amount = missing_output" in buttons[1]["label"]
    assert buttons[1]["style"] == "background-color: khaki"


def _step(step_id, instrument, action, uid, statement=None):
    args = {"statement": statement} if statement is not None else {}
    step = {"id": step_id, "uuid": uid, "instrument": instrument, "action": action, "args": args, "return": ""}
    if statement is not None:
        step["arg_types"] = {"statement": "int" if instrument == "variable" else ""}
    return step


def test_create_action_button_indents_steps_inside_control_blocks():
    script = Script(author="tester")
    script.script_dict["script"] = [
        _step(1, "while", "while", 1, "x < 3"),
        _step(2, "if", "if", 2, "x > 1"),
        _step(3, "variable", "x", 3, 1),
        _step(4, "if", "else", 2),
        _step(5, "repeat", "repeat", 4, 2),
        _step(6, "variable", "y", 5, 2),
        _step(7, "repeat", "endrepeat", 4),
        _step(8, "if", "endif", 2),
        _step(9, "while", "endwhile", 1),
        _step(10, "variable", "z", 6, 3),
    ]

    buttons = create_action_button(script)

    assert [button["depth"] for button in buttons] == [0, 1, 2, 1, 2, 3, 2, 1, 0, 0]
    # only a block's own rows carry its number; the steps inside and after the blocks none
    assert [button["block"] for button in buttons] == [0, 1, None, 1, 2, None, 2, 1, 0, None]


def test_create_action_button_gives_each_block_its_own_number():
    script = Script(author="tester")
    script.script_dict["script"] = [
        _step(1, "while", "while", 1, "x < 3"),
        _step(2, "repeat", "repeat", 2, 2),
        _step(3, "variable", "a", 3, 1),
        _step(4, "repeat", "endrepeat", 2),
        _step(5, "variable", "b", 4, 1),
        _step(6, "while", "endwhile", 1),
        _step(7, "if", "if", 5, "True"),
        _step(8, "variable", "c", 6, 1),
        _step(9, "if", "else", 5),
        _step(10, "if", "endif", 5),
    ]

    buttons = create_action_button(script)

    assert [button["depth"] for button in buttons] == [0, 1, 2, 1, 1, 0, 0, 1, 0, 0]
    # b is back in the while once the repeat inside it ends; the if after it is a new block
    assert [button["block"] for button in buttons] == [0, 1, None, 1, None, 0, 2, None, 2, 2]


def test_create_action_button_depth_never_goes_negative_for_steps_out_of_order():
    script = Script(author="tester")
    script.script_dict["script"] = [
        _step(1, "if", "endif", 1),
        _step(2, "if", "else", 1),
        _step(3, "variable", "x", 2, 1),
        _step(4, "if", "if", 1, "True"),
        _step(5, "variable", "y", 3, 2),
    ]

    buttons = create_action_button(script)

    assert [button["depth"] for button in buttons] == [0, 0, 0, 0, 1]
    assert [button["structure_issue"] for button in buttons] == [
        "This endif comes before its own if.",
        "This else comes before its own if.",
        None,
        "This if has no endif below it.",
        None,
    ]


def test_create_action_button_flags_a_block_closed_while_one_inside_it_is_open():
    script = Script(author="tester")
    script.script_dict["script"] = [
        _step(1, "if", "if", 1, "a"),
        _step(2, "if", "if", 2, "b"),
        _step(3, "if", "else", 1),
        _step(4, "variable", "x", 3, 1),
        _step(5, "if", "endif", 1),
        _step(6, "if", "else", 2),
        _step(7, "if", "endif", 2),
    ]

    buttons = create_action_button(script)

    crossed = "belongs to 'if a' above, but 'if b' inside it has not ended yet."
    assert [button["structure_issue"] for button in buttons] == [
        None, None, f"This else {crossed}", None, f"This endif {crossed}", None, None,
    ]
    # a crossed row is drawn at its own block's depth
    assert [button["depth"] for button in buttons] == [0, 1, 0, 2, 0, 0, 0]


def test_create_action_button_accepts_an_if_without_an_else():
    script = Script(author="tester")
    script.script_dict["script"] = [
        _step(1, "if", "if", 1, "a"),
        _step(2, "variable", "x", 2, 1),
        _step(3, "if", "endif", 1),
    ]

    buttons = create_action_button(script)

    assert [button["depth"] for button in buttons] == [0, 1, 0]
    assert [button["structure_issue"] for button in buttons] == [None, None, None]


def hook_like_param_names(count: int, index: int, filter_count: int, filter_index: int, validate_count: str = ""):
    return count, index, filter_count, filter_index, validate_count


def test_create_form_for_method_allows_hook_like_parameter_names(app):
    """``filter_<field>``/``validate_<field>`` params must not be used as WTForms inline hooks."""
    with app.app_context():
        form_class = create_form_for_method(
            inspect.signature(hook_like_param_names),
            autofill=False,
            design=False,
        )
        form = form_class()

    assert isinstance(form.filter_count, IntegerField)
    assert isinstance(form.validate_count, StringField)
    assert [field.name for field in form] == [
        "count",
        "index",
        "filter_count",
        "filter_index",
        "validate_count",
    ]


def test_hook_like_parameter_names_still_process_and_validate(app):
    data = MultiDict({
        "count": "1",
        "index": "2",
        "filter_count": "3",
        "filter_index": "4",
        "validate_count": "ok",
    })

    with app.test_request_context("/", method="POST", data=data):
        form_class = create_form_for_method(inspect.signature(hook_like_param_names), autofill=False, design=False)
        form = form_class()

        assert form.validate() is True, form.errors
        assert form.filter_count.data == 3
        assert form.filter_index.data == 4

    with app.test_request_context("/", method="POST", data=MultiDict({"count": "1", "index": "2"})):
        form = create_form_for_method(inspect.signature(hook_like_param_names), autofill=False, design=False)()

        assert form.validate() is False
        assert "filter_count" in form.errors


def test_dynamic_base_form_keeps_genuine_inline_hooks(app):
    class HookedForm(DynamicBaseForm):
        amount = IntegerField("amount")
        note = StringField("note")

        def filter_note(self, value):
            return (value or "").strip().upper()

        def validate_amount(self, field):
            if field.data and field.data > 10:
                raise ValidationError("too big")

    with app.test_request_context("/", method="POST", data=MultiDict({"amount": "99", "note": " hi "})):
        form = HookedForm()

        assert form.note.data == "HI"
        assert form.validate() is False
        assert form.errors["amount"] == ["too big"]


def reserved_param_names(volume: float, validate: bool = False, arg_types: str = "a", meta: int = 1):
    return volume, validate, arg_types, meta


def test_parameters_named_after_form_attributes_keep_their_html_name(app):
    """A parameter may share a name with a form attribute; it is bound under a safe name."""
    with app.app_context():
        form = create_form_for_method(inspect.signature(reserved_param_names), autofill=False, design=False)()

    # field.name is what routes and templates use, so it must stay the parameter name
    assert [field.name for field in form] == ["volume", "validate", "arg_types", "meta"]
    # the form's own API is intact
    assert callable(form.validate)
    assert form.arg_types["volume"] == "<class 'float'>"


def test_parameter_named_validate_does_not_disable_validation(app):
    """Regression: a `validate` parameter used to shadow Form.validate and pass any input."""
    bad_input = MultiDict({"volume": "not-a-number", "validate": "y", "arg_types": "a", "meta": "1"})

    with app.test_request_context("/", method="POST", data=bad_input):
        form = create_form_for_method(inspect.signature(reserved_param_names), autofill=False, design=False)()

        assert form.validate_on_submit() is False
        assert form.errors["volume"] == ["Not a valid float value."]

    good_input = MultiDict({"volume": "1.5", "validate": "y", "arg_types": "a", "meta": "2"})
    with app.test_request_context("/", method="POST", data=good_input):
        form = create_form_for_method(inspect.signature(reserved_param_names), autofill=False, design=False)()

        assert form.validate_on_submit() is True, form.errors
        assert {field.name: field.data for field in form} == {
            "volume": 1.5, "validate": True, "arg_types": "a", "meta": 2,
        }


def test_parameter_named_arg_types_is_not_dropped_by_metadata(app):
    """Regression: the arg_types metadata used to overwrite a field of the same name."""
    with app.app_context():
        form = create_form_for_method(inspect.signature(reserved_param_names), autofill=False, design=False)()

    assert "arg_types" in [field.name for field in form]
    assert isinstance(form.arg_types, dict)


def test_create_form_from_action_handles_reserved_parameter_names(app):
    action = {
        "id": 3,
        "uuid": 12,
        "instrument": "deck.pump",
        "action": "dose",
        "args": {"volume": 2.0, "validate": 1},
        "arg_types": {"volume": "float", "validate": "int"},
        "return": "",
    }

    with app.app_context():
        form = create_form_from_action(action, design=False)

    assert {field.name: field.data for field in form} == {"volume": 2.0, "validate": 1}
    assert callable(form.validate)


def double_collision(validate: int = 1, param_validate: int = 2):
    """a parameter that collides, next to the name it would be renamed to"""
    return validate, param_validate


def test_renaming_does_not_collide_with_an_existing_parameter(app):
    data = MultiDict({"validate": "1", "param_validate": "2"})

    with app.test_request_context("/", method="POST", data=data):
        form = create_form_for_method(inspect.signature(double_collision), autofill=False, design=False)()

        assert form.validate() is True, form.errors
        assert {field.name: field.data for field in form} == {"validate": 1, "param_validate": 2}


def underscore_param(volume: float, _internal: int = 3):
    """WTForms skips underscore-prefixed attributes, so this field needs a safe name"""
    return volume, _internal


def test_underscore_parameter_is_still_rendered_and_submitted(app):
    with app.test_request_context("/", method="POST", data=MultiDict({"volume": "1.0", "_internal": "5"})):
        form = create_form_for_method(inspect.signature(underscore_param), autofill=False, design=False)()

        assert form.validate() is True, form.errors
        assert {field.name: field.data for field in form} == {"volume": 1.0, "_internal": 5}


def renamed_field_with_error(volume: float, validate: int = 1):
    """`validate` is bound under a safe name, but errors must still name the parameter"""
    return volume, validate


def test_errors_are_reported_under_the_parameter_name(app):
    """A renamed field must not leak its internal attribute name into error messages."""
    with app.test_request_context("/", method="POST", data=MultiDict({"volume": "1.0", "validate": "abc"})):
        form = create_form_for_method(inspect.signature(renamed_field_with_error), autofill=False, design=False)()

        assert form.validate() is False
        assert list(form.errors) == ["validate"]   # not the internal "param_validate"



class Speed(Enum):
    SLOW = 1
    FAST = 2


def test_an_enum_field_takes_the_enums_own_value_from_json(app):
    """The downloaded proxy sends an Enum as its value: ``set_mode(Speed.FAST)`` posts 2."""
    def set_mode(mode: Speed):
        return mode

    form_class = create_form_for_method(inspect.signature(set_mode), autofill=False, design=False)

    with app.test_request_context(method="POST", json={"mode": 2}):
        assert form_class().mode.data == "FAST"
    with app.test_request_context(method="POST", json={"mode": 5}):
        assert form_class().mode.process_errors


def test_an_enum_step_keeps_its_key_however_it_was_typed(app):
    """Key or value, a step stores the key, and its edit form shows the key, so saving it
    again unchanged keeps it as it was. A step saved when steps stored the value shows its key."""
    def stir(mode: Speed, color: Choice):
        return mode, color

    form_class = create_form_for_method(inspect.signature(stir), autofill=False, design=False)

    for typed, stored in [({"mode": "SLOW", "color": "RED"}, ("SLOW", "RED")),
                          ({"mode": "1", "color": "red"}, ("SLOW", "RED"))]:
        with app.test_request_context(method="POST", data=typed):
            form = form_class()
            assert (form.mode.data, form.color.data) == stored

    with app.test_request_context():
        edit = form_class(data={"mode": 1, "color": "red"})
        assert (edit.mode._value(), edit.color._value()) == ("SLOW", "RED")

    with app.test_request_context(method="POST", data={"mode": "SLOW", "color": "RED"}):
        assert form_class().validate()


def mix(level: Optional[Literal["low", "high"]] = None):
    return level


def test_an_optional_literal_is_recorded_with_its_choices():
    assert get_arg_type(["level"], {"signature": inspect.signature(mix)}) == {"level": ["Literal:low,high", "NoneType"]}


@pytest.mark.skipif(sys.version_info < (3, 10), reason="X | None needs Python 3.10")
def test_a_literal_or_none_is_recorded_with_its_choices():
    signature = inspect.Signature([inspect.Parameter(
        "level", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Literal["low", "high"] | None)])
    assert get_arg_type(["level"], {"signature": signature}) == {"level": ["Literal:low,high", "NoneType"]}


def test_an_optional_literal_step_offers_its_choices_when_edited(app, monkeypatch):
    """A step saved before Optional[Literal] kept its choices recorded just "Literal";
    its edit form takes the choices from the deck's signature."""
    monkeypatch.setattr(global_state, "_interface_schema", {"deck.mixer": {"mix": {"signature": inspect.signature(mix)}}})

    for recorded in (["Literal:low,high", "NoneType"], ["Literal", "NoneType"]):
        action = {"id": 1, "uuid": 1, "instrument": "deck.mixer", "action": "mix",
                  "args": {"level": "high"}, "arg_types": {"level": recorded}, "return": ""}
        with app.app_context():
            form = create_form_from_action(action, script=Script(author="tester"), design=True)

        assert isinstance(form.level, FlexibleLiteralField)
        assert form.level.choices == ["low", "high"]
        assert form.level.data == "high"
