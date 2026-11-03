"""Read and change the run conditions of a task still waiting in the queue.

A queued task holds what the execution page submitted: a repeat count, a list of
config entries (typed in or loaded from a spreadsheet), or an optimization
campaign. Nothing has used those values until the task starts, so they can still
be changed. Every change is checked here before it is applied, since a bad value
would otherwise only surface once the run is underway.
"""

import copy

from ivoryos.parsers.bo_campaign import normalize_value
from ivoryos.parsers.type_conversions import convert_config_type
from ivoryos.runtime.safety import check_value, describe, guard
from ivoryos.script import ScriptEditor
from ivoryos.utils.enums import enum_class_from_type

REPEAT = "repeat"
CONFIG = "config"
OPTIMIZER = "optimizer"

DEFAULT_PARAMETER_TYPES = ["range", "choice", "fixed"]
# Parameter kinds whose values are a list of options rather than bounds.
LIST_KINDS = ("choice", "substance")


def task_mode(task):
    """How the task runs, which decides what about it can be edited."""
    if task.get("optimizer_cls") is not None:
        return OPTIMIZER
    if task.get("config") and not task.get("repeat_count"):
        return CONFIG
    return REPEAT


def column_label(arg_type, constraints=None):
    """A config column's type with its unit and range: ``float · optional · mL · 0 to 10``."""
    parts = [type_label(arg_type), "optional" if accepts_none(arg_type) else "",
             *(describe(c) for c in constraints or [])]
    return " · ".join(part for part in parts if part)


def accepts_none(arg_type):
    """Whether a workflow input takes None: its argument is ``Optional[...]`` or ``X | None``.

    Such an input can be left empty in a config row and runs as None. Any input can still be
    given None by typing ``None``.
    """
    types = arg_type if isinstance(arg_type, (list, tuple)) else [arg_type]
    return any(str(t) in ("NoneType", "None") for t in types)


def choices_of(arg_type):
    """The values a choice input takes, for the editors to offer as a dropdown: an Enum's member
    names, as the execution page shows them, or a Literal's values. None for any other input,
    or an Enum that cannot be found, which is then typed in."""
    for item in arg_type if isinstance(arg_type, (list, tuple)) else [arg_type]:
        text = "" if item is None else str(item)
        if text.startswith("Enum:"):
            enum_class = enum_class_from_type(text)
            return [member.name for member in enum_class] if enum_class else None
        if text.startswith("Literal:"):
            return text[len("Literal:"):].split(",")
    return None


def column_choices(fields, arg_types):
    """``{input: [value]}`` for the choice inputs among ``fields`` (see :func:`choices_of`)."""
    choices = {}
    for field in fields:
        options = choices_of((arg_types or {}).get(field))
        if options:
            choices[field] = options
    return choices


def optional_inputs(arg_types):
    """The workflow inputs that can be left empty in a config row (see :func:`accepts_none`)."""
    return [field for field, arg_type in (arg_types or {}).items() if accepts_none(arg_type)]


def text_of(value):
    """A stored value as it reads in an input box."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return repr(value)


def cell_text(value):
    """A config value as it reads in its table cell: None is written ``None``, so it reads back as None."""
    return "None" if value is None else text_of(value)



def _list_text(values):
    return ", ".join(text_of(value) for value in values or [])


def type_label(arg_type):
    """A config argument type as a short hint for a column header."""
    if isinstance(arg_type, (list, tuple)):
        return " | ".join(type_label(item) for item in arg_type if item != "NoneType")
    text = "" if arg_type is None else str(arg_type)
    if text.startswith("Enum:"):
        return text.rsplit(".", 1)[-1]
    if text.startswith("Literal:"):
        return "one of " + text[len("Literal:"):]
    return text


def _schema(task):
    optimizer_cls = task.get("optimizer_cls")
    try:
        return optimizer_cls.get_schema() or {}
    except Exception:
        return {}


def _positive_int(value, label):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number.") from None
    if number < 1:
        raise ValueError(f"{label} must be at least 1.")
    return number


def _convert(text, value_type, label):
    """``text`` as the parameter's value type, the way the optimizer form reads it."""
    try:
        if value_type == "int":
            return int(text)
        if value_type == "float":
            return float(text)
    except ValueError:
        kind = "a whole number" if value_type == "int" else "a number"
        raise ValueError(f"{label} must be {kind}, not '{text}'.") from None
    return text


