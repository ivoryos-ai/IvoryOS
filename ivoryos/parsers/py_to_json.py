import ast
import uuid


from ivoryos.runtime.state import GlobalState
from ivoryos.parsers.structured_types import is_dict_annotation, structured_value_from_node
from ivoryos.parsers.introspection import _get_type_from_parameters
from ivoryos.utils.compat import unparse

global_state = GlobalState()

if global_state.building_blocks:
    building_blocks = {
        inner_key: f"{block_key}.{inner_key}"
        for block_key, block_value in global_state.building_blocks.items()
        for inner_key in block_value.keys()
    }
else:
    building_blocks = {}

def generate_uuid():
    return int(str(uuid.uuid4().int)[:15])

def infer_type(value):
    if isinstance(value, bool):
        return "bool"
    elif isinstance(value, int):
        return "int"
    elif isinstance(value, float):
        return "float"
    elif isinstance(value, str) and value.startswith("#"):
        return "any"
    elif isinstance(value, str):
        return "str"
    else:
        return "unknown"

def convert_to_cards(source_code: str):
    tree = ast.parse(source_code)
    cards = []
    card_id = 1
    block_stack = []  # to track control flow UUIDs

    def new_id():
        nonlocal card_id
        val = card_id
        card_id += 1
        return val

    def add_card(card):
        cards.append(card)

    def is_supported_assignment(node):
        return (
            isinstance(node.targets[0], ast.Name) and
            isinstance(node.value, ast.Constant)
        )

    class CardVisitor(ast.NodeVisitor):
        def __init__(self):
            self.defined_types = {}  # <-- always exists

        def value_and_type_from_node(self, node, annotation=None):
            if annotation is not None and is_dict_annotation(annotation) and not isinstance(node, ast.Name):
                try:
                    value = structured_value_from_node(node, annotation)
                    return value, _get_type_from_parameters("value", {"value": annotation})
                except ValueError:
                    pass
            if isinstance(node, ast.Constant):
                value = node.value
                return value, infer_type(value)
            if isinstance(node, ast.Name):
                value = f"#{node.id}"
                return value, self.defined_types.get(node.id, infer_type(value))
            value = unparse(node, source_code)
            return value, infer_type(value)

        def visit_FunctionDef(self, node):
            self.defined_types = {
                arg.arg: unparse(arg.annotation, source_code) if arg.annotation else "float"
                for arg in node.args.args
            }
            for stmt in node.body:
                self.visit(stmt)

        def visit_If(self, node):
            uuid_ = generate_uuid()
            block_stack.append(("if", uuid_))

            add_card({
                "action": "if",
                "arg_types": {"statement": ""},
                "args": {"statement": unparse(node.test, source_code)},
                "id": new_id(),
                "instrument": "if",
                "return": "",
                "uuid": uuid_
            })

            for stmt in node.body:
                self.visit(stmt)

            if node.orelse:
                add_card({
                    "action": "else",
                    "args": {},
                    "id": new_id(),
                    "instrument": "if",
                    "return": "",
                    "uuid": uuid_
                })
                for stmt in node.orelse:
                    self.visit(stmt)

            _, block_uuid = block_stack.pop()
            add_card({
                "action": "endif",
                "args": {},
                "id": new_id(),
                "instrument": "if",
                "return": "",
                "uuid": block_uuid
            })

        def visit_While(self, node):
            uuid_ = generate_uuid()
            block_stack.append(("while", uuid_))

            add_card({
                "action": "while",
                "arg_types": {"statement": ""},
                "args": {"statement": unparse(node.test, source_code)},
                "id": new_id(),
                "instrument": "while",
                "return": "",
                "uuid": uuid_
            })

            for stmt in node.body:
                self.visit(stmt)

            _, block_uuid = block_stack.pop()
            add_card({
                "action": "endwhile",
                "args": {},
                "id": new_id(),
                "instrument": "while",
                "return": "",
                "uuid": block_uuid
            })

        def visit_Assign(self, node):
            if is_supported_assignment(node):
                var_name = node.targets[0].id
                value = node.value.value
                self.defined_types[var_name] = infer_type(value)
                add_card({
                    "action": var_name,
                    "arg_types": {"statement": infer_type(value)},
                    "args": {"statement": value},
                    "id": new_id(),
                    "instrument": "variable",
                    "return": "",
                    "uuid": generate_uuid()
                })
            elif isinstance(node.value, ast.Await):
                self.handle_call(node.value.value, ret_var=node.targets[0].id, awaited=True)

            elif isinstance(node.value, ast.Call):
                self.handle_call(node.value, ret_var=node.targets[0].id)

        def visit_Expr(self, node):
            if isinstance(node.value, ast.Await):
                # node.value is ast.Await
                self.handle_call(node.value.value, awaited=True)
            elif isinstance(node.value, ast.Call):
                self.handle_call(node.value)

        def handle_call(self, node, ret_var="", awaited=False):
            func_parts = []
            f = node.func
            while isinstance(f, ast.Attribute):
                func_parts.insert(0, f.attr)
                f = f.value
            if isinstance(f, ast.Name):
                func_parts.insert(0, f.id)

            full_func_name = ".".join(func_parts)

            # Check if it starts with 'deck.' and strip it
            if full_func_name.startswith("deck."):
                remaining_parts = full_func_name.split(".")[1:]
                # Must have at least instrument.action
                if len(remaining_parts) >= 2:
                    instrument = f"deck.{'.'.join(remaining_parts[:-1])}"
                    action = remaining_parts[-1]
                else:
                    return # invalid format like deck.something
            elif full_func_name.startswith("blocks."):
                instrument = ".".join(func_parts[:-1])
                action = func_parts[-1]
            elif func_parts[-1] in building_blocks.keys():
                instrument = building_blocks.get(func_parts[-1])
                action = func_parts[-1]
            else:
                # Try to see if the first part is a known instrument in interface_schema
                # This covers cases like 'sdl.dose' where 'sdl' is the instrument
                if len(func_parts) >= 2:
                    possible_instrument = ".".join(func_parts[:-1])
                    possible_action = func_parts[-1]
                    if f"deck.{possible_instrument}" in global_state.interface_schema:
                        instrument = f"deck.{possible_instrument}"
                        action = possible_action
                    else:
                        return
                else:
                    return

            # # Validate that the instrument (if not a block or time) exists in interface_schema
            # if not instrument.startswith("blocks.") and instrument != "time":
            #      if instrument not in global_state.interface_schema:
            #          return # Not a valid instrument call for this deck
            #


            # --- special case for time.sleep ---
            if instrument == "time" and action == "sleep":
                wait_value = None
                wait_type = "any"
                if node.args:
                    arg_node = node.args[0]
                    wait_value, wait_type = self.value_and_type_from_node(arg_node)

                add_card({
                    "action": "wait",
                    "arg_types": {"statement": wait_type},
                    "args": {"statement": wait_value},
                    "id": new_id(),
                    "instrument": "wait",
                    "return": ret_var,
                    "uuid": generate_uuid()
                })
                return
            # -----------------------------------


            args = {}
            arg_types = {}

            # Resolve function signature
            sig_params = []
            func_def = None
            annotations = {}  # parameter name -> annotation, to parse dict arguments

            # 1. Check in interface_schema
            if instrument in global_state.interface_schema:
                func_info = global_state.interface_schema[instrument].get(action)
                if func_info and 'signature' in func_info:
                    sig_params = list(func_info['signature'].parameters.keys())
                    sig_params.remove("self")
                    annotations = {k: p.annotation for k, p in func_info['signature'].parameters.items()}
                    print(sig_params)

            # 2. Check in building_blocks
            # instrument might be mapped name or actual block name
            # building_blocks keys are short names, values are mapped names (e.g. 'test' -> 'blocks.general.test')
            if not sig_params:
                # Check if instrument is a block name e.g. "blocks.general"
                if instrument.startswith("blocks."):
                    if instrument in global_state.building_blocks:
                        func_info = global_state.building_blocks[instrument].get(action)
                        if func_info and 'signature' in func_info:
                            sig_params = list(func_info['signature'].parameters.keys())
                            annotations = {k: p.annotation for k, p in func_info['signature'].parameters.items()}

            # Handle positional arguments
            for i, arg_node in enumerate(node.args):
                if i < len(sig_params):
                    arg_name = sig_params[i]
                else:
                    # Fallback if we have more args than parameters or no signature found
                    arg_name = f"arg_{i}"

                value, value_type = self.value_and_type_from_node(arg_node, annotations.get(arg_name))

                args[arg_name] = value
                arg_types[arg_name] = value_type


            for kw in node.keywords:
                if kw.arg is None and isinstance(kw.value, ast.Dict):
                    for k_node, v_node in zip(kw.value.keys, kw.value.values):
                        key = k_node.value if isinstance(k_node, ast.Constant) else unparse(k_node, source_code)
                        value, value_type = self.value_and_type_from_node(v_node, annotations.get(key))
                        args[key] = value
                        arg_types[key] = value_type
                else:
                    value, value_type = self.value_and_type_from_node(kw.value, annotations.get(kw.arg))
                    args[kw.arg] = value
                    arg_types[kw.arg] = value_type

            card = {
                "action": action,
                "arg_types": arg_types,
                "args": args,
                "id": new_id(),
                "instrument": instrument,
                "return": ret_var,
                "uuid": generate_uuid()
            }

            if awaited:
                card["coroutine"] = True  # mark as coroutine if awaited

            add_card(card)

    CardVisitor().visit(tree)
    return cards

def extract_functions_and_convert(source_code: str):
    """
    Parses source code, extracts each top-level function definition,
    and converts its body to cards.
    Returns a dict {func_name: cards_list}.
    """
    tree = ast.parse(source_code)
    results = {}
    
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
             # Extract the source code for this function
             # ast.get_source_segment is available in 3.8+
             func_source = ast.get_source_segment(source_code, node)
             if func_source:
                 cards = convert_to_cards(func_source)
                 results[node.name] = {"cards": cards, "source": func_source}
    return results
