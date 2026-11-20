import inspect
import os
from flask import Blueprint, redirect, url_for, flash, request, session, current_app, g
from flask_login import login_required

from ivoryos.runtime.state import GlobalState
from ivoryos.services.draft_service import get_script_file, post_script_file
from ivoryos.parsers.introspection import load_interface_schema
from ivoryos.script import ScriptEditor


global_state = GlobalState()
agent = Blueprint('design_agent', __name__)

@agent.route('/agent/process_request', methods=['POST'])
@login_required
def process_request():
    """
    .. :quickref: Workflow Design; process natural language input to automatically generate actions.

    .. http:post:: /agent/process_request

    A user prompt is processed, with the most likely actions are appended at the end of the workflow design.
    The arguments and their parameter are automatically extracted from the user request. 
    If the variables are unknown the default value is taken or a dynamic variable is generated. 

    :form prompt: User request to the design agent. 

    :status 200: Successfully generated new actions or successfully catched exception.
    """
    try:
        # extract user request
        prompt = request.form.get("prompt")
        if not prompt:
            raise Exception("Design agent could not extract prompt.")
        
        # obtain the current deck/instrument information
        try: 
            deck_info = _get_deck_info()
            if not deck_info: raise Exception("The deck information dictonary retrieved seems to be empty. Check the current deck state.")
        except Exception as e:
            raise Exception(f"Error while extracting the deck information - Message: '{e}'")
        
        # generate design steps
        try:
            llm_agent = global_state.agent
            if not llm_agent: raise ValueError("GlobalState.agent is not initialized. Ensure it is properly set up.")
            action_list = llm_agent.generate_design(user_request = prompt, deck_info = deck_info)
            if len(action_list) == 0: raise ValueError("The agent returned an empty list.")
        except Exception as e:
            raise Exception(f"Error while generating the design - Message: '{e}'")
        
        # append actions to desing
        try:
            _add_actions_to_design(action_list = action_list, deck_info = deck_info)
        except Exception as e:
            raise Exception(f"Error while adding actions to the design builder - Message: '{e}'")
    
    except Exception as e:
        g.logger.warning(f"DesignAgent Exception occured while generating actions. \n   === DETAILS ===\n{e}\n   === ======= ===")
        flash(f"Agent failed to generate design. Please try again! You can check out the logs for more details.", "error")
        return redirect(url_for("design.experiment_builder"))
    
    flash(f"Design agent generated {len(action_list)} action(s) successfully.", "success")
    return redirect(url_for("design.experiment_builder"))