def _blank(value):
    return value is None or str(value).strip() == ""


def blank_row(values):
    """Whether a config entry is empty, like one added and never filled in."""
    return all(_blank(value) for value in values.values())


def config_field_problems(values, fields, arg_types, limits=None):
    """``{input: why its value cannot run}`` for a config entry, empty if it can run.

    Checked one value at a time, so a table can point at the exact cell rather
    than describe the whole entry. ``limits`` are the instruments' safety
    limits as ``{input: [constraint]}`` (``guard.column_limits``); a value past one cannot run either.
    """
    problems = {key: "Not an input of this workflow." for key in values if key not in arg_types}
    for field in fields:
        if _blank(values.get(field)):
            # an optional input left empty runs as None
            if not accepts_none(arg_types.get(field)):
                problems[field] = "No value."
            continue
        try:
            value = convert_config_type({field: values[field]}, arg_types)[field]
        except Exception as e:
            problems[field] = str(e)
            continue
        for constraint in (limits or {}).get(field, []):
            found = check_value(constraint, value)
            if found:
                shown, reason = found[0]
                problems[field] = f"{shown} {reason}."
                break
    return problems


def config_form_problems(form, fields, arg_types, limits=None):
    """``["Row n, 'input': why", ...]`` for a submitted config table, in table order.

    ``form`` holds the table's cells as ``input[row]`` keys, the way the
    execution page sends them. A row with a value that cannot be converted, or
    one left partly empty, is reported; the runner would otherwise fail the
    first and leave out the second without a word. Empty rows are ignored, and so is an
    empty cell of an input that takes None (see :func:`accepts_none`).
    """
    rows = {}
    for key, value in form.items():
        field, bracket, index = key.partition("[")
        if not bracket:
            continue
        try:
            rows.setdefault(int(index.rstrip("]")), {})[field] = value
        except ValueError:
            continue
    problems = []
    for number in sorted(rows):
        values = rows[number]
        if blank_row(values):
            continue
        for field, reason in config_field_problems(values, fields, arg_types, limits).items():
            problems.append(f"Row {number}, '{field}': {reason}")
    return problems


def config_row_problem(values, fields, arg_types, limits=None):
    """Why a config entry cannot run, or ``None`` if it can.

    ``values`` is the entry as text, typed in or loaded from a spreadsheet. It is
    converted on a copy, the way the runner converts it when the entry starts, and
    checked against ``limits`` like ``config_field_problems``.
    """
    unknown = [key for key in values if key not in arg_types]
    if unknown:
        return f"'{unknown[0]}' is not an input of this workflow."
    missing = [field for field in fields if _blank(values.get(field)) and not accepts_none(arg_types.get(field))]
    if missing:
        names = ", ".join(f"'{field}'" for field in missing)
        return f"no value for {names}."
    try:
        converted = convert_config_type(dict(values), arg_types)
    except Exception as e:
        return str(e)
    for field, constraints in (limits or {}).items():
        for constraint in constraints:
            found = check_value(constraint, converted.get(field))
            if found:
                shown, reason = found[0]
                return f"'{field}' = {shown} {reason}."
    return None


def unset_input_problems(fields, arg_types, rows=None):
    """``["'input' has no value: ...", ...]`` for workflow inputs a run would leave unset.

    An input is a ``#name`` that no step sets, so only the run can give it, by a config row or an
    optimizer parameter. The page asks for it, but a repeat run posted without a table, or an API row
    leaving it out, would call the step with None. ``rows`` are the run's config entries, None if it
    has none. An input that takes None (see :func:`accepts_none`) may be left out.
    """
    required = [field for field in fields if not accepts_none(arg_types.get(field))]
    if not rows:
        return [f"'{field}' has no value: no step in the workflow sets it, so the run has to give it."
                for field in required]
    return [f"Row {number}, '{field}': No value." for number, row in enumerate(rows, start=1)
            for field in required if field not in row]


# --- reading --------------------------------------------------------------


def editable_conditions(task):
    """The task's run conditions in a JSON-safe shape an editor can fill in."""
    mode = task_mode(task)
    conditions = {
        "uid": task.get("uid"),
        "mode": mode,
        "name": task.get("run_name") or "",
        "history": task.get("history") or "",
        "batch_size": task.get("batch_size") or 1,
    }
    if mode == CONFIG:
        conditions.update(_config_view(task))
    else:
        conditions["repeat_count"] = task.get("repeat_count")
    if mode == OPTIMIZER:
        conditions.update(_optimizer_view(task))
    return conditions


