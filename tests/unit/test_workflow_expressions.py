"""Workflow conditions and variable statements are read without eval, and defining a registered workflow runs no
code saved in it."""
import asyncio
import enum
from typing import Literal, Optional
from unittest.mock import MagicMock

import pytest

from ivoryos.runtime.script_runner import ScriptRunner
from ivoryos.runtime.script_runner_steps import ScriptRunnerStepMixin
from ivoryos.utils.expressions import evaluate


class Speed(enum.Enum):
    FAST = 1


NAMES = {"x": 3, "y": 2.5, "ready": True, "name": "abc", "values": [1, 2, 3], "result": {"yield": 0.8},
         "speed": Speed.FAST}


@pytest.mark.parametrize("expression, expected", [
    ("x + 5 * (y - 2)", 5.5),
    ("x > 2 and ready", True),
    ("0 or 'fallback'", "fallback"),
    ("1 < x < 5", True),
    ("x in values", True),
    ("'a' if ready else 'b'", "a"),
    ("values[-1]", 3),
    ("values[1:]", [2, 3]),
    ("result['yield'] > 0.5", True),
    ("name.upper()", "ABC"),
    ("result.get('missing', 0)", 0),
    ("speed.name", "FAST"),
    ("f'run_{x}_{y:.1f}'", "run_3_2.5"),
    ("  x + 1", 4),
])
def test_plain_expressions_give_what_python_gives(expression, expected):
    assert evaluate(expression, NAMES) == expected


@pytest.mark.parametrize("expression", [
    "().__class__.__base__.__subclasses__()",
    "'{0.__class__}'.format(x)",
    "f'{x.__class__}'",
    "__import__('os')",
    "len(values)",
    "(lambda: 1)()",
    "[i for i in values]",
    "{**result}",
    "_hidden",
])
def test_anything_beyond_a_plain_expression_is_refused(expression):
    with pytest.raises(ValueError):
        evaluate(expression, NAMES)


def test_modules_reached_through_a_value_are_refused():
    import os
    import types

    with pytest.raises(ValueError):
        evaluate("deck.os.getcwd()", {"deck": types.SimpleNamespace(os=os)})


def test_unknown_names_are_reported():
    with pytest.raises(NameError):
        evaluate("missing > 0", NAMES)


def test_conditions_cannot_reach_python_internals():
    with pytest.raises(ValueError):
        ScriptRunnerStepMixin._evaluate_condition("#x.__class__.__base__.__subclasses__()", {"x": 1})


def _run_variable_step(instrument, statement, arg_type, context):
    runner = ScriptRunner()
    runner.logger = MagicMock()
    step = {"instrument": instrument, "action": "out", "args": {"statement": statement},
            "arg_types": {"statement": arg_type}}
    asyncio.run(runner._execute_variable_batched(step, [context], phase_id=1, step_index=1, section_name="script"))
    return context["out"]


@pytest.mark.parametrize("statement, arg_type, expected", [
    ("#x + 5 * (#y - 2)", "float", 5.5),
    ("x * 2", "int", 6),
    ("#x / 2", "int", 1),
    ("#x > 2", "bool", True),
    ("f'run_{#x}'", "str", "run_3"),
    ('"quoted text"', "str", "quoted text"),
    ("sample-1", "str", "sample-1"),
])
def test_math_and_variable_steps_still_evaluate(statement, arg_type, expected):
    assert _run_variable_step("math_variable", statement, arg_type, {"x": 3, "y": 2.5}) == expected


def test_a_text_variable_that_tries_to_escape_is_kept_as_text():
    statement = "().__class__.__base__.__subclasses__()"
    assert _run_variable_step("variable", statement, "str", {}) == statement


@pytest.mark.parametrize("statement, expected", [
    ('#name + "_asd"', "qwe_asd"),
    ('name + "_asd"', "qwe_asd"),
    ('f"{name}_asd"', "qwe_asd"),
    ('f"{#name}_asd"', "qwe_asd"),
    ("#name.upper()", "QWE"),
    ("#name_input", "abc"),
    ("sample_#x", "sample_3"),
    ("run-#x", "run-3"),
    ("vial #A1", "vial #A1"),
    ("plain text", "plain text"),
])
def test_text_variables_are_built_from_other_variables(statement, expected):
    # issue 217: a text value was pasted into the statement, so `#name + "_asd"` was kept as `qwe + "_asd"`
    context = {"name": "qwe", "name_input": "abc", "x": 3}
    assert _run_variable_step("variable", statement, "str", context) == expected


def test_a_condition_on_a_text_variable_holds():
    assert _run_variable_step("variable", '#status == "done"', "bool", {"status": "done"}) is True


@pytest.mark.parametrize("arg_type, expected", [("float", 10.0), ("str", 10)])
def test_numbers_given_as_text_still_add_up(arg_type, expected):
    # a config column with no type keeps its cells as text
    assert _run_variable_step("variable", "#base * 2", arg_type, {"base": "5"}) == expected


