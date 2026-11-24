import inspect
import pickle
import os
import sys
import sysconfig
from enum import Enum
try:
    from typing import get_args, get_origin, Literal
except ImportError:
    from typing_extensions import get_args, get_origin, Literal

from ivoryos.utils.decorators import BUILDING_BLOCKS
from ivoryos.utils.enums import _UNIONS


UNSUPPORTED_PARAMETER_TYPES = ["BinaryIO", "TextIO", "BytesIO", "typing.IO"]

# A deck object whose class comes from one of these packages is data, a plot or part of a web
# app, not an instrument: a module-level DataFrame or Flask app is not parsed. Standard library
# objects (Path, Lock, Queue, Logger...) are skipped the same way. Only the name of the class's
# module is compared, so none of these packages is imported.
NON_INSTRUMENT_PACKAGES = frozenset({
    "numpy", "pandas", "polars", "pyarrow", "scipy", "xarray", "sympy",
    "matplotlib", "seaborn", "plotly", "bokeh", "PIL",
    "sklearn", "torch", "tensorflow", "jax",
    "flask", "flask_login", "flask_socketio", "flask_sqlalchemy", "flask_wtf",
    "werkzeug", "jinja2", "sqlalchemy", "socketio", "engineio",
    "requests", "httpx", "openai",
})


def _is_stdlib_by_location(package: str) -> bool:
    """Whether the imported top-level module ``package`` was loaded from the standard library.

    Fallback for Python < 3.10, which has no ``sys.stdlib_module_names``.
    """
    if package in sys.builtin_module_names:
        return True
    path = getattr(sys.modules.get(package), "__file__", None)
    if not path:
        return False
    path = os.path.normcase(os.path.realpath(path))
    if "site-packages" in path or "dist-packages" in path:
        return False
    paths = sysconfig.get_paths()
    # Windows keeps the standard library's C extensions in DLLs, beside Lib
    roots = {paths["stdlib"], paths["platstdlib"], os.path.join(sys.base_prefix, "DLLs")}
    return any(path.startswith(os.path.normcase(os.path.realpath(root)) + os.sep) for root in roots)


def _is_stdlib(package: str) -> bool:
    """Whether ``package``, a top-level module name, belongs to the standard library."""
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return package in names
    return _is_stdlib_by_location(package)


def _non_instrument_package(val) -> str:
    """The package ``val``'s class comes from when that makes it no instrument, else ``''``."""
    package = (getattr(type(val), "__module__", None) or "").split(".")[0]
    if package and (package in NON_INSTRUMENT_PACKAGES or _is_stdlib(package)):
        return package
    return ""


def _inspect_class(class_object=None, debug=False):
    """
    inspect class object: inspect function signature if not name.startswith("_")
    """
    functions = {}
    under_score = "_"
    if debug:
        under_score = "__"

    for function, method in inspect.getmembers(type(class_object), predicate=callable):
        if not function.startswith(under_score) and not function.isupper():
            try:
                annotation = inspect.signature(method)
                
                # Check if the method requires an unsupported parameter type (like file streams)
                is_compatible = True
                for p in annotation.parameters.values():
                    type_str = str(p.annotation)
                    if any(t in type_str for t in UNSUPPORTED_PARAMETER_TYPES):
                        is_compatible = False
                        break
                
                if not is_compatible:
                    continue

                docstring = inspect.getdoc(method)
                coroutine = inspect.iscoroutinefunction(method)
                has_args = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in annotation.parameters.values())
                has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in annotation.parameters.values())
                functions[function] = dict(signature=annotation, docstring=docstring, coroutine=coroutine,
                                           has_args=has_args, has_kwargs=has_kwargs)

            except Exception:
                pass

    for function, prop in inspect.getmembers(type(class_object), lambda x: isinstance(x, property)):
        if not function.startswith(under_score) and not function.isupper():
            try:
                annotation = inspect.signature(prop.fget) if prop.fget else None
                docstring = inspect.getdoc(prop)
                functions[function] = dict(signature=annotation, docstring=docstring, coroutine=False,
                                           is_property=True, has_setter=prop.fset is not None)
            except Exception:
                pass
    return functions