def _config_view(task):
    fields, arg_types = ScriptEditor(task["script"]).config("script")
    rows = task.get("config") or []
    # an entry submitted through the API can name inputs the workflow lacks; show
    # them, so the check on save can point at them rather than drop them silently
    extra = []
    for row in rows:
        extra.extend(key for key in row if key not in fields and key not in extra)
    columns = [*fields, *extra]
    limits = guard.column_limits(task["script"])
    return {
        "fields": columns,
        "types": {field: column_label(arg_types.get(field), limits.get(field)) for field in fields},
        # an Enum or Literal input is a dropdown; an optional one can also be None
        "choices": column_choices(fields, arg_types),
        "optional": optional_inputs(arg_types),
        "rows": [[cell_text(row[field]) if field in row else "" for field in columns] for row in rows],
    }


def _optimizer_view(task):
    schema = _schema(task)
    available = list(schema.get("parameter_types") or DEFAULT_PARAMETER_TYPES)

    parameters = []
    for parameter in task.get("parameters") or []:
        kind = parameter.get("type")
        bounds = parameter.get("bounds") or []
        view = {
            "name": parameter.get("name"),
            "type": kind,
            "types": available if kind in available else [*available, kind],
            "value_type": parameter.get("value_type", "float"),
            "min": "", "max": "", "step": "", "choices": "", "value": "",
        }
        if kind == "range":
            view["min"], view["max"] = (text_of(bound) for bound in (bounds + [None, None])[:2])
            view["step"] = text_of(bounds[2]) if len(bounds) > 2 else ""
        elif kind in LIST_KINDS:
            view["choices"] = _list_text(bounds)
        elif kind == "fixed":
            view["value"] = text_of(parameter.get("value"))
        parameters.append(view)

    current = {objective.get("name"): objective for objective in task.get("objectives") or []}
    objectives = []
    for name in [*current, *(name for name in _return_names(task) if name not in current)]:
        objective = current.get(name)
        if objective is None:
            goal = "none"
        else:
            goal = "minimize" if objective.get("minimize", True) else "maximize"
        objectives.append({
            "name": name,
            "goal": goal,
            "early_stop": text_of((objective or {}).get("early_stop")),
        })

    steps = []
    step_specs = schema.get("optimizer_config") or {}
    saved_steps = task.get("steps") or {}
    for key in [*step_specs, *(key for key in saved_steps if key not in step_specs)]:
        spec = step_specs.get(key) or {}
        saved = saved_steps.get(key) or {}
        models = list(spec.get("model") or [])
        if saved.get("model") and saved["model"] not in models:
            models.append(saved["model"])
        steps.append({
            "key": key,
            "label": key.replace("_", " ").capitalize(),
            "model": saved.get("model", ""),
            "models": models,
            "has_num_samples": "num_samples" in spec or "num_samples" in saved,
            "num_samples": text_of(saved.get("num_samples")),
        })

    fields = schema.get("additional_field") or {}
    saved_params = task.get("additional_params") or {}
    additional = []
    for name in [*fields, *(name for name in saved_params if name not in fields)]:
        spec = fields.get(name) or {}
        value = saved_params.get(name)
        additional.append({
            "name": name,
            "type": spec.get("type", ""),
            "options": list(spec.get("options") or []),
            "value": _list_text(value) if isinstance(value, (list, tuple)) else text_of(value),
        })

    return {
        "optimizer": getattr(task.get("optimizer_cls"), "__name__", ""),
        "requires_step": schema.get("supports_continuous") is False,
        "multiple_objectives": schema.get("multiple_objectives", True),
        "supports_constraints": schema.get("supports_constraints", True) is not False,
        "parameters": parameters,
        "objectives": objectives,
        "constraints": list(task.get("constraints") or []),
        "steps": steps,
        "additional_params": additional,
    }


def _return_names(task):
    try:
        _, return_list = ScriptEditor(task["script"]).config_return()
    except Exception:
        return []
    return list(return_list or [])


# --- changing -------------------------------------------------------------


