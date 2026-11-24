"""Which module-level objects of a deck script are parsed as instruments."""
import collections
import datetime
import enum
import functools
import logging
import os
import pathlib
import threading
import types

import flask
import pytest

from ivoryos.parsers.introspection import (
    _is_stdlib_by_location,
    _non_instrument_package,
    generate_interface_schema,
)


class Pump:
    def dispense(self, volume: float):
        pass


class Stage:
    @property
    def position(self) -> float:
        return 0.0


class Empty:
    pass


class Mode(enum.Enum):
    FAST = 1


class Worker(threading.Thread):
    def home(self):
        pass


def _fake_library_object(module_name):
    """An object whose class claims to come from ``module_name``, without importing it."""
    cls = type("Figure", (), {"savefig": lambda self: None})
    cls.__module__ = module_name
    return cls()


def _deck(**objects):
    deck = types.ModuleType("fake_deck")
    for name, value in objects.items():
        setattr(deck, name, value)
    return deck


def test_instruments_are_parsed_and_library_objects_skipped():
    deck = _deck(
        pump=Pump(),
        stage=Stage(),
        worker=Worker(),
        out_dir=pathlib.Path("."),
        lock=threading.Lock(),
        today=datetime.date.today(),
        counts=collections.OrderedDict(),
        callback=functools.partial(print, "x"),
        log=logging.getLogger("deck"),
        blueprint=flask.Blueprint("bp", __name__),
        app=flask.Flask("deck"),
        figure=_fake_library_object("matplotlib.figure"),
        mode=Mode.FAST,
        empty=Empty(),
    )
    schema = generate_interface_schema(deck)
    assert set(schema) == {"deck.pump", "deck.stage", "deck.worker"}


def test_dataframe_and_array_are_skipped():
    pd = pytest.importorskip("pandas")
    np = pytest.importorskip("numpy")
    deck = _deck(pump=Pump(), df=pd.DataFrame({"a": [1]}), series=pd.Series([1]),
                 arr=np.zeros(3), value=np.float64(1.0))
    assert set(generate_interface_schema(deck)) == {"deck.pump"}


def test_plain_values_modules_classes_and_functions_are_never_parsed():
    deck = _deck(n=3, name="x", rows=[1], config={"a": 1}, os=os, Pump=Pump, helper=print,
                 fn=lambda: None)
    assert generate_interface_schema(deck, include_names=["n", "os", "helper", "fn"]) == {}


def test_names_starting_with_underscore_or_capital_are_skipped():
    deck = _deck(_pump=Pump(), PUMP=Pump(), Pump2=Pump())
    assert generate_interface_schema(deck) == {}


def test_include_names_keeps_a_skipped_object():
    pd = pytest.importorskip("pandas")
    deck = _deck(df=pd.DataFrame({"a": [1]}), OT2=Pump(), empty=Empty(), out_dir=pathlib.Path("."))
    schema = generate_interface_schema(deck, include_names=["df", "OT2", "empty"])
    assert set(schema) == {"deck.df", "deck.OT2", "deck.empty"}
    assert "to_csv" in schema["deck.df"]
    assert schema["deck.empty"] == {}


def test_exclude_names_wins_over_include_names():
    deck = _deck(pump=Pump(), stage=Stage())
    schema = generate_interface_schema(deck, exclude_names=["stage"], include_names=["stage"])
    assert set(schema) == {"deck.pump"}


def test_startup_summary_lists_skipped_objects(capsys):
    deck = _deck(pump=Pump(), out_dir=pathlib.Path("."), mode=Mode.FAST, n=3)
    generate_interface_schema(deck)
    out = capsys.readouterr().out
    assert "deck.out_dir: PosixPath (pathlib)" in out or "deck.out_dir: WindowsPath (pathlib)" in out
    assert "deck.mode: Mode (no public methods)" in out
    assert "include_names" in out
    assert "deck.n" not in out


def test_startup_summary_has_no_skipped_section_when_nothing_is_skipped(capsys):
    generate_interface_schema(_deck(pump=Pump(), n=3))
    assert "SKIPPED" not in capsys.readouterr().out


@pytest.mark.parametrize("module_name, package", [
    ("pandas.core.frame", "pandas"),
    ("matplotlib.figure", "matplotlib"),
    ("flask.app", "flask"),
    ("pathlib", "pathlib"),
    ("serial.serialposix", ""),
    ("opentrons.protocol_api", ""),
    ("__main__", ""),
    ("my_lab.drivers", ""),
])
def test_non_instrument_package_matches_the_module_name(module_name, package):
    assert _non_instrument_package(_fake_library_object(module_name)) == package


@pytest.mark.parametrize("package, expected", [
    ("pathlib", True),
    ("collections", True),
    ("_thread", True),
    ("ivoryos", False),
    ("pytest", False),
    ("not_a_module_xyz", False),
])
def test_stdlib_fallback_for_python_before_3_10(package, expected):
    assert _is_stdlib_by_location(package) is expected