def _resolve_type_string(annotation):
    arg_type = ''
    if isinstance(annotation, str):
        arg_type = annotation
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        module_name = annotation.__module__
        if module_name == "__main__":
            from ivoryos.runtime.state import GlobalState
            deck = GlobalState().deck
            if deck:
                if deck.__name__ == "__main__":
                     if hasattr(deck, '__file__'):
                         module_name = os.path.splitext(os.path.basename(deck.__file__))[0]
                else:
                    module_name = deck.__name__
        arg_type = f"Enum:{module_name}.{annotation.__name__}"
    elif get_origin(annotation) is Literal:
        # inside Optional/Union too, so an Optional[Literal] keeps its choices
        arg_type = _literal_type_string(annotation)
    elif hasattr(annotation, '__name__'):
        arg_type = annotation.__name__
    elif getattr(annotation, '_name', None):
        # List[int] and the like have no __name__ before Python 3.10
        arg_type = annotation._name
    else:
        arg_type = str(annotation)
    return arg_type


def _literal_type_string(annotation):
    """``Literal["a", "b"]`` as a step records it: ``Literal:a,b``."""
    return f"Literal:{','.join(str(a) for a in get_args(annotation))}"


def _get_type_from_parameters(arg, parameters):
    """get argument types from inspection"""
    arg_type = ''
    try:
        if isinstance(parameters, inspect.Signature):
            if arg not in parameters.parameters:
                return arg_type
            annotation = parameters.parameters[arg].annotation
        elif isinstance(parameters, dict):
            annotation = parameters.get(arg, '')
        else:
            annotation = ''
    except Exception:
        return arg_type

    if isinstance(annotation, str):
        arg_type = annotation
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        arg_type = _resolve_type_string(annotation)
    elif annotation is not inspect._empty:
        origin = get_origin(annotation)
        if origin is Literal:
            return _literal_type_string(annotation)

        # Optional[X], Union[X, Y] and X | None. Python 3.14 made them one class, in `typing`
        # and named Union, so this comes before anything that looks at the module or the name.
        if origin in _UNIONS:
            arg_type = [_resolve_type_string(i) for i in get_args(annotation)]
        elif getattr(annotation, '__module__', '') == 'typing':

            if hasattr(annotation, '__origin__'):
                origin = annotation.__origin__
                if hasattr(origin, '__name__'):
                    arg_type = origin.__name__
        else:
            arg_type = annotation.__name__
    return arg_type


def get_arg_type(args, parameters):
    """get argument type from signature"""
    arg_types = {}
    parameters = parameters.get("signature")
    if args:
        for arg in args:
            arg_types[arg] = _get_type_from_parameters(arg, parameters)
    return arg_types


def get_return_type(function_data):
    """Return lightweight metadata from a function signature's return annotation."""
    signature = function_data.get("signature") if isinstance(function_data, dict) else function_data
    if not isinstance(signature, inspect.Signature):
        return {"kind": "none", "types": [], "annotation": ""}

    annotation = signature.return_annotation
    if annotation in (None, type(None)):
        return {"kind": "none", "types": [], "annotation": ""}

    if annotation in (inspect.Signature.empty, inspect._empty):
        return {"kind": "scalar", "types": [], "annotation": ""}

    if isinstance(annotation, str):
        return _get_return_type_from_string(annotation)

    origin = get_origin(annotation)
    args = get_args(annotation)
    annotation_str = str(annotation)

    if annotation is tuple or origin is tuple:
        variable_length = len(args) == 2 and args[1] is Ellipsis
        return {
            "kind": "tuple",
            "types": [_resolve_type_string(arg) for arg in args if arg is not Ellipsis],
            "annotation": annotation_str,
            "variable_length": variable_length,
            "arity": None if variable_length else len(args),
        }

    if annotation is dict or origin is dict:
        return {
            "kind": "dict",
            "types": [_resolve_type_string(arg) for arg in args],
            "annotation": annotation_str,
        }

    return {
        "kind": "scalar",
        "types": [_resolve_type_string(annotation)],
        "annotation": annotation_str,
    }


def _split_annotation_args(annotation_args):
    args = []
    depth = 0
    start = 0
    for index, char in enumerate(annotation_args):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(annotation_args[start:index].strip())
            start = index + 1
    final_arg = annotation_args[start:].strip()
    if final_arg:
        args.append(final_arg)
    return args


def _get_return_type_from_string(annotation):
    annotation = annotation.strip().strip("'\"")
    parse_annotation = annotation[7:] if annotation.lower().startswith("typing.") else annotation
    normalized = parse_annotation.lower()

    if normalized in ("", "none"):
        return {"kind": "none", "types": [], "annotation": annotation}

    for prefix in ("tuple[", "tuple("):
        if normalized.startswith(prefix) and parse_annotation.endswith(("]", ")")):
            args = _split_annotation_args(parse_annotation[len(prefix):-1])
            variable_length = len(args) == 2 and args[1] == "..."
            return {
                "kind": "tuple",
                "types": [arg for arg in args if arg != "..."],
                "annotation": annotation,
                "variable_length": variable_length,
                "arity": None if variable_length else len(args),
            }

    for prefix in ("dict[", "dict("):
        if normalized.startswith(prefix) and parse_annotation.endswith(("]", ")")):
            return {
                "kind": "dict",
                "types": _split_annotation_args(parse_annotation[len(prefix):-1]),
                "annotation": annotation,
            }

    return {"kind": "scalar", "types": [annotation], "annotation": annotation}


