"""The stand-ins for asyncio.to_thread and ast.unparse behave like them on a Python that has neither."""
import ast
import asyncio
import contextvars
import importlib.util
import threading

import pytest

from ivoryos.utils import compat


@pytest.fixture
def old_compat(monkeypatch):
    """ivoryos.utils.compat as Python 3.8 loads it: a separate copy, so the real module is untouched."""
    monkeypatch.delattr(asyncio, "to_thread", raising=False)
    monkeypatch.delattr(ast, "unparse", raising=False)
    spec = importlib.util.spec_from_file_location("ivoryos_compat_old_python", compat.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_to_thread_stand_in_runs_the_call_in_another_thread(old_compat):
    assert old_compat.to_thread.__module__ == "ivoryos_compat_old_python"

    def dose(volume, unit="mL"):
        return f"{volume} {unit}", threading.get_ident()

    async def main():
        return await old_compat.to_thread(dose, 5, unit="uL")

    output, thread = asyncio.run(main())
    assert output == "5 uL"
    assert thread != threading.get_ident()


def test_to_thread_stand_in_carries_context_variables_and_errors(old_compat):
    sample = contextvars.ContextVar("sample")

    def fail():
        raise TimeoutError(sample.get())

    async def main():
        sample.set("A1")
        assert await old_compat.to_thread(sample.get) == "A1"
        await old_compat.to_thread(fail)

    with pytest.raises(TimeoutError, match="A1"):
        asyncio.run(main())


def test_unparse_stand_in_returns_the_text_the_node_was_parsed_from(old_compat):
    source = 'def workflow(amount: float):\n    if count > 1 and name == "A":\n        pass\n'
    function = ast.parse(source).body[0]

    assert old_compat.unparse(function.args.args[0].annotation, source) == "float"
    assert old_compat.unparse(function.body[0].test, source) == 'count > 1 and name == "A"'


@pytest.mark.skipif(not hasattr(ast, "unparse"), reason="ast.unparse needs Python 3.9")
def test_unparse_is_ast_unparse_where_python_has_it():
    source = 'x  ==  "A"'
    assert compat.unparse(ast.parse(source, mode="eval").body, source) == "x == 'A'"
    assert compat.to_thread is asyncio.to_thread
