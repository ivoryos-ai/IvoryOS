"""Enum and Literal arguments: a step stores a name for the choice, and the driver is called with the choice.

An Enum's name is the member's key, and a Literal's is its option as text (``"1.0"``, ``"False"``). Both are plain
text, so a workflow saves whatever the Enum's values or the Literal's options are: numbers, text, or objects such as
a plate. For an Enum a value is accepted wherever one is typed or sent (``"methanol"``, ``2``, or ``"2"`` as a form
sends it back) and finds its member the same way a key does, so workflows saved when steps stored the value keep
working.
"""

import importlib
import inspect
from enum import EnumMeta
from typing import Union

try:
    from typing import Literal, get_args, get_origin
except ImportError:  # Python 3.7
    from typing_extensions import Literal, get_args, get_origin

try:
    from types import UnionType  # `Mode | None`, Python 3.10+
    _UNIONS = (Union, UnionType)
except ImportError:
    _UNIONS = (Union,)

NOT_AN_OPTION = object()  # None can be a Literal's option


def enum_class_of(annotation):
    """The Enum class an annotation names, also inside ``Optional``; None otherwise."""
    if isinstance(annotation, EnumMeta):
        return annotation
    if get_origin(annotation) in _UNIONS:
        for arg in get_args(annotation):
            if isinstance(arg, EnumMeta):
                return arg
    return None


def enum_class_from_type(type_str):
    """The Enum class a recorded ``Enum:module.Class`` type names, or None if it cannot be found."""
    try:
        _, full_path = type_str.split(":", 1)
        module_name, class_name = full_path.rsplit(".", 1)
    except (AttributeError, ValueError):
        return None
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        from ivoryos.runtime.state import GlobalState

        deck = GlobalState().deck
        if not (deck and (deck.__name__ == module_name or module_name == "__main__")):
            return None
        module = deck
    except Exception:
        return None
    return enum_class_of(getattr(module, class_name, None))


def find_member(enum_class, key):
    """The member ``key`` stands for, or None: the member itself, its key, its value, or its
    value as text (``"1"`` for ``SLOW = 1``)."""
    if isinstance(key, enum_class):
        return key
    if isinstance(key, str) and key in enum_class.__members__:
        return enum_class[key]
    for member in enum_class:
        try:
            if member.value == key or (isinstance(key, str) and str(member.value) == key):
                return member
        except Exception:  # a value whose comparison fails is simply not a match
            continue
    return None


def literal_options_of(annotation):
    """The options of a ``Literal``, also inside ``Optional``; None otherwise."""
    if get_origin(annotation) is Literal:
        return get_args(annotation)
    if get_origin(annotation) in _UNIONS:
        for arg in get_args(annotation):
            if get_origin(arg) is Literal:
                return get_args(arg)
    return None


def find_option(options, key):
    """The option ``key`` stands for, or ``NOT_AN_OPTION``: the option itself, its text (``"1.0"``,
    ``"False"``, what a form and a saved step hold), or a number equal to it (JSON may turn 1.0 into 1)."""
    for option in options:
        if type(option) is type(key) and option == key:
            return option
    for option in options:
        if str(option) == str(key):
            return option
    if isinstance(key, (int, float)) and not isinstance(key, bool):
        for option in options:
            if isinstance(option, (int, float)) and not isinstance(option, bool) and option == key:
                return option
    return NOT_AN_OPTION


def setter_annotation(prop):
    """What a property's setter takes: as the setter annotates it, else what the getter returns,
    the type the Designer's form for the setter is built from."""
    parameters = [p for name, p in inspect.signature(prop.fset).parameters.items() if name != "self"]
    if parameters and parameters[0].annotation is not inspect.Parameter.empty:
        return parameters[0].annotation
    if prop.fget is not None:
        returned = inspect.signature(prop.fget).return_annotation
        if returned is not inspect.Signature.empty:
            return returned
    return inspect.Parameter.empty


def to_members(function, kwargs):
    """``kwargs`` for calling ``function``, each Enum-typed argument as its member and each Literal-typed
    one as its option. An argument that names no choice is passed as it is."""
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return kwargs
    converted = dict(kwargs)
    for name, value in kwargs.items():
        param = parameters.get(name)
        if param is None:
            continue
        enum_class = enum_class_of(param.annotation)
        if enum_class is not None:
            member = find_member(enum_class, value)
            if member is not None:
                converted[name] = member
            continue
        options = literal_options_of(param.annotation)
        if options is not None:
            option = find_option(options, value)
            if option is not NOT_AN_OPTION:
                converted[name] = option
    return converted