def parse_changes(task, changes, unique_name=None):
    """``{task key: new value}`` for the edited conditions in ``changes``.

    ``unique_name(name, keep)`` turns a new experiment name into one no other run
    uses, ``keep`` being the task's current name, which it may hold on to.
    Without it the name is only made a valid identifier.

    Raises ``ValueError`` with a message for the user when something is not
    usable. Nothing is applied here, so a failed check leaves the task as it was.
    """
    if not isinstance(changes, dict):
        raise ValueError("Expected the edited conditions as an object.")
    mode = task_mode(task)
    updates = {}
    if "name" in changes:
        name = str(changes["name"] or "").strip()
        if not name:
            raise ValueError("Give the experiment a name.")
        if name != task.get("run_name"):
            if unique_name is None:
                updates["run_name"] = ScriptEditor.validate_function_name(name)
            else:
                updates["run_name"] = unique_name(name, task.get("run_name"))
            # the run is saved under run_name, so the queue shows that from now on
            updates["display_name"] = None
    if "batch_size" in changes:
        updates["batch_size"] = _positive_int(changes["batch_size"], "Batch size")
    if mode != CONFIG and "repeat_count" in changes:
        label = "Iterations" if mode == OPTIMIZER else "Repeat count"
        updates["repeat_count"] = _positive_int(changes["repeat_count"], label)
    if mode == CONFIG and "config" in changes:
        updates["config"] = _parse_config(task, changes["config"])
        # the entries are text again, so the runner has to convert them
        updates["compiled"] = False
    if mode == OPTIMIZER:
        updates.update(_parse_optimizer(task, changes))
    return updates


def _parse_config(task, rows):
    if not isinstance(rows, list):
        raise ValueError("Expected the config entries as a list.")
    fields, arg_types = ScriptEditor(task["script"]).config("script")
    limits = guard.column_limits(task["script"])
    entries = []
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Entry {number} is not a set of input values.")
        values = {str(key): "" if value is None else str(value) for key, value in row.items()}
        if blank_row(values):
            continue
        # checked now so a bad value is caught here; the runner converts the
        # text itself when the entry starts
        problem = config_row_problem(values, fields, arg_types, limits)
        if problem:
            raise ValueError(f"Entry {number}: {problem}")
        entries.append(values)
    if not entries:
        raise ValueError("Keep at least one config entry. To drop the task, remove it from the queue.")
    return entries


def _parse_optimizer(task, changes):
    schema = _schema(task)
    updates = {}
    if "parameters" in changes:
        updates["parameters"] = _parse_parameters(task, changes["parameters"], schema)
        problems = guard.check_search_space(task["script"], updates["parameters"])
        if problems:
            raise ValueError(f"Past a limit: {problems[0]}")
    if "objectives" in changes:
        updates["objectives"] = _parse_objectives(task, changes["objectives"], schema)
    if "constraints" in changes:
        constraints = [str(item).strip() for item in changes["constraints"] or [] if not _blank(item)]
        if constraints and schema.get("supports_constraints") is False:
            raise ValueError("This optimizer does not support constraints.")
        updates["constraints"] = constraints
    if "steps" in changes:
        updates["steps"] = _parse_steps(task, changes["steps"], schema)
    if "additional_params" in changes:
        updates["additional_params"] = _parse_additional(task, changes["additional_params"], schema)
    return updates


def _parse_parameters(task, entries, schema):
    by_name = {}
    for entry in entries or []:
        if isinstance(entry, dict):
            by_name[entry.get("name")] = entry
    current = task.get("parameters") or []
    known = {parameter.get("name") for parameter in current}
    unknown = [name for name in by_name if name not in known]
    if unknown:
        raise ValueError(f"'{unknown[0]}' is not a parameter of this campaign.")
    return [_parse_parameter(parameter, by_name[parameter.get("name")], schema)
            if parameter.get("name") in by_name else parameter
            for parameter in current]