def _get_deck_info(add_flow_control = True, add_class_info = True):
    """
    Generates a structured dictonary of all instruments on the current deck configuration - works online and offline.
    
    Args:
        add_flow_control (bool, default: True): See `_add_flow_control()` method.
        add_class_info (bool, default: True): Additional class information (`name`, `docstring`) of the instrument object. 
            Works only in online mode.
    
    Returns:
        deck_dictionary (dict):
            
            Format:
            {
                instrument_name: {
                    "class_name": str | None,                    # Name of the Python class
                    "class_doc": str | None,                     # Class-level docstring
                    "actions": {         
                        action_name: {       
                            "action_doc": str | None,            # Method description
                            "coroutine": bool,                   # Coroutine flag 
                            "args": {        
                                "param_name": {      
                                    "arg_type": str,             # Data type
                                    "default_value": any | None  # Default if defined, else None
                                }
                            }
                        }
                    }
                }
            }
    
    """
    deck_dictionary = {}
    
    if add_flow_control: deck_dictionary.update(_add_flow_control()) 
    
    # loads the selected offline deck interface_schema or the last online interface_schema
    if current_app.config["OFF_LINE"]:
        add_class_info = False # sets the flag to false for offline mode
        pseudo_deck_path = os.path.join(current_app.config["DUMMY_DECK"], session.get('pseudo_deck', ''))
        interface_schema = load_interface_schema(pseudo_deck_path)
    else:
        interface_schema = GlobalState().interface_schema
    
    # loads general deck with all current objects, from which class infos can be extracted
    if add_class_info == True:
        deck_with_class_info = vars(GlobalState().deck)
        if not deck_with_class_info: add_class_info = False

    for instrument, actions in interface_schema.items():
        # skips the deck_name key present in the offline interface_schemas
        if instrument == 'deck_name':
            continue
        
        instrument_identifier = str(instrument)
        if instrument_identifier.startswith('deck.'):  # str.removeprefix is Python 3.9+
            instrument_identifier = instrument_identifier[len('deck.'):]
        
        if add_class_info == True:
            class_name = type(deck_with_class_info[instrument_identifier]).__name__ or None
            class_doc = class_doc = inspect.getdoc(deck_with_class_info[instrument_identifier]) or None
        else:
            class_name = None
            class_doc = None
        
        deck_dictionary[instrument_identifier] = {
            "class_name": class_name,
            "class_doc": class_doc,
            "actions": {}
        }

        for action, meta in actions.items():
            action_doc = meta.get('docstring', None)
            coroutine = meta.get('coroutine', False)
            
            deck_dictionary[instrument_identifier]["actions"][action] = {
                "action_doc": action_doc,
                "coroutine": coroutine,
                "args": {}
            }
            
            signature = meta.get('signature')
            
            for arg_name, param in signature.parameters.items():
                
                if arg_name == 'self':
                    continue

                arg_type = "Any"
                if param.annotation != inspect.Parameter.empty:
                    if hasattr(param.annotation, '__name__'):
                        arg_type = param.annotation.__name__
                    else:
                        arg_type = str(param.annotation).replace('typing.', '')

                default_value = None
                if param.default != inspect.Parameter.empty:
                    default_value = param.default

                # Populate the args dictionary
                deck_dictionary[instrument_identifier]["actions"][action]["args"][arg_name] = {
                    "arg_type": arg_type,
                    "default_value": default_value
                }
        
    return deck_dictionary


def _add_flow_control():
    """
    Returns a dictionary for flow control logic, structured as a 'Virtual Instrument'.
    
    TODO: Currently only the 'wait' and 'comment' method. Other methods likely need more finetuning to reliable work with the design agent.
    When adding new flow control logics, check the dictonary syntax closely that it matches the deck dictionaries of the '_get_deck_info' method!
    """
    return {
        "wait": {
            "instrument_class": "Flow_Control",
            "class_doc": "No description.",
            "actions": {
                "wait": {
                    "action_doc": "Pauses execution for a specific duration (statement = pause_in_seconds: float).",
                    "coroutine": False,
                    "args": { "statement": { "arg_type": "float", "default_value": None } }
                }
            }
        },
        "comment": {
            "instrument_class": "Flow_Control",
            "class_doc": "No description.",
            "actions": {
                "comment": {
                    "action_doc": "Adds a comment (statement = comment_content: str). Has no effect on the experiment execution.",
                    "coroutine": False,
                    "args": {
                        "statement": { "arg_type": "str", "default_value": None} }
                }
            }
        }
    }


def _add_actions_to_design(action_list: list, deck_info: dict):
    """
    Iterates through the LLM generated action list and adds each action. Post the new script file in the end.

    Args:
        action_list (list): Validated actions containing 'instrument', 'action', and 'args'.
        deck_info (dict): Deck configuration used to map argument types for each action.
    """
    script = get_script_file()
    batch_action = False
    
    for action in action_list:
        instrument_name = action["instrument"]
        action_name = action["action"]
        args = action["args"]
        deck_args = deck_info[instrument_name]["actions"][action_name]["args"]
        coroutine = deck_info[instrument_name]["actions"][action_name]["coroutine"]
        arg_types = {}
        
        for arg in args.keys():
            arg_type = deck_args[arg]["arg_type"]
            arg_types[arg] = arg_type
            
        new_action = {
                "instrument": instrument_name,
                "action": action_name,
                "args": args,
                "return": "", 
                "arg_types": arg_types,
                "coroutine": coroutine,
                "batch_action": batch_action
            }
        
        ScriptEditor(script).add_action(action=new_action)
    
    post_script_file(script, label=f"Add {len(action_list)} step{'' if len(action_list) == 1 else 's'} from the design agent")