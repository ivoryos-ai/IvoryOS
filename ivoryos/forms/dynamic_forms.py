import ast
import json
import sys
import uuid
from enum import Enum, EnumMeta
from typing import Union, Any
import inspect
import importlib

from wtforms.fields.choices import SelectField
from wtforms.fields.core import Field
from wtforms.validators import InputRequired, ValidationError, Optional
from wtforms.widgets.core import TextInput, TextArea
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, HiddenField, BooleanField, IntegerField
from wtforms.form import BaseForm

from ivoryos.script import Script, ScriptEditor, ScriptRenderer
from ivoryos.script.compatibility import check_action, current_reference
from ivoryos.runtime.state import GlobalState

from ivoryos.parsers.introspection import get_return_type
from ivoryos.parsers.structured_types import (
    find_structured_type, format_structured_value, has_variables, is_dict_annotation, is_variable, load_structured_type,
    parse_structured_value, render_python, structured_schema, structured_template, to_bool, to_dict,
    validate_structured_value,
)
from ivoryos.runtime.safety import describe as describe_limit, guard
from ivoryos.utils.enums import _UNIONS, enum_class_of, find_member

try:
    from typing import get_origin, get_args
except ImportError:
    # For Python versions = 3.7, use typing_extensions
    from typing_extensions import get_origin, get_args


# ---------------------------------------------------------------------------
# Reserved form field names
#
# Field names on a dynamic form come from user method signatures, so they can
# collide with names the form itself needs. There are two distinct kinds of
# collision, handled by two different mechanisms:
#
# 1. Parameter vs. the form's own API (`validate`, `process`, `meta`,
#    `arg_types`, `filter_<field>`, ...). One field, one non-field attribute.
#    Handled by `DynamicBaseForm` + `safe_field_name` below, which bind the
#    field under a prefixed *attribute* while keeping the parameter name as the
#    field's HTML name. See issue #183.
#
# 2. Parameter vs. a step metadata widget (the batch toggle, the hidden field
#    naming the workflow). Two *real fields* competing for one HTML name, so
#    renaming the attribute is not enough - both would still submit under the
#    same name. The metadata field's submitted name has to move instead, which
#    is what the constants below do. See issue #185.
#
# The `ivoryos_` prefix is reserved for (2); do not add these names to
# `DynamicBaseForm` as reserved attributes, that would reintroduce the
# duplicate-input problem.
#
# The *step dict* keys stay unprefixed (`batch_action`, `consolidate_batch_args`),
# so saved scripts and the ScriptEditor API are unaffected.
#
# Reserved names that are deliberately NOT namespaced:
#   `hidden_name`, `hidden_wait`, `override_busy`
#       Part of the public HTTP API - the generated remote proxy client posts
#       `{"hidden_name": ...}` (see services/client_proxy.py), so renaming them
#       would break already-generated clients. A parameter with one of these
#       names will be dropped.
#   `builtin_name`, `variable_type`
#       Only ever set on builtin logic forms (if/while/wait/variable/...),
#       which have a fixed field set and no user signature. Unreachable.
#   `return`
#       A Python keyword, so it can never be a parameter name.
#   `return_0`, `return_1`, ...
#       Only added for methods annotated with a tuple return of arity > 1, and
#       `extract_return_variables` consumes any `return_<digits>` key. A
#       parameter named `return_0` on such a method would be swallowed.
# ---------------------------------------------------------------------------
BATCH_ACTION_FIELD = "ivoryos_batch_action"
CONSOLIDATE_ARGS_FIELD = "ivoryos_consolidate_batch_args"
WORKFLOW_NAME_FIELD = "ivoryos_workflow_name"


VARIABLE_TYPE_CHOICES = [('int', 'Integer'), ('float', 'Float'), ('str', 'String'), ('bool', 'Boolean')]

def is_list_type(ann):
    if ann is list: return True
    try:
        origin = get_origin(ann)
    except:
        origin = getattr(ann, '__origin__', None)

    if origin is list: return True

    # String fallback
    s = str(ann).lower()
    if s.startswith('list[') or s == 'list': return True
    if 'typing.list' in s: return True

    # Check Union
    if origin in _UNIONS:
         args = get_args(ann)
         return any(is_list_type(arg) for arg in args)

    return False

global_state = GlobalState()

def find_variable(data, script):
    """
    find user defined variables and return values in the script:Script
    :param data: string of input variable name
    :param script:Script object
    """
    variables: dict[str, str] = ScriptEditor(script).get_variables()
    for variable_name, variable_type in variables.items():
        if variable_name == data:
            return data, variable_type  # variable_type int float str or "function_output"
    return None, None


class VariableOrStringField(Field):
    widget = TextInput()

    def __init__(self, label='', validators=None, script=None, **kwargs):
        super(VariableOrStringField, self).__init__(label, validators, **kwargs)
        self.script = script

    def process_formdata(self, valuelist):
        if valuelist:
            if not self.script.editing_type == "script" and valuelist[0].startswith("#"):
                raise ValueError(self.gettext("Variable is not supported in prep/cleanup"))
            self.data = valuelist[0]

    def _value(self):
        if self.script:
            variable, variable_type = find_variable(self.data, self.script)
            if variable:
                return variable
        # print("_value", self.data, type(self.data))
        return str(self.data) if self.data else ''


class VariableOrFloatField(Field):
    widget = TextInput()

    def __init__(self, label='', validators=None, script=None, **kwargs):
        super(VariableOrFloatField, self).__init__(label, validators, **kwargs)
        self.script = script

    def _value(self):
        if self.script:
            variable, variable_type = find_variable(self.data, self.script)
            if variable:
                return variable

        if self.raw_data:
            return self.raw_data[0]
        if self.data is not None:
            return str(self.data)
        return ""

    def process_formdata(self, valuelist):
        if not valuelist:
            return
        elif valuelist[0].startswith("#"):
            if not self.script.editing_type == "script":
                raise ValueError(self.gettext("Variable is not supported in prep/cleanup"))
            self.data = valuelist[0]
            return
        try:
            if self.script:
                try:
                    variable, variable_type = find_variable(valuelist[0], self.script)
                    if variable:
                        if not variable_type == "function_output":
                            if variable_type not in ["float", "int"]:
                                raise ValueError("Variable is not a valid float")
                        self.data = variable
                        return
                except ValueError:
                    pass
            self.data = float(valuelist[0])
        except ValueError as exc:
            self.data = None
            raise ValueError(self.gettext("Not a valid float value.")) from exc


