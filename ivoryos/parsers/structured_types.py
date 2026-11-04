"""
Support for dict-typed method parameters, e.g. ``def configure(self, settings: dict)`` or ``Dict[str, float]``.

Inside a workflow a dict value is kept as a plain, JSON-friendly dict, so it can be stored, shown and edited whole
(as JSON or as a table of keys and values, see ``static/js/structured_editor.js``) and hold ``#variable``
placeholders at any depth. Those variables become run parameters, and are rendered as bare names in exported
Python code. The driver gets the keys and values its ``Dict[K, V]`` names (``to_dict``), cast when it is called.

The arg type string of a dict parameter is ``"dict"``, or ``["Dict", "NoneType"]`` for an ``Optional[Dict[K, V]]``.
"""
import ast
import copy
import inspect
import json
import re
from enum import Enum
from typing import Any, Union

try:
    from typing import get_args, get_origin
except ImportError:
    from typing_extensions import get_args, get_origin

try:
    from types import UnionType  # PEP 604 ``X | None``, Python 3.10+
except ImportError:
    UnionType = None

_VARIABLE = re.compile(r"#[A-Za-z_]\w*")
_DICT_TYPE = re.compile(r"[Dd]ict(\[.*\])?")
_NAMED_CONSTANTS = {"None": None, "null": None, "True": True, "true": True, "False": False, "false": False}


# ---------------------------------------------------------------------------
# annotations
# ---------------------------------------------------------------------------

def _strip_optional(annotation):
    """``Optional[X]`` -> ``(X, True)``; anything else -> ``(annotation, False)``."""
    origin = get_origin(annotation)
    if origin is Union or (UnionType is not None and origin is UnionType):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(non_none) != len(args):
            return non_none[0], True
    return annotation, False


def is_dict_annotation(annotation):
    """``dict``, ``Dict[K, V]`` / ``dict[K, V]``, or an ``Optional`` of one."""
    inner, _ = _strip_optional(annotation)
    return inner is dict or get_origin(inner) is dict


def _dict_value_annotation(annotation):
    """``V`` of ``Dict[K, V]``, or ``None`` for a bare ``dict`` / anything else."""
    if not is_dict_annotation(annotation):
        return None
    args = get_args(_strip_optional(annotation)[0])
    return args[1] if len(args) == 2 else None


# ---------------------------------------------------------------------------
# arg type strings
# ---------------------------------------------------------------------------

def find_structured_type(type_entry):
    """``"dict"`` when an arg type entry (a string, or a list for ``Optional``) is a dict, else ``None``."""
    entries = type_entry if isinstance(type_entry, list) else [type_entry]
    # "dict", or "Dict" for an Optional[Dict[K, V]] (see introspection._get_type_from_parameters)
    if any(isinstance(entry, str) and _DICT_TYPE.fullmatch(entry) for entry in entries):
        return "dict"
    return None


def load_structured_type(type_entry):
    """The annotation for a structured arg type entry (``dict``), or ``None``."""
    return dict if find_structured_type(type_entry) == "dict" else None


# ---------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------

def is_variable(value):
    return isinstance(value, str) and _VARIABLE.fullmatch(value) is not None


def has_variables(value):
    return any(True for _ in iter_variables(value, None))


def iter_variables(value, annotation):
    """Yield ``(name, annotation)`` for every ``#variable`` leaf inside a structured value."""
    if is_variable(value):
        yield value[1:], annotation
        return
    if isinstance(value, list):
        for item in value:
            for found in iter_variables(item, None):
                yield found
    elif isinstance(value, dict):
        item_type = _dict_value_annotation(annotation)  # the V of a Dict[K, V]
        for item in value.values():
            for found in iter_variables(item, item_type):
                yield found


def substitute_variables(value, context):
    """Replace ``#variable`` leaves nested inside dicts/lists with their values from the context."""
    if is_variable(value):
        return context[value[1:]] if value[1:] in context else value
    if isinstance(value, list):
        return [substitute_variables(item, context) for item in value]
    if isinstance(value, dict):
        return {key: substitute_variables(item, context) for key, item in value.items()}
    return value


def structured_template(annotation):
    """Value used to prefill forms: an empty dict, or ``None`` for an ``Optional`` one."""
    return None if _strip_optional(annotation)[1] else {}