def _parse_parameter(current, entry, schema):
    name = current.get("name")
    kind = entry.get("type") or current.get("type")
    available = schema.get("parameter_types") or DEFAULT_PARAMETER_TYPES
    if kind != current.get("type") and kind not in available:
        raise ValueError(f"'{name}': this optimizer does not take '{kind}' parameters.")
    value_type = current.get("value_type", "float")

    # keep anything else the parameter carries, such as settings sent through the API
    parameter = {key: value for key, value in current.items() if key not in ("bounds", "value")}
    parameter["type"] = kind

    if kind == "range":
        number_type = "int" if value_type == "int" else "float"
        if _blank(entry.get("min")) or _blank(entry.get("max")):
            raise ValueError(f"'{name}' needs both a minimum and a maximum.")
        low = _convert(str(entry["min"]).strip(), number_type, f"The minimum of '{name}'")
        high = _convert(str(entry["max"]).strip(), number_type, f"The maximum of '{name}'")
        if low >= high:
            raise ValueError(f"The minimum of '{name}' must be below its maximum.")
        bounds = [low, high]
        if not _blank(entry.get("step")):
            step = _convert(str(entry["step"]).strip(), "float", f"The step of '{name}'")
            if step <= 0:
                raise ValueError(f"The step of '{name}' must be above 0.")
            bounds.append(step)
        elif schema.get("supports_continuous") is False:
            raise ValueError(f"'{name}' needs a step: this optimizer only searches discrete values.")
        parameter["bounds"] = bounds
    elif kind in LIST_KINDS:
        items = [item.strip() for item in str(entry.get("choices") or "").split(",") if item.strip()]
        if not items:
            raise ValueError(f"'{name}' needs at least one choice.")
        item_type = "str" if kind == "substance" else value_type
        parameter["bounds"] = [_convert(item, item_type, f"Each choice of '{name}'") for item in items]
    elif kind == "fixed":
        if _blank(entry.get("value")):
            raise ValueError(f"'{name}' needs a value.")
        parameter["value"] = _convert(str(entry["value"]).strip(), value_type, f"The value of '{name}'")
    else:
        # a kind this editor does not know how to change
        return current
    return parameter


def _parse_objectives(task, entries, schema):
    current = {objective.get("name"): objective for objective in task.get("objectives") or []}
    known = set(current) | set(_return_names(task))
    objectives = []
    for entry in entries or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if name not in known:
            raise ValueError(f"'{name}' is not an output of this workflow.")
        goal = entry.get("goal")
        if goal == "none":
            continue
        if goal not in ("minimize", "maximize"):
            raise ValueError(f"'{name}' must be minimized, maximized or left out.")
        objective = dict(current.get(name) or {"name": name})
        objective["minimize"] = goal == "minimize"
        if _blank(entry.get("early_stop")):
            objective.pop("early_stop", None)
        else:
            objective["early_stop"] = _convert(str(entry["early_stop"]).strip(), "float",
                                               f"The early stop threshold of '{name}'")
        objectives.append(objective)
    if not objectives:
        raise ValueError("Optimize at least one objective.")
    if len(objectives) > 1 and schema.get("multiple_objectives") is False:
        raise ValueError("This optimizer takes a single objective.")
    return objectives


def _parse_steps(task, entries, schema):
    specs = schema.get("optimizer_config") or {}
    steps = copy.deepcopy(task.get("steps") or {})
    for key, entry in (entries or {}).items():
        if key not in specs and key not in steps:
            raise ValueError(f"'{key}' is not a step of this optimizer.")
        if not isinstance(entry, dict):
            continue
        step = steps.setdefault(key, {})
        label = key.replace("_", " ").capitalize()
        if "model" in entry:
            model = entry.get("model") or ""
            models = (specs.get(key) or {}).get("model") or []
            if model and models and model not in models and model != step.get("model"):
                raise ValueError(f"{label}: '{model}' is not a model this optimizer offers.")
            if model:
                step["model"] = model
            else:
                step.pop("model", None)
        if "num_samples" in entry:
            if _blank(entry["num_samples"]):
                step.pop("num_samples", None)
            else:
                samples = _convert(str(entry["num_samples"]).strip(), "int", f"{label} samples")
                if samples < 0:
                    raise ValueError(f"{label} samples cannot be negative.")
                step["num_samples"] = samples
    return steps


def _parse_additional(task, entries, schema):
    known = set(schema.get("additional_field") or {}) | set(task.get("additional_params") or {})
    params = {}
    for name, value in (entries or {}).items():
        if name not in known:
            raise ValueError(f"'{name}' is not a setting of this optimizer.")
        normalized = normalize_value(str(value).strip()) if value is not None else None
        if normalized is not None:
            params[name] = normalized
    return params