class VariableOrIntField(Field):
    widget = TextInput()

    def __init__(self, label='', validators=None, script=None, **kwargs):
        super(VariableOrIntField, self).__init__(label, validators, **kwargs)
        self.script = script

    def _value(self):
        if self.script:
            variable, variable_type = find_variable(self.data, self.script)
            if variable:
                return variable

        if self.raw_data:
            return self.raw_data[0]
        if self.data is not None:
            return str(self.data)
        return ""

    def process_formdata(self, valuelist):
        if not valuelist:
            return
        if self.script:
            variable, variable_type = find_variable(valuelist[0], self.script)
            if variable:
                try:
                    if not variable_type == "function_output":
                        if not variable_type == "int":
                            raise ValueError("Not a valid integer value")
                    self.data = str(variable)
                    return
                except ValueError:
                    pass
        if valuelist[0].startswith("#"):
            if not self.script.editing_type == "script":
                raise ValueError(self.gettext("Variable is not supported in prep/cleanup"))
            self.data = valuelist[0]
            return
        if valuelist[0] == "":
            # print("empty input", valuelist)
            self.data = None
            return
        try:
            self.data = int(valuelist[0])
        except ValueError as exc:
            self.data = None
            raise ValueError(self.gettext("Not a valid integer value.")) from exc


class BoolCheckboxField(BooleanField):
    """The Instruments page's bool: a ticked box sends ``y``. A script posting ``data={"value": False}`` sends
    the text ``False``, which WTForms read as True."""
    false_values = (False, "false", "False", "")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = "BooleanField"  # the templates draw a checkbox for this type


class VariableOrBoolField(Field):
    widget = TextInput()
    false_values = (False, "false", "", "False", "f", "F", "n")

    def __init__(self, label='', validators=None, script=None, **kwargs):
        super(VariableOrBoolField, self).__init__(label, validators, **kwargs)
        self.script = script

    def process_data(self, value):

        if self.script:
            variable, variable_type = find_variable(value, self.script)
            if variable:
                if not variable_type == "function_output":
                    raise ValueError("Not accepting boolean variables")
                return variable
        if isinstance(value, str) and value.startswith("#"):
            self.data = value
            return value
        # Known bug, left for now: None is not a false value, so an untouched `Optional[bool] = None`
        # is prefilled as True and a step saved without touching it calls the driver with True.
        if value in self.false_values:
            self.data = False
        else:
            self.data = True
        return None

    def process_formdata(self, valuelist):
        # todo
        # print(valuelist)
        if not valuelist or not type(valuelist) is list:
            self.data = False
        else:
            value = valuelist[0] if type(valuelist) is list else valuelist
            if value.startswith("#"):
                if not self.script.editing_type == "script":
                    raise ValueError(self.gettext("Variable is not supported in prep/cleanup"))
                self.data = valuelist[0]
                return
            variable, _ = find_variable(value, self.script) if self.script else (None, None)
            if variable:
                self.data = variable
                return
            try:
                self.data = to_bool(value)
            except ValueError as exc:
                self.data = None
                raise ValueError(self.gettext("Not a valid boolean value: use True or False.")) from exc

    def _value(self):

        if self.script:
            variable, variable_type = find_variable(self.raw_data, self.script)
            if variable:
                return variable

        if self.raw_data:
            return str(self.raw_data[0])
        return str(self.data)


class FlexibleEnumField(StringField):
    def __init__(self, label=None, validators=None, choices=None, script=None, **kwargs):
        super().__init__(label, validators, **kwargs)
        self.script = script
        self.enum_class = self._resolve_enum(choices)
        self.choices = [e.name for e in self.enum_class]

    def _resolve_enum(self, annotation):
        """Extract Enum from Enum or Optional[Enum]"""
        enum_class = enum_class_of(annotation)
        if enum_class is None:
            raise TypeError(f"FlexibleEnumField expected Enum or Optional[Enum], got {annotation!r}")
        return enum_class

    def _value(self):
        """The member's key, whether a key or (in a step saved before keys) a value was stored;
        empty for None rather than 'None'."""
        if self.data is None:
            return ''
        member = find_member(self.enum_class, self.data)
        return member.name if member is not None else str(self.data)

    def process_formdata(self, valuelist):
        # A step keeps the member's key, however it was given: the key from the form, or the value
        # typed in or sent as JSON by the downloaded proxy. See ivoryos.utils.enums.
        if valuelist:
            key = valuelist[0]
            # Treat empty string or "None" as null value
            if key in ("", None, "None"):
                self.data = None
                return

            member = find_member(self.enum_class, key)
            if member is not None:
                self.data = member.name
            elif not isinstance(key, str):
                raise ValueError(self.gettext("Not a valid choice"))
            elif key.startswith("#"):
                # Script variable reference — only valid when a script context exists
                if self.script is None or not self.script.editing_type == "script":
                    raise ValueError(self.gettext("Variable is not supported in prep/cleanup"))
                self.data = key
            else:
                # not a key or a value: a variable set earlier in the script, if there is one
                # (script is None on the Instruments page)
                if self.script is not None:
                    variable, variable_type = find_variable(key, self.script)
                    if variable:
                        self.data = variable
                        return
                raise ValidationError(f"Invalid choice: '{key}'. Must match one of {list(self.enum_class.__members__.keys())}")


class FlexibleLiteralField(StringField):
    def __init__(self, label=None, validators=None, choices=None, script=None, **kwargs):
        super().__init__(label, validators, **kwargs)
        self.script = script
        self.choices = [str(c) for c in (choices or [])]

    def _value(self):
        if self.data is None:
            return ''
        return str(self.data)

    def process_formdata(self, valuelist):
        if valuelist:
            key = valuelist[0]
            if key in ("", None, "None"):
                self.data = None
                return

            # the option as text, also from a JSON body, which Flask-WTF hands every form on the page
            if str(key) in self.choices:
                self.data = str(key)
            elif not isinstance(key, str):
                raise ValueError(self.gettext("Not a valid choice"))
            elif key.startswith("#"):
                if self.script is None or not self.script.editing_type == "script":
                    raise ValueError(self.gettext("Variable is not supported in prep/cleanup"))
                self.data = key
            else:
                if self.script is not None:
                    variable, variable_type = find_variable(key, self.script)
                    if variable:
                        self.data = variable
                        return
                raise ValidationError(f"Invalid choice: '{key}'. Must match one of {self.choices}")