def structured_schema(annotation):
    """
    Layout of a dict annotation for the form editor (``static/js/structured_editor.js``), e.g. for
    ``Optional[Dict[str, float]]``: ``{"kind": "dict", "key": {"kind": "scalar", "type": "str", "optional": False},
    "value": {"kind": "scalar", "type": "float", "optional": False}, "optional": True}``. An Enum value is
    ``{"kind": "enum", "choices": [...]}``; a type the editor has no input for (a union, a list) is ``{"kind": "json"}``.
    """
    inner, optional = _strip_optional(annotation)
    if isinstance(inner, type) and issubclass(inner, Enum) and _json_safe([member.value for member in inner]):
        schema = {"kind": "enum", "type": inner.__name__, "choices": [member.value for member in inner]}
    elif inner in (bool, int, float, str):
        schema = {"kind": "scalar", "type": inner.__name__}
    elif is_dict_annotation(inner):
        args = get_args(inner)
        key, value = args if len(args) == 2 else (str, Any)
        schema = {"kind": "dict", "key": structured_schema(key), "value": structured_schema(value)}
    else:
        schema = {"kind": "json"}
    schema["optional"] = optional
    return schema


def _json_safe(value):
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def format_structured_value(value):
    return json.dumps(value, indent=2)


def parse_structured_value(text, annotation=None):
    """
    Parse user text into plain dicts/lists. Accepts JSON and Python literals, e.g. ``{'gain': 1.5, 'mode': None}``.
    Bare ``#variable`` placeholders are allowed anywhere and kept as ``"#variable"`` strings.
    """
    try:
        tree = ast.parse(_quote_variables(text.strip()), mode="eval")
    except SyntaxError as e:
        raise ValueError(f"cannot parse value ({e.msg})") from e
    return _node_to_value(tree.body, annotation)


class _NamesToVariables(ast.NodeTransformer):
    def visit_Name(self, node):
        if node.id in _NAMED_CONSTANTS:
            return node
        return ast.copy_location(ast.Constant(f"#{node.id}"), node)


def structured_value_from_node(node, annotation):
    """Plain value for an expression in an imported Python script, e.g. ``{'gain': g}``; names become #variables."""
    return _node_to_value(_NamesToVariables().visit(copy.deepcopy(node)), annotation)


def _quote_variables(text):
    """Wrap ``#variable`` tokens outside of string literals in quotes."""
    out = []
    quote = None
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            out.append(char)
            if char == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            out.append(char)
        elif char == "#" and _VARIABLE.match(text, i):
            match = _VARIABLE.match(text, i)
            out.append(repr(match.group(0)))
            i = match.end()
            continue
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _node_to_value(node, annotation=None):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in _NAMED_CONSTANTS:
        return _NAMED_CONSTANTS[node.id]
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float))):
        return -node.operand.value if isinstance(node.op, ast.USub) else node.operand.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_node_to_value(item) for item in node.elts]
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            raise ValueError("'**' unpacking is not supported")
        item_type = _dict_value_annotation(annotation)
        return {_node_to_value(key): _node_to_value(value, item_type) for key, value in zip(node.keys, node.values)}
    raise ValueError(f"unsupported expression: {_source(node)}")


def _source(node):
    try:
        return ast.unparse(node)
    except AttributeError:  # Python < 3.9
        return type(node).__name__


def validate_structured_value(value, annotation, path=""):
    """Raise ``ValueError`` when a dict argument (or a dict nested in one) is not a dict. Variables are allowed anywhere."""
    if value is None or is_variable(value) or not is_dict_annotation(annotation):
        return
    if not isinstance(value, dict):
        raise ValueError(f"{path or 'value'}: expected a dict, got {value!r}")
    for key, item in value.items():
        validate_structured_value(item, _dict_value_annotation(annotation), f"{path}[{key!r}]")


