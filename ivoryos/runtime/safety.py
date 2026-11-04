"""Limits on what the instruments may be asked to do, kept outside the drivers.

A driver says what an instrument *can* do. What a lab *allows* it to do is a different
question, and the answer belongs to the bench, not to the driver: this heater block may go to
250 °C, but with these vials nothing above 120; this pump's volumes are in mL. Writing that into
driver code means editing a vendor's package, and parameter names and docstrings are not read
when it matters. So it is data, one file in the data folder (``safety.json``), set from the
shield at the end of each field on the Instruments page:

    {
      "format": "ivoryos-safety/1",
      "limits": [
        {"target": "reactor", "method": "set_temperature", "param": "setpoint", "min": -50, "max": 250, "unit": "°C"},
        {"target": "handler", "method": "place_vial", "param": "station", "allowed": ["rack", "reactor"]}
      ]
    }

- ``target`` is the instrument's name. A property setter is the method ``<name>_(setter)``
  with the field ``value``.
- A limit is a number range, a list of allowed values, a unit, or any of them together. A unit
  is a label for people: nothing is converted, and driver code is never asked to declare one.
- A field whose choices the driver already fixes (an Enum, a Literal, a bool) needs no limit.
- An argument left out of a call is checked at the driver's default.

The format is IvoryOS Next's, so a file of limits can move between the two.

**Where it is enforced.** ``enforce()`` runs immediately before a call reaches a driver, from a
run's step and from the Instruments page alike, so it holds whatever the value's source: a
form, a variable, a config table or an optimizer. In a run a blocked step is a failed step: the
run pauses and a person chooses to retry, continue or stop. ``check_steps`` and friends refuse a
run before anything moves when a value already written into it is out of bounds.

**A file that cannot be read blocks every call** until it is fixed or deleted: starting
unguarded because of a stray comma would be the wrong way to fail. No file at all means
nothing is limited.
"""

import inspect
import json
import os
import threading
from enum import Enum
from typing import Union

try:
    from typing import Literal, get_args, get_origin
except ImportError:  # Python 3.7
    from typing_extensions import Literal, get_args, get_origin

try:
    from types import UnionType  # `float | None`, Python 3.10+
    _UNIONS = (Union, UnionType)
except ImportError:
    _UNIONS = (Union,)

SAFETY_FORMAT = "ivoryos-safety/1"
FILE_NAME = "safety.json"
SETTER_SUFFIX = "_(setter)"
CONSTRAINT_KEYS = ("min", "max", "allowed", "unit")

# the units suggested beside a field's shield, grouped the way a lab thinks of them; anything else
# is typed in and kept as written, since a unit is only a label
UNIT_GROUPS = [
    {"label": "Volume", "units": ["µL", "mL", "L"]},
    {"label": "Mass", "units": ["mg", "g", "kg"]},
    {"label": "Temperature", "units": ["°C", "K"]},
    {"label": "Speed", "units": ["rpm"]},
    {"label": "Length", "units": ["nm", "µm", "mm", "cm"]},
    {"label": "Flow rate", "units": ["µL/s", "mL/min", "L/min"]},
    {"label": "Time", "units": ["s", "min", "h"]},
    {"label": "Percent", "units": ["%"]},
]


class SafetyViolation(Exception):
    """A call or a run the limits do not allow; ``problems`` says why, one line each."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("Safety guard: " + " ".join(self.problems))


def empty_config():
    return {"format": SAFETY_FORMAT, "limits": []}


# --- values -------------------------------------------------------------------------------


def _as_number(value):
    """The value as a number, or None. NaN is not a number here: it compares false against
    every bound, so it would pass any limit."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _fmt(value):
    """A value as a person would write it: 120 rather than 120.0, text in quotes."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:g}" if abs(value) < 1e15 else str(value)
    if isinstance(value, str):
        return f"'{value}'"
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def _is_reference(value):
    """A ``#variable`` the run fills in later; it is checked again once it holds a value."""
    return isinstance(value, str) and value.startswith("#")


