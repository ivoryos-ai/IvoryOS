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