def generate_interface_schema(deck, save: bool = False, output_path: str = '', exclude_names: list = None,
                              include_names: list = None):
    """
    Create an interface schema of the given script

    Module attributes that are not instruments are skipped: plain values, modules, classes and
    functions; names starting with ``_`` or a capital letter; objects whose class comes from the
    standard library or a package in ``NON_INSTRUMENT_PACKAGES``; and objects with no public
    method or property.

    :param exclude_names: attribute names never to parse
    :param include_names: attribute names to parse even when the rules above would skip them
                          (except plain values, modules, classes and functions)
    """
    exclude_names = set(exclude_names or ())
    include_names = set(include_names or ())

    interface_schema = {}
    included = {}
    skipped = {}  # objects skipped as not instruments, listed at startup
    failed = {}

    for name, val in vars(deck).items():
        qualified_name = f"deck.{name}"
        class_name = type(val).__name__

        if type(val).__module__ == 'builtins' or name in exclude_names:
            continue
        forced = name in include_names
        if not forced:
            if name[0].isupper() or name.startswith("_"):
                continue
            package = _non_instrument_package(val)
            if package:
                skipped[qualified_name] = f"{class_name} ({package})"
                continue

        try:
            functions = _inspect_class(val)
        except Exception as e:
            failed[qualified_name] = str(e)
            continue
        if not functions and not forced:
            skipped[qualified_name] = f"{class_name} (no public methods)"
            continue
        interface_schema[qualified_name] = functions
        included[qualified_name] = class_name

    deck_summary = {
        "included": included,
        "skipped": skipped,
        "failed": failed
    }

    def print_interface_schema(deck_summary):
        def print_section(title, items):
            try:
                print(f"\n=== {title} ({len(items)}) ===")
            except UnicodeEncodeError:
                safe_title = title.encode("ascii", errors="replace").decode("ascii")
                print(f"\n=== {safe_title} ({len(items)}) ===")
            if not items:
                return
            for name, class_type in items.items():
                print(f"  {name}: {class_type}")

        print_section("INCLUDED MODULES [ok]", deck_summary["included"])
        if deck_summary["skipped"]:
            print_section("SKIPPED, NOT INSTRUMENTS [skip]", deck_summary["skipped"])
            print("  To parse one anyway, pass its name in ivoryos.run(..., include_names=[...])")
        print_section("FAILED MODULES [err]", deck_summary["failed"])
        print("\n")

    print_interface_schema(deck_summary)

    if interface_schema and save:
        parse_dict = interface_schema.copy()
        parse_dict["deck_name"] = os.path.splitext(os.path.basename(deck.__file__))[
            0] if deck.__name__ == "__main__" else deck.__name__
        try:
            if output_path:
                os.makedirs(output_path, exist_ok=True)
            with open(os.path.join(output_path, f"{parse_dict['deck_name']}.pkl"), 'wb') as file:
                pickle.dump(parse_dict, file)
        except Exception:
            pass
    return interface_schema


def generate_block_schema(save: bool = False, output_path: str = ''):
    block_schema = {}
    for category, data in BUILDING_BLOCKS.items():
        key = f"blocks.{category}"
        block_schema[key] = {}

        for func_name, meta in data.items():
            func = meta["func"]
            block_schema[key][func_name] = {
                "signature": meta["signature"],
                "docstring": meta["docstring"],
                "coroutine": meta["coroutine"],
                "path": f"{func.__module__}.{func.__qualname__}"
            }
    if block_schema:
        print(f"\n=== BUILDING_BLOCKS [ok] ({len(block_schema)}) ===")
        for category, blocks in block_schema.items():
            print(f"  {category}: ", ",".join(blocks.keys()))
    return block_schema

def load_interface_schema(pkl_name: str):
    """
    Loads a pickled interface schema from disk on offline mode
    """
    if not pkl_name:
        return None
    try:
        with open(pkl_name, 'rb') as f:
            interface_schema = pickle.load(f)
        return interface_schema
    except FileNotFoundError:
        return None


def create_module_interface_schema(module):
    classes = inspect.getmembers(module, inspect.isclass)
    api_variables = {}
    for i in classes:
        api_variables[i[0]] = i[1]
    return api_variables