def check_value(constraint, value):
    """Why ``value`` breaks ``constraint``: ``[(the value as shown, the reason)]``.

    A list is checked element by element, and so is a set. Nothing given and ``#references`` are
    skipped: the first is somebody else's error, the second is checked once the run has put a value there.
    """
    problems = []
    for item in value if isinstance(value, (list, tuple, set)) else [value]:
        if item is None or item == "" or _is_reference(item):
            continue
        shown = _fmt(item)
        if "min" in constraint or "max" in constraint:
            number = _as_number(item)
            if number is None:
                problems.append((shown, "is not a number, and this field has a limit"))
                continue
            unit = f" {constraint['unit']}" if constraint.get("unit") else ""
            if "min" in constraint and number < constraint["min"]:
                problems.append((shown, f"is below the minimum of {_fmt(constraint['min'])}{unit}"))
            if "max" in constraint and number > constraint["max"]:
                problems.append((shown, f"is above the maximum of {_fmt(constraint['max'])}{unit}"))
        if constraint.get("allowed") is not None:
            allowed = [str(choice) for choice in constraint["allowed"]]
            if str(item) not in allowed:
                problems.append((shown, "is not allowed here (allowed: " + ", ".join(allowed) + ")"))
    return problems


def describe(constraint):
    """A limit as a short hint beside a field: ``mL · 0 to 10``."""
    parts = []
    if constraint.get("unit"):
        parts.append(constraint["unit"])
    low, high = constraint.get("min"), constraint.get("max")
    if low is not None and high is not None:
        parts.append(f"{_fmt(low)} to {_fmt(high)}")
    elif low is not None:
        parts.append(f"at least {_fmt(low)}")
    elif high is not None:
        parts.append(f"at most {_fmt(high)}")
    if constraint.get("allowed") is not None:
        parts.append("one of " + ", ".join(str(choice) for choice in constraint["allowed"]))
    return " · ".join(parts)


def _tidy_number(number):
    return int(number) if float(number).is_integer() else number


# --- instruments --------------------------------------------------------------------------


def instrument_name(key):
    """The name a limit's ``target`` uses for a step's instrument: ``deck.reactor`` is
    ``reactor``. ``None`` for what is not an instrument, like building blocks."""
    if not key or not isinstance(key, str):
        return None
    if key.startswith("deck."):
        return key[len("deck."):]
    if "." in key:
        return None
    return key


def _live_object(name):
    from ivoryos.runtime.state import GlobalState

    state = GlobalState()
    if state.deck is not None and hasattr(state.deck, name):
        return getattr(state.deck, name)
    return (state.defined_variables or {}).get(name)


def _member_signature(obj, method):
    """The signature of a method, or of a property setter's ``(value)``; None if unknown."""
    if obj is None:
        return None
    if method.endswith(SETTER_SUFFIX):
        prop = getattr(type(obj), method[: -len(SETTER_SUFFIX)], None)
        if not isinstance(prop, property):
            return None
        try:
            getter = inspect.signature(prop.fget) if prop.fget else None
        except (TypeError, ValueError):
            getter = None
        annotation = getter.return_annotation if getter else inspect.Signature.empty
        value = inspect.Parameter("value", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                  annotation=inspect.Parameter.empty if annotation is inspect.Signature.empty else annotation)
        return inspect.Signature([value])
    member = getattr(type(obj), method, None)
    if member is None or not callable(member):
        return None
    try:
        return inspect.signature(member)
    except (TypeError, ValueError):
        return None