class StructuredField(Field):
    """
    A dict argument, edited as JSON or a Python literal (as a table of keys and values in the browser).
    ``#variables`` are allowed for the whole value or for any value inside it.
    """
    widget = TextArea()

    def __init__(self, label='', validators=None, annotation=None, script=None, **kwargs):
        super(StructuredField, self).__init__(label, validators, **kwargs)
        self.annotation = annotation
        self.script = script

    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        if self.data is None:
            return ""
        if isinstance(self.data, str):
            return self.data
        return format_structured_value(self.data)

    def process_formdata(self, valuelist):
        if not valuelist:
            return
        value = valuelist[0]  # text from a form, or already a dict/list from a JSON request
        if value is None or isinstance(value, str) and value.strip() in ("", "None"):
            self.data = None
            return
        try:
            if isinstance(value, str) and not is_variable(value.strip()):
                value = parse_structured_value(value, self.annotation)
            elif isinstance(value, str):
                value = value.strip()
            validate_structured_value(value, self.annotation)
            # a key or value that is not its type is refused here; the step keeps what was typed and the
            # driver gets it cast (to_dict)
            to_dict(value, self.annotation)
        except ValueError as exc:
            self.data = None
            raise ValueError(str(exc)) from exc
        if has_variables(value) and self.script is None:
            raise ValueError(self.gettext("Variables are only supported when designing a workflow"))
        if has_variables(value) and not self.script.editing_type == "script":
            raise ValueError(self.gettext("Variable is not supported in prep/cleanup"))
        self.data = value


STRUCTURED_PLACEHOLDER = 'JSON, e.g. {"key": value}; #variables allowed for any value'


def _is_output_reference(value):
    """``{"name": "function_output"}``: a step argument that is the output of an earlier step, not a dict value."""
    return isinstance(value, dict) and len(value) == 1 and next(iter(value.values())) == "function_output"


def _structured_render_kwargs(value, annotation=None):
    rows = 1 if value is None or isinstance(value, str) else len(format_structured_value(value).splitlines())
    # monospace and unwrapped, so the JSON keeps its layout in narrow cards
    render_kwargs = {"rows": min(max(rows, 2), 20), "spellcheck": "false", "wrap": "off",
                     "style": "font-family: var(--bs-font-monospace, monospace); font-size: .85em;"}
    if annotation is not None:
        # the field layout, so structured_editor.js can show inputs and tables over the JSON
        render_kwargs["data-schema"] = json.dumps(structured_schema(annotation))
    return render_kwargs


class DynamicBaseForm(FlaskForm):
    """
    Base form for dynamic forms, whose field names come from user method signatures.

    A parameter name is not allowed to take over part of the form's own API:

    - WTForms reads ``filter_<field>`` and ``validate_<field>`` attributes as inline hooks for
      ``<field>``, so a parameter named ``filter_count`` next to ``count`` would be called
      as a filter/validator for the latter. A field is never a hook.
    - A parameter named after a form attribute (``validate``, ``process``, ``arg_types``, ...)
      is bound under a safe attribute name by :func:`safe_field_name`, keeping the parameter
      name as the field's HTML name.
    """

    # Names a parameter must not take over. Declaring them here is what reserves them:
    # :func:`safe_field_name` finds them with ``hasattr`` and renames the colliding field.
    arg_types = {}        # default; replaced per form class by the factories, read by templates
    has_kwargs = False    # default; replaced per form class by create_form_for_method
    original_name = None  # default; replaced per form class by create_workflow_forms
    meta = None           # value unused: WTForms replaces it on every instance
    form_errors = ()      # value unused: WTForms replaces it on every instance

    def _hook_shadowing_fields(self, prefix):
        """field names that WTForms would mistake for a ``<prefix>_<field>`` hook of another field"""
        return [name for name in self._fields
                if name.startswith(f"{prefix}_") and name[len(prefix) + 1:] in self._fields]

    def process(self, *args, **kwargs):
        # inline filters are looked up on the instance, hide the colliding fields while processing
        shadowing = {name: getattr(self, name) for name in self._hook_shadowing_fields("filter")}
        for name in shadowing:
            setattr(self, name, None)
        try:
            super().process(*args, **kwargs)
        finally:
            for name, field in shadowing.items():
                setattr(self, name, field)

    def validate(self, extra_validators=None):
        # inline validators are looked up on the class, where the colliding fields are still unbound
        extra = dict(extra_validators) if extra_validators else {}
        for name in self._fields:
            inline = getattr(type(self), f"validate_{name}", None)
            if inline is not None and not hasattr(inline, "_formfield"):
                extra.setdefault(name, []).append(inline)
        return BaseForm.validate(self, extra)

    @property
    def errors(self):
        # report errors under the parameter name, which is what routes and templates use
        errors = {field.name: field.errors for field in self._fields.values() if field.errors}
        if self.form_errors:
            errors[None] = self.form_errors
        return errors


def safe_field_name(param_name: str, taken=()):
    """
    Python attribute name to bind a parameter's field under.

    Parameter names come from user code and can collide with the form's own attributes, e.g. a
    parameter named ``validate`` would shadow ``Form.validate()`` and make validation a no-op.
    Colliding names are prefixed; the field keeps ``param_name`` as its HTML name, so
    ``field.name``, request data and rendering are unaffected.

    :param param_name: the method parameter name
    :param taken: attribute names already bound on the form
    """
    def is_reserved(name):
        # WTForms skips underscore-prefixed class attributes when collecting fields, so such a
        # parameter would be dropped entirely; it also keeps internals like ``_fields`` safe.
        # ``csrf_token`` is not reserved: it is a field rather than an attribute, so renaming a
        # parameter of that name would submit two inputs called ``csrf_token`` and break CSRF.
        return name.startswith("_") or hasattr(DynamicBaseForm, name)

    safe_name = param_name
    while is_reserved(safe_name) or safe_name in taken:
        safe_name = f"param_{safe_name}"
    return safe_name