def to_bool(value):
    """``value`` as a bool, in any case, the way a form, a spreadsheet or JSON writes one. Blank is False, as the
    Designer's field says. Anything else is refused: Python's ``bool("FALSE")`` is True."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "t", "yes", "y", "1"):
        return True
    if text in ("false", "f", "no", "n", "0", ""):
        return False
    raise ValueError(f"{value!r} is not True or False")


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{value!r} is not a number") from e


def to_int(value):
    """``value`` as an int. ``3.0`` is 3, but ``2.5`` is refused rather than truncated."""
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    number = to_float(value)
    if not number.is_integer():
        raise ValueError(f"{value!r} is not a whole number")
    return int(number)


_SCALARS = {bool: to_bool, int: to_int, float: to_float, str: str}


def is_scalar_annotation(annotation):
    """``bool``, ``int``, ``float``, ``str``, or an ``Optional`` of one."""
    inner, _ = _strip_optional(annotation)
    return isinstance(inner, type) and inner in _SCALARS


def to_scalar(value, annotation):
    """
    ``value`` as a scalar annotation says; ``ValueError`` when it cannot be. Text for a ``str`` is kept as typed. In an
    ``Optional`` the word None is None, and a plain ``str`` given None gets the text ``'None'``, as it always has.
    """
    inner, optional = _strip_optional(annotation)
    if optional and (value is None or value == "None"):
        return None
    if value is None and inner is not str:
        return None
    return _SCALARS[inner](value)


def is_tuple_annotation(annotation):
    """``tuple``, ``Tuple[X, Y]`` / ``tuple[X, ...]``, or an ``Optional`` of one."""
    inner, _ = _strip_optional(annotation)
    return inner is tuple or get_origin(inner) is tuple


def is_list_annotation(annotation):
    """``list``, ``List[X]`` / ``list[X]``, or an ``Optional`` of one."""
    inner, _ = _strip_optional(annotation)
    return inner is list or get_origin(inner) is list


def is_set_annotation(annotation):
    """``set``, ``Set[X]`` / ``set[X]``, or an ``Optional`` of one."""
    inner, _ = _strip_optional(annotation)
    return inner is set or get_origin(inner) is set


def _literal_or_text(text, as_text):
    """One comma-separated item: quoted text without its quotes; otherwise the text as typed when ``as_text``, else
    the Python value it reads as, if any."""
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError):
        return text
    return value if isinstance(value, str) or not as_text else text


def parse_collection_text(text, item_type=None):
    """
    The items of a list, set or tuple typed as text, the same for the Instruments page and a workflow.

    Brackets mean Python syntax, so ``[A1, B2]`` is refused: text inside them needs quotes. Without brackets, commas
    separate the items. An item of a ``List[str]`` stays as typed (``1E5`` is not 100000.0), and any other is read as
    a Python value where it can be (``A1, 2`` is ``["A1", 2]``).
    """
    text = text.strip()
    if not text:
        return []
    if text[0] in "[({":
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError, TypeError) as e:
            raise ValueError(f"{text!r} is not valid Python: text in brackets needs quotes, as in ['a', 'b']") from e
        if isinstance(parsed, dict):
            raise ValueError(f"{text!r} is a dict, not a list of items")
        return list(parsed) if isinstance(parsed, (list, tuple, set)) else [parsed]
    as_text = _strip_optional(item_type)[0] is str
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError):
        pass
    else:
        items = list(parsed) if isinstance(parsed, tuple) else [parsed]
        if not as_text or all(isinstance(item, str) for item in items):
            return items
    return [_literal_or_text(part.strip(), as_text) for part in text.split(",")]


def to_list(value, annotation):
    """
    A list argument with its items cast by ``List[X]``, from text or from a saved step. ``ValueError`` when an item
    cannot be its type. A bare ``list`` has nothing to cast by.
    """
    inner, optional = _strip_optional(annotation)
    args = get_args(inner)
    item_type = args[0] if args else None
    if isinstance(value, str) and not is_variable(value):
        if optional and value.strip() in ("", "None"):
            return None
        value = parse_collection_text(value, item_type)
    if value is None or is_variable(value):
        return value
    items = list(value) if isinstance(value, (list, tuple, set)) else [value]
    return [_cast_item(item, item_type) for item in items] if args else items


def to_set(value, annotation):
    """A set argument: JSON has no sets, so a saved step holds a list. Items are cast as in :func:`to_list`."""
    items = to_list(value, annotation)
    if items is None or is_variable(items):
        return items
    try:
        return set(items)
    except TypeError as e:
        raise ValueError(f"{items!r} cannot be a set: {e}") from e


def _cast_item(item, annotation):
    """
    An element of a collection, or a key or value of a dict, as its annotation says. A type without a rule here (an Enum,
    a union, ``Any``) is left as it came, and so are None and ``#variables``.
    """
    inner, _ = _strip_optional(annotation)
    if item is None or is_variable(item):
        return item
    if is_tuple_annotation(inner):
        return to_tuple(item, inner)
    if is_dict_annotation(inner):
        return to_dict(item, inner)
    if is_list_annotation(inner) and isinstance(item, (list, tuple, set)):
        return to_list(item, inner)
    if is_set_annotation(inner) and isinstance(item, (list, tuple, set)):
        return to_set(item, inner)
    # the whole annotation, so the word None in an Optional is None
    return to_scalar(item, annotation) if is_scalar_annotation(inner) else item


def to_tuple(value, annotation):
    """
    A tuple argument as the tuple the driver asked for: JSON has no tuples, so a saved step holds a list, and text
    arrives from a form or a spreadsheet cell, read as :func:`parse_collection_text` says. Elements are cast by the
    annotation; ``ValueError`` when one cannot be.
    """
    inner, optional = _strip_optional(annotation)
    args = get_args(inner)
    if isinstance(value, str) and not is_variable(value):
        if optional and value.strip() in ("", "None"):
            return None
        # with text in any position every item is kept as typed, and the casts below read the others from it
        value = parse_collection_text(value, str if any(_strip_optional(arg)[0] is str for arg in args) else None)
    if value is None or is_variable(value):
        return value
    items = list(value) if isinstance(value, (list, tuple, set)) else [value]
    if not args:
        return tuple(items)
    if len(args) == 2 and args[1] is Ellipsis:
        return tuple(_cast_item(item, args[0]) for item in items)
    if len(items) != len(args):
        raise ValueError(f"expected {len(args)} values, got {len(items)}: {value!r}")
    return tuple(_cast_item(item, item_type) for item, item_type in zip(items, args))


def to_dict(value, annotation):
    """
    A dict argument with its keys and values cast by ``Dict[K, V]``, at any depth. JSON keys are always text, so a
    saved step's ``{1: 1.5}`` comes back as ``{"1": 1.5}``, and typed JSON writes a float as ``1``. ``ValueError``
    names the key whose key or value cannot be cast. A bare ``dict`` is left as it came.
    """
    if isinstance(value, str) and not is_variable(value):
        value = parse_structured_value(value, annotation)
    args = get_args(_strip_optional(annotation)[0])
    if not isinstance(value, dict) or len(args) != 2:
        return value
    key_type, value_type = args
    converted = {}
    for key, item in value.items():
        try:
            converted[_cast_item(key, key_type)] = _cast_item(item, value_type)
        except ValueError as e:
            reason = str(e)
            raise ValueError(f"[{key!r}]" + (reason if reason.startswith("[") else f": {reason}")) from None
    return converted


def to_containers(function, kwargs):
    """``kwargs`` for calling ``function``, each list-, set-, tuple- or dict-typed argument cast by its annotation."""
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return kwargs
    converted = dict(kwargs)
    for name, value in kwargs.items():
        param = parameters.get(name)
        if param is not None and is_tuple_annotation(param.annotation):
            converted[name] = to_tuple(value, param.annotation)
        elif param is not None and is_dict_annotation(param.annotation):
            converted[name] = to_dict(value, param.annotation)
        elif param is not None and is_list_annotation(param.annotation):
            converted[name] = to_list(value, param.annotation)
        elif param is not None and is_set_annotation(param.annotation):
            converted[name] = to_set(value, param.annotation)
    return converted


def render_python(value, annotation=None):
    """Python source for a structured value, ``#variable`` leaves as bare names."""
    if is_variable(value):
        return value[1:]
    if isinstance(value, list):
        return "[" + ", ".join(render_python(item) for item in value) + "]"
    if isinstance(value, dict):
        item_type = _dict_value_annotation(annotation)
        return "{" + ", ".join(f"{key!r}: {render_python(item, item_type)}" for key, item in value.items()) + "}"
    return repr(value)