def field_kind(annotation):
    """What a field's limit can say: ``number`` (a range and a unit), ``text`` (allowed
    values), ``any`` (either, for an untyped field) or ``fixed`` (choices the driver already
    fixes, an Enum, a Literal or a bool, so there is nothing to add)."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return "any"
    if isinstance(annotation, str):  # a postponed annotation, or a type saved for offline design
        if annotation in ("int", "float"):
            return "number"
        if annotation == "str":
            return "text"
        if annotation == "bool" or annotation.startswith(("Enum:", "Literal:")):
            return "fixed"
        return "any"
    if annotation is bool:
        return "fixed"
    if annotation in (int, float):
        return "number"
    if annotation is str:
        return "text"
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return "fixed"
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Literal:
        return "fixed"
    if origin in _UNIONS:
        kinds = {field_kind(arg) for arg in args if arg is not type(None)}
        return kinds.pop() if len(kinds) == 1 else "any"
    if origin in (list, tuple, set) and args:
        return field_kind(args[0])  # each element is checked
    return "any"


def guarded_fields(functions):
    """``{method: {param: kind}}``: the fields of one instrument a limit can be set on,
    property setters included. Choices the driver fixes are left out."""
    fields = {}
    for name, info in (functions or {}).items():
        if not isinstance(info, dict):
            continue
        signature = info.get("signature")
        if info.get("is_property"):
            if not info.get("has_setter"):
                continue
            annotation = signature.return_annotation if signature else inspect.Signature.empty
            params = [("value", inspect.Parameter.empty if annotation is inspect.Signature.empty else annotation)]
            name = f"{name}{SETTER_SUFFIX}"
        elif isinstance(signature, inspect.Signature):
            params = [(param.name, param.annotation) for param in signature.parameters.values()
                      if param.name != "self" and param.kind not in (param.VAR_POSITIONAL, param.VAR_KEYWORD)]
        else:
            continue
        kinds = {param: field_kind(annotation) for param, annotation in params}
        kinds = {param: kind for param, kind in kinds.items() if kind != "fixed"}
        if kinds:
            fields[name] = kinds
    return fields


# --- the file -----------------------------------------------------------------------------


def validate(raw):
    """``(config, errors)`` for a configuration as read or as about to be saved.

    ``errors`` keep it from being used; each is ``{"message", "method", "param"}``, the last
    two when the error is about one limit.
    """
    errors = []
    config = empty_config()
    if not isinstance(raw, dict):
        return config, [{"message": "The limits must be a JSON object."}]
    if raw.get("format") not in (None, SAFETY_FORMAT):
        errors.append({"message": f"Unknown format '{raw.get('format')}'; expected '{SAFETY_FORMAT}'."})

    limits = raw.get("limits") or []
    if not isinstance(limits, list):
        errors.append({"message": "'limits' must be a list."})
        limits = []
    seen = set()
    for limit in limits:
        if not isinstance(limit, dict):
            errors.append({"message": "A limit must be an object."})
            continue
        target, method, param = (str(limit.get(key) or "").strip() for key in ("target", "method", "param"))
        if not (target and method and param):
            errors.append({"message": "A limit needs an instrument, a method and a field."})
            continue
        problems = []
        entry = {"target": target, "method": method, "param": param}
        for bound in ("min", "max"):
            if limit.get(bound) in (None, ""):
                continue
            number = _as_number(limit[bound])
            if number is None:
                problems.append(f"the {bound}imum must be a number, not {_fmt(limit[bound])}.")
            else:
                entry[bound] = _tidy_number(number)
        if "min" in entry and "max" in entry and entry["min"] > entry["max"]:
            problems.append(f"the minimum ({_fmt(entry['min'])}) is above the maximum ({_fmt(entry['max'])}).")
        if limit.get("allowed") not in (None, ""):
            allowed = limit["allowed"]
            if not isinstance(allowed, list) or not allowed:
                problems.append("'allowed' must be a list with at least one value.")
            else:
                entry["allowed"] = allowed
        if str(limit.get("unit") or "").strip():
            entry["unit"] = str(limit["unit"]).strip()
        if not problems and not any(key in entry for key in CONSTRAINT_KEYS):
            problems.append("sets nothing: give it a minimum, a maximum, allowed values or a unit.")
        if not problems and (target, method, param) in seen:
            problems.append("has two limits. Keep one.")
        if problems:
            errors.extend({"message": f"{target}.{method}.{param}: {problem}", "method": method, "param": param}
                          for problem in problems)
            continue
        seen.add((target, method, param))
        config["limits"].append(entry)
    return config, errors


class Guard:
    """The limits in force, read from ``safety.json`` and read again when the file changes."""

    def __init__(self, path=None):
        self.path = path
        self._lock = threading.Lock()
        self._mtime = None
        self.config = empty_config()
        self.load_error = None

    def configure(self, path):
        with self._lock:
            self.path = path
            self._mtime = None
            self.config, self.load_error = empty_config(), None

    def _refresh(self):
        """Read the file again if it changed, so a hand edit applies without a restart."""
        if not self.path:
            return
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            mtime = None
        with self._lock:
            if mtime == self._mtime:
                return
            self._mtime = mtime
            if mtime is None:
                self.config, self.load_error = empty_config(), None
                return
            try:
                with open(self.path, encoding="utf-8") as file:
                    config, errors = validate(json.load(file))
            except Exception as e:
                self.load_error = f"{self.path} cannot be read: {e}"
                return
            if errors:
                self.load_error = f"{self.path} has errors: " + "; ".join(e["message"] for e in errors)
                return
            self.config, self.load_error = config, None

    # --- what applies -----------------------------------------------------------------------

    def limits_for(self, instrument_key):
        """``{method: {param: constraint}}`` set for one instrument."""
        self._refresh()
        name = instrument_name(instrument_key)
        found = {}
        for limit in self.config["limits"]:
            if name is not None and limit["target"] == name:
                found.setdefault(limit["method"], {})[limit["param"]] = {
                    key: limit[key] for key in CONSTRAINT_KEYS if key in limit}
        return found

    def constraints(self, instrument_key, method):
        """``{param: constraint}`` for one method of one instrument."""
        return self.limits_for(instrument_key).get(method, {})

    def form_limits(self, instrument_key, functions):
        """``{method: {param: constraint}}`` to show beside an instrument's fields."""
        limits = self.limits_for(instrument_key)
        shown = {}
        for method, info in (functions or {}).items():
            key = f"{method}{SETTER_SUFFIX}" if isinstance(info, dict) and info.get("is_property") else method
            if key in limits:
                shown[key] = limits[key]
        return shown

    # --- calls ------------------------------------------------------------------------------

    def check_call(self, instrument_key, method, args):
        """Why the call cannot go ahead, one line per problem; empty when it can."""
        self._refresh()
        if self.load_error:
            return [f"{self.load_error}. Every call is blocked until the file is fixed or deleted."]
        constraints = self.constraints(instrument_key, method)
        if not constraints:
            return []
        name = instrument_name(instrument_key)
        signature = _member_signature(_live_object(name), method)
        problems = []
        for param, constraint in constraints.items():
            if param in args:
                value = args[param]
            elif signature is not None and param in signature.parameters \
                    and signature.parameters[param].default is not inspect.Parameter.empty:
                value = signature.parameters[param].default
            else:
                continue
            for shown, reason in check_value(constraint, value):
                problems.append(f"{name}.{method}: {param} = {shown} {reason}.")
        return problems

    def enforce(self, instrument_key, method, args):
        """Raise ``SafetyViolation`` if the limits do not allow this call."""
        problems = self.check_call(instrument_key, method, args)
        if problems:
            raise SafetyViolation(problems)

    # --- runs -------------------------------------------------------------------------------

    @staticmethod
    def _deck_steps(script):
        for section in ("prep", "script", "cleanup"):
            for step in (script.script_dict or {}).get(section) or []:
                if instrument_name(step.get("instrument")) is not None and isinstance(step.get("args"), dict):
                    yield step

    def check_steps(self, script):
        """Values written into the workflow's steps that the limits do not allow."""
        self._refresh()
        if self.load_error:
            return [f"{self.load_error}."]
        problems = []
        for step in self._deck_steps(script):
            name = instrument_name(step["instrument"])
            for param, constraint in self.constraints(step["instrument"], step.get("action", "")).items():
                value = step["args"].get(param)
                if isinstance(value, dict):  # a variable, filled in during the run
                    continue
                for shown, reason in check_value(constraint, value):
                    problems.append(f"Step {step.get('id', '?')}, {name}.{step.get('action')}: "
                                    f"{param} = {shown} {reason}.")
        return problems

    def column_limits(self, script):
        """``{input: [constraint]}``: the limits on each of the workflow's inputs, through the
        steps it is passed to, for config tables and an optimizer's search space."""
        self._refresh()
        if self.load_error:
            return {}
        columns = {}
        for step in self._deck_steps(script):
            constraints = self.constraints(step["instrument"], step.get("action", ""))
            for param, value in step["args"].items():
                if _is_reference(value) and param in constraints:
                    found = dict(constraints[param])
                    found["source"] = f"{instrument_name(step['instrument'])}.{step.get('action')}.{param}"
                    columns.setdefault(value[1:], []).append(found)
        return columns

    def check_rows(self, script, rows):
        """Config rows (``[{input: value}]``) with a value the limits do not allow."""
        columns = self.column_limits(script)
        problems = []
        for number, row in enumerate(rows or [], start=1):
            for field, constraints in columns.items():
                for constraint in constraints:
                    for shown, reason in check_value(constraint, (row or {}).get(field)):
                        problems.append(f"Row {number}, '{field}': {shown} {reason}.")
        return problems

    def check_search_space(self, script, parameters):
        """An optimizer's parameters whose range or choices reach past a limit."""
        columns = self.column_limits(script)
        problems = []
        for parameter in parameters or []:
            constraints = columns.get(parameter.get("name"), [])
            if not constraints:
                continue
            kind = parameter.get("type")
            if kind == "range":
                values = list(parameter.get("bounds") or [])[:2]
            elif kind == "fixed":
                values = [parameter.get("value")]
            else:
                values = list(parameter.get("bounds") or [])
            for constraint in constraints:
                for shown, reason in check_value(constraint, values):
                    problems.append(f"{parameter['name']}: {shown} {reason} ({constraint['source']}).")
        return problems

    # --- the shields on the Instruments page --------------------------------------------------

    def field_guards(self, instrument_key, functions):
        """``{method: {param: {"kind", "limit"}}}`` for each field's shield on the Instruments
        page: what its limit can say, and the limit set, if any."""
        limits = self.limits_for(instrument_key)
        return {method: {param: {"kind": kind, "limit": limits.get(method, {}).get(param, {})}
                         for param, kind in kinds.items()}
                for method, kinds in guarded_fields(functions).items()}

    def save_limit(self, instrument_key, method, param, constraint):
        """Set one field's limit, or remove it when ``constraint`` sets nothing; the errors, in
        which case nothing is written."""
        self._refresh()
        if self.load_error:
            return [{"message": f"{self.load_error}. Fix or delete the file before saving here."}]
        name = instrument_name(instrument_key)
        if name is None or not method or not param:
            return [{"message": "This limit cannot be saved."}]
        constraint = constraint if isinstance(constraint, dict) else {}
        key = (name, method, param)
        limits = [limit for limit in self.config["limits"]
                  if (limit["target"], limit["method"], limit["param"]) != key]
        if any(constraint.get(part) not in (None, "", []) for part in CONSTRAINT_KEYS):
            limits.append({"target": name, "method": method, "param": param,
                           **{part: constraint[part] for part in CONSTRAINT_KEYS if part in constraint}})
        config, errors = validate({"format": SAFETY_FORMAT, "limits": limits})
        if errors:
            return errors
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temporary = f"{self.path}.tmp"
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=2, ensure_ascii=False)
        os.replace(temporary, self.path)
        with self._lock:
            self._mtime = None  # read it again on the next check
        return []


guard = Guard()