def parse_annotation(annotation):
    """
    Given a type annotation, return:
    - a list of all valid types (excluding NoneType)
    - a boolean indicating if the value can be None (optional)
    """
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is Any:
        return [str], True  # fallback: accept any string, optional

    if origin in _UNIONS:
        types = list(set(args))
        is_optional = type(None) in types
        non_none_types = [t for t in types if t is not type(None)]
        return non_none_types, is_optional

    # Not a Union, just a regular type
    return [annotation], False

def create_form_for_method(method, autofill, script=None, design=True, limits=None):
    """
    Create forms for each method or signature
    :param method: dict(docstring, signature)
    :param autofill:bool if autofill is enabled
    :param script:Script object
    :param design: if design is enabled
    :param limits: {param: constraint}, the instrument's safety limits, shown beside each field
    """

    class DynamicForm(DynamicBaseForm):
        pass

    annotation_mapping = {
        int: (VariableOrIntField if design else IntegerField, 'Enter integer value'),
        float: (VariableOrFloatField if design else FloatField, 'Enter numeric value'),
        str: (VariableOrStringField if design else StringField, 'Enter text'),
        bool: (VariableOrBoolField if design else BoolCheckboxField, 'Empty for false')
    }
    sig = method if type(method) is inspect.Signature else inspect.signature(method)

    attr_names = set()
    has_kwargs = False
    for param in sig.parameters.values():
        if param.name == 'self':
            continue
        
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            has_kwargs = True
            continue

        # formatted_param_name = format_name(param.name)

        default_value = None
        if autofill:
            default_value = f'#{param.name}'
        else:
            if param.default is not param.empty:
                if isinstance(param.default, Enum):
                    default_value = param.default.name
                else:
                    default_value = param.default

        annotations, optional = parse_annotation(param.annotation)

        field_kwargs = {
            "label": param.name,
            "default": default_value,
            "validators": [InputRequired()] if not (optional or param.default is None) else [Optional()]
        }
        
        if optional or param.default is None:
            field_kwargs["filters"] = [lambda x: x if x != '' else None]

        extra_render_kwargs = {}
        if is_dict_annotation(param.annotation):
            field_class = StructuredField
            placeholder_text = STRUCTURED_PLACEHOLDER
            if default_value is None and param.default is param.empty:
                # a required dict starts as an empty one, ready for entries
                field_kwargs["default"] = structured_template(param.annotation)
            extra_kwargs = {"annotation": param.annotation}
            extra_render_kwargs = _structured_render_kwargs(field_kwargs["default"], param.annotation)

        elif _is_enum_type(param.annotation):
            enum_class = _unwrap_enum_type(param.annotation)
            field_class = FlexibleEnumField
            placeholder_text = f"Choose or type a value for {enum_class.__name__}"

            extra_kwargs = {"choices": param.annotation}

        elif _is_literal_type(param.annotation):
            literal_args = _unwrap_literal_args(param.annotation)
            field_class = FlexibleLiteralField
            placeholder_text = f"Choose or type a value"
            extra_kwargs = {"choices": literal_args}

        else:
            # print(param.annotation)
            if str in annotations:
                annotation = str
            elif float in annotations:
                annotation = float
            else:
                annotation = annotations[0]
            if hasattr(param.annotation, '__origin__'):
                fallback_type_name = str(param.annotation).replace("typing.", "")
            else:
                fallback_type_name = getattr(param.annotation, '__name__', str(param.annotation).replace("typing.", ""))
            field_class, default_placeholder = annotation_mapping.get(
                annotation,
                (VariableOrStringField if design else StringField, f'Enter {fallback_type_name} value')
            )
            if len(annotations) > 1:
                type_names = []
                for t in annotations:
                    if t is int: type_names.append('int')
                    elif t is float: type_names.append('float')
                    elif t is str: type_names.append('text')
                    elif t is bool: type_names.append('bool')
                    else: type_names.append(getattr(t, '__name__', str(t)))
                placeholder_text = f"Enter {' or '.join(type_names)} value"
            else:
                placeholder_text = default_placeholder

            extra_kwargs = {}

            if annotation is bool:
                # Boolean fields should not use InputRequired
                field_kwargs["validators"] = []  # or [Optional()]


        render_kwargs = {"placeholder": placeholder_text, **extra_render_kwargs}
        # the unit and allowed range, shown after the input (see the form templates)
        hint = describe_limit((limits or {}).get(param.name) or {})
        if hint:
            field_kwargs["description"] = hint

        # Add script to kwargs if supported by field_class or in design mode
        if script and (design or field_class is FlexibleEnumField):
            field_kwargs["script"] = script

        # Create the field with additional rendering kwargs for placeholder text
        # ``name`` keeps the parameter name in the HTML even when the attribute is renamed
        field = field_class(**field_kwargs, render_kw=render_kwargs, name=param.name, **extra_kwargs)
        attr_name = safe_field_name(param.name, attr_names)
        setattr(DynamicForm, attr_name, field)
        attr_names.add(attr_name)

    setattr(DynamicForm, 'has_kwargs', has_kwargs)

    # Attach arg types metadata for UI
    arg_types_meta = {}
    for param in sig.parameters.values():
        if param.name == 'self': continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD): continue

        # Simple type inference for UI needs (checking for list)
        # We can rely on parse_annotation or strict string check
        # Checking if annotation is exactly 'list' or List[T]
        ann = param.annotation
        is_list = False
        if ann is list:
            is_list = True
        is_list = is_list_type(ann)

        if is_list:
             arg_types_meta[param.name] = "list"
        else:
             arg_types_meta[param.name] = str(ann)

    setattr(DynamicForm, 'arg_types', arg_types_meta)

    return DynamicForm


def _is_enum_type(tp):
    # Optional[Enum] comes through as Union[Enum, NoneType]
    origin = get_origin(tp)

    # Non-Optional direct enum
    if isinstance(tp, type) and issubclass(tp, Enum):
        return True

    # Optional/Union case → unwrap inner types
    if origin in _UNIONS:
        return any(
            isinstance(arg, type) and issubclass(arg, Enum)
            for arg in get_args(tp)
            if arg is not type(None)
        )

    return False

def _unwrap_enum_type(tp):
    from typing import get_origin, get_args
    from enum import Enum

    # Bare Enum
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp

    # Optional/Union conversion
    origin = get_origin(tp)
    if origin in _UNIONS:
        for arg in get_args(tp):
            if arg is not type(None) and isinstance(arg, type) and issubclass(arg, Enum):
                return arg

    return None

