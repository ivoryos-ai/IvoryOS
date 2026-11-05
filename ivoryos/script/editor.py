import ast
import builtins
import keyword
import re
import uuid
from typing import Dict

from ivoryos.parsers.structured_types import (
    find_structured_type, iter_variables, load_structured_type, parse_collection_text,
)
from ivoryos.parsers.introspection import _get_type_from_parameters

_REFERENCE = re.compile(r"#([A-Za-z_]\w*)")


def statement_expression(statement):
    """A variable step's statement or a condition as Python, its #name references as names (`#name + "_A"` is
    `name + "_A"`), or None for text that is no expression even then, such as `vial #A1`."""
    if not isinstance(statement, str):
        return None
    expression = _REFERENCE.sub(r"\1", statement)
    try:
        ast.parse(expression.strip(), mode="eval")
    except SyntaxError:
        return None
    return expression


class ScriptEditor:
    def __init__(self, script):
        self.script = script

    @property
    def currently_editing_script(self):
        return self.script.script_dict[self.script.editing_type]

    @currently_editing_script.setter
    def currently_editing_script(self, value):
        self.script.script_dict[self.script.editing_type] = value

    @property
    def currently_editing_script(self):
        return self.script.script_dict[self.script.editing_type]

    @currently_editing_script.setter
    def currently_editing_script(self, value):
        self.script.script_dict[self.script.editing_type] = value

    @staticmethod
    def validate_function_name(name):
        name = re.sub(r'\W|^(?=\d)', '_', name)
        if keyword.iskeyword(name):
            name += '_'
        return name

    def find_by_uuid(self, uuid_val):
        for stype in self.script.script_dict:
            for action in self.script.script_dict[stype]:
                if action['uuid'] == int(uuid_val):
                    return action

    def update_by_uuid(self, uuid, args, output, batch_action=False, consolidate_batch_args=False):
        action = self.find_by_uuid(uuid)
        if not action:
            return
        arg_types = action.get('arg_types', {})
        
        # Intercept variable/math/input edits to properly route the fields
        instrument = action.get("instrument")
        if instrument in ["variable", "input", "math_variable"]:
            if "variable_type" in args:
                arg_types["statement"] = args.pop("variable_type")
                
            if output:
                action["action"] = self.validate_function_name(output)

        if type(action.get('args')) is dict:
            self.eval_list(args, arg_types)
        action['args'] = args
        action['arg_types'] = arg_types
        action['return'] = output
        action['batch_action'] = batch_action
        action['consolidate_batch_args'] = consolidate_batch_args

    @staticmethod
    def eval_list(args, arg_types):
        for arg in args:
            if arg not in arg_types:
                continue
            arg_type = arg_types[arg]
            if isinstance(arg_type, str) and arg_type.startswith("Enum:"):
                continue
            if arg_type in ["list", "tuple", "set"]:
                if isinstance(args[arg], str) and not args[arg].startswith("#"):
                    args[arg] = getattr(builtins, arg_type)(parse_collection_text(args[arg]))

    def _sort(self, script_type):
        for i, action in enumerate(self.script.script_dict[script_type]):
            action['id'] = i + 1

    def sort_actions(self, script_type=None):
        if script_type:
            self._sort(script_type)
        else:
            for i in self.script.stypes:
                self._sort(i)

    def add_action(self, action: dict, insert_position=None):
        current_len = len(self.currently_editing_script)
        action_to_add = action.copy()
        action_to_add['id'] = current_len + 1
        action_to_add['uuid'] = uuid.uuid4().fields[-1]
        if insert_position is None:
            self.currently_editing_script.append(action_to_add)
        else:
            self.currently_editing_script.insert(int(insert_position) - 1, action_to_add)
        self.sort_actions()
        self.script.update_time_stamp()

    def add_variable(self, statement, variable, variable_type, insert_position=None):
        variable = self.validate_function_name(variable)
        convert_type = getattr(builtins, variable_type)
        # a plain value is stored as its type; an expression such as `x * 2` or `x > 2` is kept as typed and
        # evaluated when the step runs, as a math step's is, so a variable does what math did
        if isinstance(statement, str) and statement.startswith("#"):
            pass
        elif variable_type == "bool":
            word = statement.strip().lower()
            if word in ["true", "y", "t", "yes"]:
                statement = True
            elif word in ["false", "n", "f", "no", ""]:
                statement = False
        else:
            try:
                statement = convert_type(statement)
            except ValueError:
                # neither the type nor an expression, such as `1.2.3`: refused here, not when the run gets to it
                if statement_expression(statement) is None:
                    raise
        current_len = len(self.currently_editing_script)
        uid = uuid.uuid4().fields[-1]
        action = {"id": current_len + 1, "instrument": 'variable', "action": variable,
                        "args": {"statement": 'None' if statement == '' else statement}, "return": '', "uuid": uid,
                        "arg_types": {"statement": variable_type}}
        if insert_position is None:
            self.currently_editing_script.append(action)
        else:
            self.currently_editing_script.insert(int(insert_position) - 1, action)
        self.sort_actions()
        self.script.update_time_stamp()

    def add_math_variable(self, statement, math_variable, variable_type="float", insert_position=None):
        math_variable = self.validate_function_name(math_variable)
        current_len = len(self.currently_editing_script)
        uid = uuid.uuid4().fields[-1]
        action = {"id": current_len + 1, "instrument": 'math_variable', "action": math_variable,
                        "args": {"statement": 'None' if statement == '' else statement}, "return": '', "uuid": uid,
                        "arg_types": {"statement": variable_type}}
        if insert_position is None:
            self.currently_editing_script.append(action)
        else:
            self.currently_editing_script.insert(int(insert_position) - 1, action)
        self.sort_actions()
        self.script.update_time_stamp()

    def add_input_action(self, statement, variable, variable_type, insert_position=None):
        current_len = len(self.currently_editing_script)
        uid = uuid.uuid4().fields[-1]
        action = {"id": current_len + 1, "instrument": 'input', "action": variable,
                  "args": {"statement": statement}, "return": variable, "uuid": uid,
                  "arg_types": {"statement": variable_type}}
        if insert_position is None:
            self.currently_editing_script.append(action)
        else:
            self.currently_editing_script.insert(int(insert_position) - 1, action)
        self.sort_actions()
        self.script.update_time_stamp()


    def get_added_variables(self, before_id: int = None):
        script_list = self.script.script_dict.get("script", [])
        if before_id is not None:
            script_list = [a for a in script_list if a['id'] < before_id]
        return self._collect_added_variables(script_list)

    def _collect_added_variables(self, script_list):
        vars_dict = {}
        for action in script_list:
            if action["instrument"] == "variable":
                vars_dict[action["action"]] = action["arg_types"]["statement"]
            elif action["instrument"] == "math_variable":
                vars_dict[action["action"]] = action["arg_types"]["statement"]
            if "workflow" in action and isinstance(action["workflow"], list):
                vars_dict.update(self._collect_added_variables(action["workflow"]))
        return vars_dict

    def get_output_variables(self, before_id: int = None):
        script_list = self.script.script_dict.get("script", [])
        if before_id is not None:
            script_list = [a for a in script_list if a['id'] < before_id]
        return self._collect_output_variables(script_list)

    def _collect_output_variables(self, script_list):
        output_vars = {}
        for action in script_list:
            for output_name in self._return_names(action.get("return")):
                output_vars[output_name] = "function_output"
            if "workflow" in action and isinstance(action["workflow"], list):
                output_vars.update(self._collect_output_variables(action["workflow"]))
        return output_vars

    def get_variables(self, before_id: int = None):
        output_variables: Dict[str, str] = self.get_output_variables(before_id=before_id)
        added_variables = self.get_added_variables(before_id=before_id)
        output_variables.update(added_variables)
        return output_variables

    @staticmethod
    def _return_names(return_value):
        if isinstance(return_value, list):
            return [name for name in return_value if name]
        return [return_value] if return_value else []

    @staticmethod
    def _format_return_target(return_value):
        if isinstance(return_value, list):
            names = [name if name else "_" for name in return_value]
            return ", ".join(names) if any(name != "_" for name in names) else ""
        return return_value or ""

    def get_autocomplete_variables(self, before_id: int = None) -> list:
        variables = self.get_variables(before_id=before_id)
        variable_list = list(variables.keys())
        editing_type = self.script.editing_type or 'script'
        if editing_type in self.script.script_dict:
             config_vars, _ = self.config(editing_type, before_id=before_id)
             for var in config_vars:
                 variable_list.append(f"#{var}")
        return variable_list

    def validate_variables(self, kwargs, arg_types: dict = None):
        output_variables: Dict[str, str] = self.get_variables()
        for key, value in kwargs.items():
            if isinstance(value, str):
                if value in output_variables:
                    var_type = output_variables[value]
                    kwargs[key] = f"#{value}"
                elif value.startswith("#"):
                    kwargs[key] = f"#{self.validate_function_name(value[1:])}"
                else:
                    type_hint = arg_types.get(key, "") if arg_types else ""
                    valid_types = type_hint if isinstance(type_hint, list) else [type_hint] if type_hint else []
                    is_converted = False
                    try:
                        converted = ast.literal_eval(value)
                        if valid_types:
                            # text that parses to text had quotes, and they are part of what was typed
                            if type(converted).__name__ in valid_types and not isinstance(converted, str):
                                kwargs[key] = converted
                                is_converted = True
                        else:
                            if isinstance(converted, (int, float, bool, list, tuple, dict, set)):
                                kwargs[key] = converted
                                is_converted = True
                    except (ValueError, SyntaxError):
                        pass
                    if not is_converted and valid_types:
                        for t_name in valid_types:
                            if t_name in ['str', 'any', 'NoneType']: continue
                            if t_name in ['bool', 'list', 'tuple', 'dict', 'set']: continue
                            try:
                                converter = getattr(builtins, t_name, None)
                                if converter:
                                    kwargs[key] = converter(value)
                                    break
                            except Exception:
                                pass
        return kwargs

    def add_logic_action(self, logic_type: str, statement, insert_position=None, **kwargs):
        # a blank number field submits None rather than ''
        if statement is None:
            statement = ''
        current_len = len(self.currently_editing_script)
        uid = uuid.uuid4().fields[-1]
        logic_dict = {
            "if":
                [
                    {"id": current_len + 1, "instrument": 'if', "action": 'if',
                     "args": {"statement": 'True' if statement == '' else statement},
                     "return": '', "uuid": uid, "arg_types": {"statement": ''}},
                    {"id": current_len + 2, "instrument": 'if', "action": 'else', "args": {}, "return": '',
                     "uuid": uid},
                    {"id": current_len + 3, "instrument": 'if', "action": 'endif', "args": {}, "return": '',
                     "uuid": uid},
                ],
            "while":
                [
                    {"id": current_len + 1, "instrument": 'while', "action": 'while',
                     "args": {"statement": 'False' if statement == '' else statement}, "return": '', "uuid": uid,
                     "arg_types": {"statement": ''}},
                    {"id": current_len + 2, "instrument": 'while', "action": 'endwhile', "args": {}, "return": '',
                     "uuid": uid},
                ],
            "wait":
                [
                    {"id": current_len + 1, "instrument": 'wait', "action": "wait",
                     "args": {"statement": 1 if statement == '' else statement},
                     "return": '', "uuid": uid, "arg_types": {"statement": "float"},
                     "batch_action": kwargs.get("batch_action", False)},
                ],
            "repeat":
                [
                    {"id": current_len + 1, "instrument": 'repeat', "action": "repeat",
                     "args": {"statement": 1 if statement == '' else statement}, "return": '', "uuid": uid,
                     "arg_types": {"statement": "int"}},
                    {"id": current_len + 2, "instrument": 'repeat', "action": 'endrepeat',
                     "args": {}, "return": '', "uuid": uid},
                ],
            "pause":
                [
                    {"id": current_len + 1, "instrument": 'pause', "action": "pause",
                     "args": {"statement": "Human intervention required" if statement == '' else statement},
                     "return": '', "uuid": uid, "arg_types": {"statement": "str"}}
                ],
            "comment":
                [
                    {"id": current_len + 1, "instrument": 'comment', "action": "comment",
                     "args": {"statement": statement}, "return": '', "uuid": uid,
                     "arg_types": {"statement": "str"}}
                ],
        }
        action_list = logic_dict[logic_type]
        if insert_position is None:
            self.currently_editing_script.extend(action_list)
        else:
            index = int(insert_position) - 1
            self.currently_editing_script[index:index] = action_list
        self.sort_actions()
        self.script.update_time_stamp()

    def delete_action(self, action_id: int):
        uid = next((action['uuid'] for action in self.currently_editing_script if action['id'] == int(action_id)), None)
        self.currently_editing_script = [action for action in self.currently_editing_script if action['uuid'] != uid]
        self.sort_actions()
        self.script.update_time_stamp()

    def toggle_comment_action(self, action_id: int):
        uid = next((action['uuid'] for action in self.currently_editing_script if action['id'] == int(action_id)), None)
        if uid is not None:
            for action in self.currently_editing_script:
                if action['uuid'] == uid:
                    action['disabled'] = not action.get('disabled', False)
            self.script.update_time_stamp()

    def duplicate_action(self, action_id: int):
        index_to_duplicate = next((i for i, action in enumerate(self.currently_editing_script) if action['id'] == int(action_id)), None)
        if index_to_duplicate is None:
            raise ValueError(f"Action not found: Unable to duplicate the action with ID {action_id}")
        action_to_duplicate = self.currently_editing_script[index_to_duplicate]
        self.add_action(action_to_duplicate, insert_position=index_to_duplicate + 2)

    def config(self, stype, before_id: int = None):
        configure = []
        variables = self.get_variables(before_id=before_id)
        config_type_dict = {}
        for action in self.script.script_dict[stype]:
            args = action['args']
            if args is not None:
                if type(args) is not dict:
                    if type(args) is str and args.startswith("#"):
                        key = args[1:]
                        if key not in (*variables, *configure):
                            configure.append(key)
                            config_type_dict[key] = action['arg_types']
                else:
                    # each #name in an expression or condition is an input, not `x > 5` after a leading #
                    if action['instrument'] == "math_variable" or (
                            action['instrument'] in ("variable", "if", "while")
                            and statement_expression(args.get('statement')) is not None):
                        pattern = r"#([A-Za-z_][A-Za-z0-9_]*)"
                        vars_found = re.findall(pattern, args['statement'])
                        for key in vars_found:
                            if key not in (*variables, *configure):
                                configure.append(key)
                                config_type_dict[key] = (action.get('arg_types') or {}).get('statement') or "any"
                    else:
                        for arg in args:
                            if type(args[arg]) is str and args[arg].startswith("#"):
                                key = args[arg][1:]
                                if key not in (*variables, *configure):
                                    configure.append(key)
                                    if arg in action['arg_types']:
                                        if action['arg_types'][arg] == '':
                                            config_type_dict[key] = "any"
                                        else:
                                            config_type_dict[key] = action['arg_types'][arg]
                                    else:
                                        config_type_dict[key] = "any"
                            elif find_structured_type(action['arg_types'].get(arg)) is not None:
                                # variables nested inside a dict value, typed by the dict's value annotation
                                annotation = load_structured_type(action['arg_types'][arg])
                                for key, value_annotation in iter_variables(args[arg], annotation):
                                    if key not in (*variables, *configure):
                                        configure.append(key)
                                        field_type = _get_type_from_parameters(key, {key: value_annotation}) if value_annotation is not None else ""
                                        config_type_dict[key] = field_type or "any"
        return configure, config_type_dict

    def config_return(self):
        output_vars = self._collect_output_variables(self.script.script_dict['script'])
        return_list = set(output_vars.keys())
        output_str = "{"
        for i in return_list:
            output_str += "'" + i + "':" + i + ","
        output_str += "}"
        return output_str, list(return_list)