@pytest.mark.parametrize("statement", ['f"{#nmae}_asd"', 'f"{nmae}_asd"'])
def test_a_misspelt_name_in_an_f_string_is_an_error(statement):
    with pytest.raises(NameError, match="nmae"):
        ScriptRunnerStepMixin._variable_value(statement, "str", {"name": "qwe"})


@pytest.mark.parametrize("statement, line, inputs", [
    ('f"{#name}_asd"', 'out = f"{name}_asd"', ["name"]),
    ('#name + "_asd"', 'out = name + "_asd"', ["name"]),
    ("#a + #b", "out = a + b", ["a", "b"]),
    ("#name_input", "out = name_input", ["name_input"]),
    ("vial #A1", "out = vial #A1", []),
])
def test_text_variables_compile(app, statement, line, inputs):
    from ivoryos.script import Script, ScriptEditor, ScriptRenderer

    step = {"id": 1, "uuid": 1, "instrument": "variable", "action": "out", "args": {"statement": statement},
            "arg_types": {"statement": "str"}, "return": ""}
    script = Script(author="t", name="wf")
    script.script_dict = {"prep": [], "script": [step], "cleanup": []}
    with app.app_context():
        assert ScriptEditor(script).config("script")[0] == inputs
        renderer = ScriptRenderer(script)
        code = f"{renderer.get_required_imports()}\n{renderer.compile()['script']}"
    assert line in code
    compile(code, "<workflow>", "exec")


@pytest.mark.parametrize("instrument, statement, line", [
    ("variable", "#x * 2", "param['out'] = float(x * 2)"),
    ("math_variable", "#x * 2", "param['out'] = float(x * 2)"),
])
def test_a_variable_expression_is_in_the_batch_code_as_math_was(app, instrument, statement, line):
    from ivoryos.script import Script, ScriptRenderer

    step = {"id": 1, "uuid": 1, "instrument": instrument, "action": "out", "args": {"statement": statement},
            "arg_types": {"statement": "float"}, "return": ""}
    script = Script(author="t", name="wf")
    script.script_dict = {"prep": [], "script": [step], "cleanup": []}
    with app.app_context():
        assert line in ScriptRenderer(script).compile(batch=True)["script"]


@pytest.mark.parametrize("condition, line, inputs", [
    ("#x > 5", "if x > 5:", ["x"]),
    ("#x > 5 and #y < 3", "if x > 5 and y < 3:", ["x", "y"]),
    ("x > 5", "if x > 5:", []),
])
def test_conditions_on_run_inputs_compile(app, condition, line, inputs):
    # `#x > 5` was the input `x > 5`, and `def wf(x > 5)` did not compile
    from ivoryos.script import Script, ScriptEditor, ScriptRenderer

    steps = [{"id": i, "uuid": 1, "instrument": "if", "action": action, "args": args, "arg_types": {}, "return": ""}
             for i, (action, args) in enumerate([("if", {"statement": condition}), ("else", {}), ("endif", {})], 1)]
    script = Script(author="t", name="wf")
    script.script_dict = {"prep": [], "script": steps, "cleanup": []}
    with app.app_context():
        assert ScriptEditor(script).config("script")[0] == inputs
        renderer = ScriptRenderer(script)
        code = f"{renderer.get_required_imports()}\n{renderer.compile()['script']}"
    assert line in code
    compile(code, "<workflow>", "exec")


def _registered_workflow(arg_type):
    from ivoryos.forms.dynamic_forms import get_method_from_workflow
    from ivoryos.script import Script, ScriptRenderer

    step = {"id": 1, "uuid": 1, "instrument": "deck.pump", "action": "go", "args": {"x": "#p"},
            "arg_types": {"x": arg_type}, "return": "", "coroutine": False}
    script = Script(author="t", name="wf")
    script.script_dict = {"prep": [], "script": [step], "cleanup": []}
    renderer = ScriptRenderer(script)
    code = f"{renderer.get_required_imports()}\n{renderer.compile()['script']}"
    return get_method_from_workflow(code, func_name="wf")


@pytest.mark.parametrize("arg_type, annotation", [
    ("int", int),
    (["float", "NoneType"], Optional[float]),
    ("Literal:a,1", Literal["a", 1]),
])
def test_a_registered_workflow_keeps_its_parameter_types(app, arg_type, annotation):
    import inspect

    with app.app_context():
        assert inspect.signature(_registered_workflow(arg_type)).parameters["p"].annotation == annotation


@pytest.mark.parametrize("arg_type", [
    "__import__('sys').modules.setdefault('ivoryos_test_ran', 1) and int",
    "Literal:a') or __import__('sys').modules.setdefault('ivoryos_test_ran', 1) or ('b",
])
def test_a_saved_type_never_runs_when_a_workflow_is_defined(app, arg_type):
    import sys

    with app.app_context():
        try:
            _registered_workflow(arg_type)
        except (ValueError, NameError):
            pass
    assert "ivoryos_test_ran" not in sys.modules