def _is_literal_type(tp):
    from typing import get_origin, get_args
    try:
        from typing import Literal
    except ImportError:
        from typing_extensions import Literal
    origin = get_origin(tp)
    if origin is Literal:
        return True
    if origin in _UNIONS:
        return any(get_origin(arg) is Literal for arg in get_args(tp))
    return False

def _unwrap_literal_args(tp):
    from typing import get_origin, get_args
    try:
        from typing import Literal
    except ImportError:
        from typing_extensions import Literal
    origin = get_origin(tp)
    if origin is Literal:
        return get_args(tp)
    if origin in _UNIONS:
        for arg in get_args(tp):
            if get_origin(arg) is Literal:
                return get_args(arg)
    return []

def create_add_form(attr, attr_name, autofill: bool, script=None, design: bool = True, limits=None):
    """
    Create forms for each method or signature
    :param attr: dict(docstring, signature)
    :param attr_name: method name
    :param autofill:bool if autofill is enabled
    :param script:Script object
    :param design: if design is enabled. Design allows string input for parameter names ("#param") for all fields
    """
    signature = attr.get('signature', {})
    docstring = attr.get('docstring', "")
    return_type = get_return_type(attr)
    # print(signature, docstring)
    dynamic_form = create_form_for_method(signature, autofill, script, design, limits=limits)
    if design:
        if return_type["kind"] == "tuple" and return_type.get("arity") and return_type["arity"] > 1:
            for index, item_type in enumerate(return_type["types"]):
                return_value = StringField(
                    label=f"Save item {index + 1} as",
                    render_kw={"placeholder": item_type or "Optional"}
                )
                setattr(dynamic_form, f'return_{index}', return_value)
        elif return_type["kind"] != "none":
            return_value = StringField(label='Save value as', render_kw={"placeholder": "Optional"})
            setattr(dynamic_form, 'return', return_value)
        batch_action = BooleanField(label='run once per batch', render_kw={"placeholder": "Optional"})
        setattr(dynamic_form, BATCH_ACTION_FIELD, batch_action)
    hidden_method_name = HiddenField(name=f'hidden_name', description=docstring, render_kw={"value": f'{attr_name}'})
    setattr(dynamic_form, 'hidden_name', hidden_method_name)
    return dynamic_form


def create_form_from_module(sdl_module, autofill: bool = False, script=None, design: bool = False):
    """
    Create forms for each method, used for control routes
    :param sdl_module: method module
    :param autofill:bool if autofill is enabled
    :param script:Script object
    :param design: if design is enabled
    """
    method_forms = {}
    for attr_name in dir(sdl_module):
        try:
            method = getattr(sdl_module, attr_name)
            if inspect.ismethod(method) and not attr_name.startswith('_'):
                signature = inspect.signature(method)
                docstring = inspect.getdoc(method)
                attr = dict(signature=signature, docstring=docstring)
                form_class = create_add_form(attr, attr_name, autofill, script, design)
                method_forms[attr_name] = form_class()
        except Exception as e:
            print(f"Error creating form for {attr_name}: {e}")
    return method_forms


def create_form_from_pseudo(pseudo: dict, autofill: bool, script=None, design: bool = True, limits=None):
    """
    Create forms for pseudo method, used for design routes
    :param pseudo:{'dose_liquid': {
                        "docstring": "some docstring",
                        "signature": Signature(amount_in_ml: float, rate_ml_per_minute: float) }
                    }
    :param autofill:bool if autofill is enabled
    :param script:Script object
    :param design: if design is enabled
    """
    method_forms = {}
    for attr_name, info in pseudo.items():
        # Handle properties (getter/setter)
        if isinstance(info, dict) and info.get('is_property'):
            # Getter
            form_class = create_add_form(info, attr_name, autofill, script, design)
            method_forms[attr_name] = form_class()
            
            # Setter
            if info.get('has_setter'):
                setter_name = f"{attr_name}_(setter)"
                sig = info.get('signature')
                # Infer type from getter return annotation if available
                param_type = inspect._empty
                if sig and sig.return_annotation is not inspect._empty:
                    param_type = sig.return_annotation
                
                # Create a synthetic signature for the setter: (value: type)
                setter_sig = inspect.Signature(
                    parameters=[inspect.Parameter('value', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=param_type)],
                    return_annotation=None
                )
                
                setter_info = {
                    'signature': setter_sig,
                    'docstring': f"Set {attr_name}"
                }
                form_class_setter = create_add_form(setter_info, setter_name, autofill, script, design,
                                                    limits=(limits or {}).get(setter_name))
                method_forms[setter_name] = form_class_setter()
        else:
            # Regular method
            # signature = info.get('signature', {})
            form_class = create_add_form(info, attr_name, autofill, script, design,
                                         limits=(limits or {}).get(attr_name))
            method_forms[attr_name] = form_class()
    return method_forms


