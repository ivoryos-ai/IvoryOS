"""
A showcase of the input types IvoryOS's dynamic forms support.

Every call checks what it received against the method's annotations and raises a TypeError on a
mismatch, whether it came from a workflow step or from the Instruments page. Running a workflow
built from these methods therefore doubles as a test that each type reaches the driver intact.
"""
import functools
import inspect
import logging
from enum import Enum, EnumMeta
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union, get_args, get_origin

try:
    from types import UnionType  # `int | None`, Python 3.10+
    _UNIONS = (Union, UnionType)
except ImportError:
    _UNIONS = (Union,)

logger = logging.getLogger("showcase_logger")
logger.setLevel(logging.INFO)


def _matches(value, expected):
    """Whether ``value`` is what a parameter annotated ``expected`` should receive, at any depth."""
    if expected in (inspect.Parameter.empty, Any):
        return True
    if expected in (None, type(None)):
        return value is None
    origin, args = get_origin(expected), get_args(expected)
    if origin in _UNIONS:
        return any(_matches(value, arg) for arg in args)
    if origin is Literal:  # Literal[1] is not satisfied by "1" or by True
        return any(type(value) is type(option) and value == option for option in args)
    if origin is dict:
        key_type, value_type = args or (Any, Any)
        if isinstance(value_type, EnumMeta):  # an Enum inside a dict arrives as the plain text or number
            value_type = Any
        return isinstance(value, dict) and all(
            _matches(key, key_type) and _matches(item, value_type) for key, item in value.items())
    if origin in (list, set):
        return isinstance(value, origin) and all(_matches(item, args[0]) for item in value)
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_matches(item, args[0]) for item in value)
        return len(value) == len(args) and all(map(_matches, value, args))
    if expected is float:  # an int is a fine float, a bool is not
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def _checked(method):
    """Log a call's arguments and raise a TypeError for any that its annotation does not allow."""
    signature = inspect.signature(method)

    @functools.wraps(method)  # IvoryOS reads the signature and docstring through this
    def wrapper(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        received = {name: value for name, value in bound.arguments.items() if name != "self"}
        logger.info("%s(%s)", method.__name__,
                    ", ".join(f"{name}={value!r} <{type(value).__name__}>" for name, value in received.items()))
        problems = [f"{name}={value!r} is a {type(value).__name__}, expected {signature.parameters[name].annotation}"
                    for name, value in received.items() if not _matches(value, signature.parameters[name].annotation)]
        if problems:
            raise TypeError(f"{method.__name__}: " + "; ".join(problems))
        return method(*args, **kwargs)
    return wrapper


def check_arguments(cls):
    """Class decorator: apply :func:`_checked` to every public method."""
    for name, member in list(vars(cls).items()):
        if inspect.isfunction(member) and not name.startswith("_"):
            setattr(cls, name, _checked(member))
    return cls


class Color(Enum):
    RED = "Red"
    GREEN = "Green"
    BLUE = "Blue"


class Speed(Enum):
    SLOW = 1
    FAST = 3


@check_arguments
class InputTypeShowcase:
    """Each method shows one family of types. Its docstring, shown in the UI, gives an example to try."""

    def basic_types(self, string_input: str, int_input: int, float_input: float, bool_input: bool):
        """str, int, float and bool. Each is required, except a blank bool, which is False."""
        return True

    def optional_types(self, optional_int: Optional[int] = None, optional_float: Optional[float] = None,
                       optional_str: Union[str, None] = None, optional_bool: Optional[bool] = None):
        """Optional fields can be left blank, and then arrive as None (a blank bool is False)."""
        return True

    def union_types(self, number: Union[int, float], int_or_text: Union[int, str] = "auto"):
        """Unions accept any of their types: try 3 and 2.5, then 5 and auto."""
        return True

    def default_values(self, standard_timeout: int = 60, default_name: str = "IvoryOS", ratio: float = 0.5,
                       enabled: bool = True):
        """Defaults are pre-filled in the form."""
        return True

    def enum_choices(self, primary_color: Color, speed: Speed = Speed.SLOW, optional_color: Optional[Color] = None):
        """Enum dropdowns: the driver gets the member, whether its values are text or numbers."""
        return True

    def literal_choices(self, mode: Literal["Fast", "Standard", "Slow"], retry: Literal[1, 3, 5] = 3,
                        scale: Literal[0.5, 1.0] = 1.0, optional_mode: Optional[Literal["Fast", "Slow"]] = None):
        """Literal dropdowns: the driver gets the option as written, so 3 rather than "3"."""
        return True

    def list_types(self, sample_ids: List[str], temperatures: List[float], counts: list[int], anything: list,
                   optional_ids: Optional[List[str]] = None):
        """Lists, as 1, 2 or as Python, where text needs quotes: ['A1', 'B2']. List[str] always gets text, so try
        sample_ids = A1, 1E5. A bare list reads each item, so try anything = A1, 2."""
        return True

    def tuple_types(self, position: Tuple[float, float], series: Tuple[int, ...], anything: tuple):
        """A fixed-length tuple, a variable-length tuple and a bare tuple. Try 1.5, 2.5 then 1, 2, 3 then a, 1."""
        return True

    def set_types(self, tags: Set[str], anything: set):
        """Sets, typed like lists: the driver gets a set, without repeats. Try a, b, a and 1, 2."""
        return True

    def dict_types(self, settings: dict, gains: Dict[str, float], well_volumes: Dict[int, float],
                   flags: dict[str, bool]):
        """Flat dicts. Try settings = {"rpm": 300, "mode": "fast"}, well_volumes = {1: 10.5, 2: 20}."""
        return True

    def dict_nested_types(self, program: Dict[str, Dict[str, float]], ramps: Dict[str, List[float]],
                          offsets: Dict[str, Optional[float]], mixed: Dict[str, Union[int, str]]):
        """Nested values. Try program = {"heat": {"temp": 80}}, ramps = {"a": [1, 2.5]}, offsets = {"x": null}."""
        return True

    def dict_choice_types(self, colors: Dict[str, Color], speeds: Dict[str, Speed]):
        """Enums inside a dict: the driver gets the plain value, unchecked. Try colors = {"lid": "Red"}, speeds = {"mix": 3}."""
        return True

    def dict_defaults(self, settings: Dict[str, float] = {"p": 1.0, "i": 0.1},  # noqa: B006 - shown in the form
                      optional_counts: Optional[Dict[str, int]] = None):
        """A dict default is pre-filled, and a blank Optional dict arrives as None, not {}."""
        return True

    def untyped_and_any(self, untyped, any_value: Any = None):
        """Without an annotation or with Any, nothing is checked: the value is guessed from the text."""
        return True

    def multiple_returns(self) -> tuple[int, float, str]:
        """A tuple return generates multiple 'Save item X as' fields."""
        return 1, 3.14, "Success"

    def dict_return(self) -> Dict[str, float]:
        """A dict return: save it, then pass it as #saved to dict_types' gains."""
        return {"p": 1.0, "i": 0.1}


if __name__ == "__main__":
    input_type = InputTypeShowcase()
    import ivoryos
    ivoryos.run(__name__, logger=logger.name)