def create_form_from_action(action: dict, script=None, design=True):
    '''
    Create forms for single action, used for design routes
    :param action: {'action': 'dose_solid', 'arg_types': {'amount_in_mg': 'float', 'bring_in': 'bool'},
                    'args': {'amount_in_mg': 5.0, 'bring_in': False}, 'id': 9,
                    'instrument': 'deck.sdl', 'return': '', 'uuid': 266929188668995}
    :param script:Script object
    :param design: if design is enabled

    '''

    arg_types = action.get("arg_types", {})
    args = action.get("args", {})
    save_as = action.get("return")
    instrument = action.get("instrument")
    action_name = action.get("action")

    class DynamicForm(DynamicBaseForm):
        pass

    annotation_mapping = {
        "int": (VariableOrIntField if design else IntegerField, 'Enter integer value'),
        "float": (VariableOrFloatField if design else FloatField, 'Enter numeric value'),
        "str": (VariableOrStringField if design else StringField, 'Enter text'),
        "bool": (VariableOrBoolField if design else BoolCheckboxField, 'Empty for false')
    }

    # Use explicitly saved order if available, otherwise fallback (e.g. for old actions)
    arg_order = action.get("arg_order", arg_types.keys())
    attr_names = set()
    
    sig = None
    if instrument:
        try:
            if instrument in global_state.interface_schema:
                method_info = global_state.interface_schema[instrument].get(action_name)
                if method_info and 'signature' in method_info:
                    sig = method_info['signature']
            elif instrument in global_state.building_blocks:
                method_info = global_state.building_blocks[instrument].get(action_name)
                if method_info and 'signature' in method_info:
                    sig = method_info['signature']
        except Exception:
            pass
    action_limits = guard.constraints(instrument, action_name) if instrument else {}

    for name in arg_order:
        param_type = arg_types[name]
        # formatted_param_name = format_name(name)
        value = args.get(name, "")
        structured_type = find_structured_type(param_type)
        if type(value) is dict and value and (structured_type is None or _is_output_reference(value)):
            value = next(iter(value))
            structured_type = None
        if value in (None, "", "None"):
            value = None

        is_optional = False
        param_default_is_none = False
        is_bool = (param_type == 'bool')
        
        if sig and name in sig.parameters:
            param = sig.parameters[name]
            annotations, parsed_optional = parse_annotation(param.annotation)
            is_optional = parsed_optional
            param_default_is_none = (param.default is None)
            if bool in annotations:
                is_bool = True

        if type(param_type) is list:
            none_type = param_type[1]
            if none_type == "NoneType":
                param_type = param_type[0]
                is_optional = True
        if param_type == "Literal" and sig and name in sig.parameters and _is_literal_type(sig.parameters[name].annotation):
            # a step saved before Optional[Literal] kept its choices recorded just "Literal"
            choices = _unwrap_literal_args(sig.parameters[name].annotation)
            param_type = f"Literal:{','.join(str(c) for c in choices)}"

        is_required = not (is_optional or param_default_is_none or is_bool)

        field_kwargs = {
            "label": name,
            "default": value,
            "validators": [InputRequired()] if is_required else [Optional()],
            "filters": [lambda x: x if x != '' else None] if (is_optional or param_default_is_none) else []
        }
        param_type = param_type if type(param_type) is str else f"{param_type}"
        extra_kwargs = {}
        extra_render_kwargs = {}
        if structured_type is not None:
            field_class = StructuredField
            placeholder_text = STRUCTURED_PLACEHOLDER
            extra_kwargs = {"annotation": load_structured_type(structured_type)}
            extra_render_kwargs = _structured_render_kwargs(value, extra_kwargs["annotation"])
        elif param_type.startswith("Enum:"):
            try:
                _, full_path = param_type.split(":", 1)
                module_name, class_name = full_path.rsplit(".", 1)
                mod = importlib.import_module(module_name)
                enum_class = getattr(mod, class_name)
                field_class = FlexibleEnumField
                placeholder_text = f"Choose or type a value for {class_name}"
                extra_kwargs = {"choices": enum_class}
            except Exception as e:
                field_class, placeholder_text = annotation_mapping.get(
                    param_type,
                    (VariableOrStringField if design else StringField, f'Enter {param_type} value')
                )
        elif param_type.startswith("Literal:"):
            _, literal_args_str = param_type.split(":", 1)
            literal_args = literal_args_str.split(",")
            field_class = FlexibleLiteralField
            placeholder_text = f"Choose or type a value"
            extra_kwargs = {"choices": literal_args}
        else:
            field_class, placeholder_text = annotation_mapping.get(
                param_type,
                (VariableOrStringField if design else StringField, f'Enter {param_type} value')
            )

        if instrument in ["math_variable", "variable", "input"]:
            field_class = VariableOrStringField
            if instrument == "math_variable":
                placeholder_text = "Enter math expression"
            elif instrument == "input":
                placeholder_text = "Enter prompt message"
            else:
                placeholder_text = "Enter value"
            field_kwargs["validators"] = [InputRequired()]


        render_kwargs = {"placeholder": placeholder_text, **extra_render_kwargs}
        # the unit and allowed range, shown after the input (see the form templates)
        hint = describe_limit(action_limits.get(name) or {})
        if hint:
            field_kwargs["description"] = hint

        # Add script to kwargs if supported by field_class or in design mode
        if script and (design or field_class is FlexibleEnumField):
            field_kwargs["script"] = script

        # Create the field with additional rendering kwargs for placeholder text
        # ``name`` keeps the parameter name in the HTML even when the attribute is renamed
        field = field_class(**field_kwargs, render_kw=render_kwargs, name=name, **extra_kwargs)
        attr_name = safe_field_name(name, attr_names)
        setattr(DynamicForm, attr_name, field)
        attr_names.add(attr_name)

    if instrument in ["math_variable", "variable", "input"]:
        # Add variable type dropdown
        type_field = SelectField(
            'Type',
            choices=VARIABLE_TYPE_CHOICES,
            default=arg_types.get("statement", "float" if instrument == "math_variable" else "str")
        )
        setattr(DynamicForm, "variable_type", type_field)

    if design:
        # if "batch_action" in action:
        # TODO for future, no need to have `or instrument in ['wait']`
        if "batch_action" in action or instrument in ['wait']:
            batch_action = BooleanField(label='run once per batch', default=bool(action.get("batch_action", False)))
            setattr(DynamicForm, BATCH_ACTION_FIELD, batch_action)
        if isinstance(save_as, list):
            return_format = action.get("return_format", {})
            return_types = return_format.get("types") or []
            for index, value in enumerate(save_as):
                placeholder = return_types[index] if index < len(return_types) else "Optional"
                return_value = StringField(
                    label=f"Save item {index + 1} as",
                    default=value,
                    render_kw={"placeholder": placeholder}
                )
                setattr(DynamicForm, f'return_{index}', return_value)
        else:
            if instrument in ["variable", "input", "math_variable"]:
                default_return = action.get("action", "")
            else:
                default_return = save_as or ""
            return_value = VariableOrStringField(label='Save value as', default=default_return, render_kw={"placeholder": "Result variable name"}, script=script)
            setattr(DynamicForm, 'return', return_value)
    
    # Attach arg_types for UI
    setattr(DynamicForm, 'arg_types', arg_types)

    has_kwargs = action.get('has_kwargs')
    if has_kwargs is None:
        try:
            # Try to resolve instrument method to check if it has kwargs
            if instrument and instrument.startswith("deck."):
                module_name = instrument.split(".")[1]
                deck = GlobalState().deck
                if deck:
                    inst = getattr(deck, module_name, None)
                    if inst:
                        method = getattr(inst, action['action'], None)
                        if method:
                            sig = inspect.signature(method)
                            has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        except Exception:
            pass

    setattr(DynamicForm, 'has_kwargs', has_kwargs)
    return DynamicForm()

def create_all_builtin_forms(script):
    all_builtin_forms = {}
    for logic_name in ['if', 'while', 'variable', 'input', 'wait', 'repeat', 'pause', 'math', 'comment']:
        # signature = info.get('signature', {})
        form_class = create_builtin_form(logic_name, script)
        all_builtin_forms[logic_name] = form_class()
    return all_builtin_forms

def create_builtin_form(logic_type, script):
    """
    Create a builtin form {if, while, variable, repeat, wait}
    """
    class BuiltinFunctionForm(FlaskForm):
        pass
    placeholder_text = {
        'wait': 'Enter second',
        'repeat': 'Enter an integer',
        'pause': 'Human Intervention Message',
        'comment': 'Enter comment to log',
        'input': 'Enter prompt message',
        'variable': 'Enter value',
        'math': 'Enter math expression, e.g. #x + 5 * (#y - 2)'
    }.get(logic_type, 'Enter statement')
    # short notes under the field: the toolbox column is narrow (see action_form.html)
    description_text = {
        'variable': 'A number, True/False, or "text"',
        'math': "Numbers and #variables",
    }.get(logic_type, '')
    field_class = {
        'wait': VariableOrFloatField,
        'repeat': VariableOrIntField,
    }.get(logic_type, VariableOrStringField)  # Default to StringField as a fallback
    field_kwargs = {
        "label": f'statement',
        "validators": [InputRequired()] if logic_type in ['wait', "variable", "math"] else [],
        "description": description_text,
        "script": script
    }
    render_kwargs = {"placeholder": placeholder_text}
    field = field_class(**field_kwargs, render_kw=render_kwargs)
    setattr(BuiltinFunctionForm, "statement", field)
    if logic_type == 'variable':
        variable_field = VariableOrStringField(label=f'variable', validators=[InputRequired()],
                                     description="No spaces",
                                     render_kw={"placeholder": "Variable name"}, script=script)
        type_field = SelectField(
            'Type',
            choices=VARIABLE_TYPE_CHOICES,
            default='str',  # Optional default value
            # coerce = lambda x: None if x == "None" else x
        )
        setattr(BuiltinFunctionForm, "variable", variable_field)
        setattr(BuiltinFunctionForm, "variable_type", type_field)
    elif logic_type == 'input':
        variable_field = VariableOrStringField(label=f'variable', validators=[InputRequired()],
                                     description="Saves the answer",
                                     render_kw={"placeholder": "Result variable name"}, script=script)
        type_field = SelectField(
            'Type',
            choices=VARIABLE_TYPE_CHOICES,
            default='str',
        )
        setattr(BuiltinFunctionForm, "variable", variable_field)
        setattr(BuiltinFunctionForm, "variable_type", type_field)
    elif logic_type == "math":
        math_variable_field = VariableOrStringField(
            label="save_to",
            validators=[InputRequired()],
            description="Saves the result",
            render_kw={"placeholder": "Result variable name"},
            script=script
        )
        type_field = SelectField(
            'Type',
            choices=VARIABLE_TYPE_CHOICES,
            default='float',
        )
        setattr(BuiltinFunctionForm, "math_variable", math_variable_field)
        setattr(BuiltinFunctionForm, "variable_type", type_field)

    if logic_type in ['wait']:
        batch_action = BooleanField(label='run once per batch', render_kw={"placeholder": "Optional"})
        setattr(BuiltinFunctionForm, BATCH_ACTION_FIELD, batch_action)

    hidden_field = HiddenField(name=f'builtin_name', render_kw={"value": f'{logic_type}'})
    setattr(BuiltinFunctionForm, "builtin_name", hidden_field)
    return BuiltinFunctionForm


# what a workflow function's annotations may be built from: `int`, `Optional[Speed]`, `Literal['a', 1]`, `int | None`
_TYPE_NODES = (ast.Name, ast.Attribute, ast.Subscript, ast.Constant, ast.Tuple, ast.List, ast.Load, ast.BitOr)
if sys.version_info < (3, 9):  # the trees of Python 3.7 and 3.8
    _TYPE_NODES += (ast.Index, ast.Str, ast.Num, ast.NameConstant)


def _check_workflow_definition(function_string):
    """Refuse a rendered workflow that would run more than imports and type annotations when defined.

    Its parameter annotations come from the arg types saved in the workflow, so a workflow file written by hand
    could put any code there, and defining the function runs it.
    """
    for node in ast.parse(function_string).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.decorator_list:
            raise ValueError("a workflow can only define its function")
        args = node.args
        params = getattr(args, "posonlyargs", []) + args.args + args.kwonlyargs + [args.vararg, args.kwarg]
        header = [p.annotation for p in params if p is not None and p.annotation is not None]
        header += args.defaults + [d for d in args.kw_defaults if d is not None]
        header += [node.returns] if node.returns is not None else []
        for part in header:
            for sub in ast.walk(part):
                if not isinstance(sub, _TYPE_NODES) and not (isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr)):
                    raise ValueError(f"workflow '{node.name}': a parameter type is not a type")


def get_method_from_workflow(function_string, func_name=None):
    """Creates a function from a string and assigns it a new name."""

    _check_workflow_definition(function_string)
    # One namespace for the imports and the function: Python 3.14 reads annotations when they are asked for, from
    # the function's globals, and imports kept apart as locals were not found there.
    namespace = dict(globals())
    exec(function_string, namespace)  # imports and the function definition only, see above
    defined = {name: value for name, value in namespace.items()
               if inspect.isfunction(value) and value.__code__.co_filename == "<string>"}

    if func_name and func_name in defined:
        return defined[func_name]

    # Fallback to the first function if name not provided or found
    return next(iter(defined.values()))


def create_workflow_forms(script, autofill: bool = False, design: bool = False):
    workflow_forms = {}
    functions = {}
    class RegisteredWorkflows:
        pass

    deck_name = script.deck
    workflows = Script.query.filter(Script.deck==deck_name, Script.name != script.name, Script.registered == True).all()
    for workflow in workflows:
        # workflow_name = Script.validate_function_name(workflow.name)
        try:
        # if True:

            # Backfill UUID if missing (persistent check)
            if not workflow.uuid:
                workflow.uuid = str(uuid.uuid4())
                from ivoryos.models import db
                db.session.add(workflow)
                db.session.commit()

            # Use UUID for only for html field id
            unique_key = workflow.uuid

            compiled_strs = ScriptRenderer(workflow).compile().get('script', "")
            if not compiled_strs:
                continue
            
            # Add imports so Enums are defined
            import_str = ScriptRenderer(workflow).get_required_imports() or ""
            safe_imports = [line for line in import_str.split('\n') if not line.endswith(' as deck')]
            safe_imports_str = '\n'.join(safe_imports)
            full_code = f"{safe_imports_str}\n{compiled_strs}"

            method = get_method_from_workflow(full_code, func_name=workflow.name)

            functions[unique_key] = dict(signature=inspect.signature(method), docstring=inspect.getdoc(method))
            setattr(RegisteredWorkflows, unique_key, method)

            form_class = create_form_for_method(method, autofill, script, design)

            # Store original name for display purposes
            form_class.original_name = workflow.name

            hidden_method_name = HiddenField(name=WORKFLOW_NAME_FIELD, description=f"{workflow.description}",
                                             render_kw={"value": f'{workflow.name}'})
            if design:
                # if workflow.return_values:
                #     return_value = StringField(label='Save value as', render_kw={"placeholder": "Optional"})
                #     setattr(form_class, 'return', return_value)
                batch_action = BooleanField(label='run once per batch', render_kw={"placeholder": "Optional"})
                setattr(form_class, BATCH_ACTION_FIELD, batch_action)
            setattr(form_class, WORKFLOW_NAME_FIELD, hidden_method_name)

            wf_arg_types = {}
            for param in functions[unique_key]['signature'].parameters.values():
                 ann = param.annotation
                 if is_list_type(ann):
                      wf_arg_types[param.name] = "list"
                 else:
                      wf_arg_types[param.name] = str(ann)
            setattr(form_class, 'arg_types', wf_arg_types)

            # workflow_forms[workflow_name] = form_class()
            workflow_forms[unique_key] = form_class()
        except Exception as e:
            # Log error or skip this workflow
            print(f"Error loading workflow {workflow.name if workflow else 'unknown'}: {e}")
            pass
    global_state.registered_workflows = RegisteredWorkflows
    return functions, workflow_forms


def create_action_buttons(script, reference=None):
    """
    Creates the design canvas buttons for every phase of a script.

    The deck is inspected once here and shared across the phases, so opening the
    canvas costs one compatibility lookup rather than one per phase.

    :param script: Script object
    :param reference: DeckReference to check steps against; looked up when omitted
    """
    if reference is None:
        reference = current_reference()
    return {stype: create_action_button(script, stype, reference=reference) for stype in script.stypes}


def create_action_button(script, stype=None, reference=None):
    """
    Creates action buttons for design route (design canvas)
    :param script: Script object
    :param stype: script type (script, prep, cleanup)
    :param reference: DeckReference to check steps against; looked up when omitted
    """
    stype = stype or script.editing_type
    variables = ScriptEditor(script).get_variables()
    if reference is None:
        reference = current_reference()
    return [_action_button(i, variables, reference) for i in script.get_script(stype)]


def _action_button(action: dict, variables: dict, reference=None):
    """
    Creates action button for one action
    :param action: Action dict
    :param variables: created variable dict
    :param reference: DeckReference to check the step against
    """
    style = {
        "repeat": "background-color: lightsteelblue",
        "if": "background-color: mistyrose",
        "while": "background-color: #a8b5a2",
        "pause": "background-color: palegoldenrod",
        "comment": "background-color: lightgoldenrodyellow",
        "input": "background-color: lightcyan",
    }.get(action['instrument'], "")
    if not style:
        style = "background-color: thistle" if 'batch_action' in action and action["batch_action"] else ""

    if action['instrument'] in ['if', 'while', 'repeat']:
        text = f"{action['action']} {action['args'].get('statement', '')}"
    elif action['instrument'] in ('variable', 'math_variable'):
        text = f"{action['action']} = {action['args'].get('statement')}"
    else:
        # regular action button
        return_target = ScriptEditor._format_return_target(action.get('return'))
        prefix = f"{return_target} = " if return_target else ""
        action_text = f"{action['instrument'].split('.')[-1] if action['instrument'].startswith('deck') else action['instrument']}.{action['action']}"
        arg_string = ""
        if action['args']:
            if type(action['args']) is dict:
                arg_list = []
                if 'arg_order' in action:
                    arg_order = list(action.get('arg_order') or [])
                    arg_order.extend(argument for argument in action['args'].keys() if argument not in arg_order)
                else:
                    arg_order = sorted(action['args'].keys())
                arg_types = action.get('arg_types') if isinstance(action.get('arg_types'), dict) else {}
                for argument_name in arg_order:
                    argument_data = action['args'].get(argument_name)
                    structured_type = find_structured_type(arg_types.get(argument_name))
                    if (structured_type is not None and isinstance(argument_data, (dict, list))
                            and not _is_output_reference(argument_data)):
                        # a dict as its (shortened) literal, #variables as bare names
                        value = render_python(argument_data, load_structured_type(structured_type))
                        value = value if len(value) <= 60 else value[:57] + "..."
                    elif isinstance(argument_data, dict):
                        if not argument_data:
                            value = argument_data  # Keep the original value if not a dict
                        else:
                            value = next(iter(argument_data))  # Extract the first key if it's a dict
                            # show warning color for variable calling when there is no definition

                            style = "background-color: khaki" if argument_data.get(value) == "function_output" and value not in variables.keys() else ""
                    else:
                        value = argument_data  # Keep the original value if not a dict
                    arg_list.append(f"{argument_name} = {value}")  # Format the key-value pair
                arg_string = "(" + ", ".join(arg_list) + ")"
            else:
                arg_string = f"= {action['args']}"
        text = f"{prefix}{action_text}  {arg_string}"
    issues = check_action(action, reference)
    return dict(label=text, style=style, uuid=action["uuid"], id=action["id"],
                instrument=action['instrument'], disabled=action.get('disabled', False),
                issues=issues)
