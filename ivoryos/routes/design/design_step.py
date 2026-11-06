from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import login_required

from ivoryos.services.draft_service import get_script_file, post_script_file
from ivoryos.services.draft_history import step_change
from ivoryos.forms.dynamic_forms import (BATCH_ACTION_FIELD, CONSOLIDATE_ARGS_FIELD,
                                          create_form_from_action, create_action_buttons)
from ivoryos.parsers.returns import extract_return_variables
from ivoryos.script import ScriptEditor, ScriptRenderer
from ivoryos.script.compatibility import check_action, current_reference


steps = Blueprint('design_steps', __name__)


@steps.get("/draft/steps/<int:uuid>")
def get_step(uuid: int):
    """
    .. :quickref: Workflow Design; Get step editing form

    **Get Step**

    .. http:get:: /draft/steps/<int:uuid>

    Retrieve the HTML editing form for a specific action step in the design canvas.

    :param uuid: The unique ID of the action step.
    :status 200: Returns the step editing form (HTML).
    :status 404: Step not found.
    """
    script = get_script_file()
    action = script.find_by_uuid(uuid)
    if action is None:
        return jsonify({"warning": "Step not found, please refresh the page."}), 404

    elif request.method == 'GET':
        forms = create_form_from_action(action, script=script)
        # session['edit_action'] = action
        return render_template("components/edit_action_form.html",
                               action=action,
                               forms=forms,
                               script=script,
                               issues=check_action(action, current_reference()))



@steps.post("/draft/steps/<int:uuid>")
def save_step(uuid: int):
    """
    .. :quickref: Workflow Design; Save step changes

    **Save Step**

    .. http:post:: /draft/steps/<int:uuid>

    Save the changes made to an action step, including updated arguments and return variables.

    :param uuid: The step number id
    :type uuid: int

    :status 200: render template with action step form
    """
    script = get_script_file()
    action = script.find_by_uuid(uuid)
    warning = None
    if action is not None:
        forms = create_form_from_action(action, script=script)
        kwargs = {field.name: field.data for field in forms if field.name != 'csrf_token'}
        if forms and forms.validate_on_submit():
            save_data = extract_return_variables(kwargs, ScriptEditor.validate_function_name)

            batch_action = kwargs.pop(BATCH_ACTION_FIELD, False)
            consolidate_batch_args = request.form.getlist(CONSOLIDATE_ARGS_FIELD)

            # Collect dynamic kwargs
            extra_keys = request.form.getlist('extra_key[]')
            extra_values = request.form.getlist('extra_value[]')
            if extra_keys:
                extra_args = {k.strip(): v for k, v in zip(extra_keys, extra_values) if k and k.strip()}
                kwargs.update(extra_args)

            # literal for args with no typehint
            arg_types = action.get('arg_types', {})
            kwargs = ScriptEditor(script).validate_variables(kwargs, arg_types)

            ScriptEditor(script).update_by_uuid(uuid=uuid, args=kwargs, output=save_data, batch_action=batch_action, consolidate_batch_args=consolidate_batch_args)
        else:
            warning = f"Compilation failed: {str(forms.errors)}"
    post_script_file(script)
    try:
        exec_string = ScriptRenderer(script).compile(current_app.config['SCRIPT_FOLDER'])
    except Exception as e:
        exec_string = {}
        warning = f"Compilation failed: {str(e)}"
    # session['python_code'] = exec_string
    design_buttons = create_action_buttons(script)
    return render_template("components/canvas_main.html",
                           script=script,
                           buttons_dict=design_buttons,
                           warning=warning)

@steps.delete("/draft/steps/<int:uuid>")
def delete_step(uuid: int):
    """
    .. :quickref: Workflow Design; Delete a design step

    **Delete Step**

    .. http:delete:: /draft/steps/<int:uuid>

    Remove a specific action step from the current workflow design.

        :param uuid: The step number id
        :type uuid: int

    :status 200: render template with action step form
    """
    script = get_script_file()
    if request.method == 'DELETE':
        ScriptEditor(script).delete_action(uuid)
    post_script_file(script)
    warning = None
    try:
        exec_string = ScriptRenderer(script).compile(current_app.config['SCRIPT_FOLDER'])
    except Exception as e:
        exec_string = {}
        warning = f"Compilation failed: {str(e)}"
    # session['python_code'] = exec_string
    design_buttons = create_action_buttons(script)
    return render_template("components/canvas_main.html",
                               script=script,
                               buttons_dict=design_buttons, warning=warning)


@steps.route("/draft/steps/<int:uuid>/duplicate", methods=["POST"], strict_slashes=False,)
def duplicate_action(uuid: int):
    """
    .. :quickref: Workflow Design; Duplicate a design step

    **Duplicate Step**

    .. http:post:: /draft/steps/<int:uuid>/duplicate

    :param uuid: The step number uuid
    :type uuid: int

    :status 200: render new design script template
    """

    # back = request.referrer
    script = get_script_file()
    editor = ScriptEditor(script)
    original = next((step for step in editor.currently_editing_script if step['id'] == int(uuid)), None)
    editor.duplicate_action(uuid)
    # a copy reads like a second add of the same action, so the change is named here
    post_script_file(script, label=step_change("Duplicate", original, script.editing_type) if original else None)
    warning = None
    try:
        exec_string = ScriptRenderer(script).compile(current_app.config['SCRIPT_FOLDER'])
    except Exception as e:
        exec_string = {}
        warning = f"Compilation failed: {str(e)}"
    # session['python_code'] = exec_string
    design_buttons = create_action_buttons(script)

    return render_template("components/canvas_main.html",
                         script=script,
                         buttons_dict=design_buttons, warning=warning)

@steps.post("/draft/steps/<int:uuid>/toggle_comment")
def toggle_comment_action(uuid: int):
    """
    .. :quickref: Workflow Design; Toggle comment step
    
    **Toggle Comment Step**
    
    .. http:post:: /draft/steps/<int:uuid>/toggle_comment
    
    :param uuid: The step number uuid
    :type uuid: int
    
    :status 200: render new design script template
    """
    script = get_script_file()
    
    # We find the ID of the step that corresponds to this UUID.
    action = script.find_by_uuid(uuid)
    if action is not None:
        action_id = action['id']
        ScriptEditor(script).toggle_comment_action(action_id)
        post_script_file(script)
        
    warning = None
    try:
        exec_string = ScriptRenderer(script).compile(current_app.config['SCRIPT_FOLDER'])
    except Exception as e:
        exec_string = {}
        warning = f"Compilation failed: {str(e)}"
    
    design_buttons = create_action_buttons(script)

    return render_template("components/canvas_main.html",
                         script=script,
                         buttons_dict=design_buttons, warning=warning)


@steps.route("/draft/steps/order", methods=['POST'])
@login_required
def update_list():
    """
    .. :quickref: Workflow Design Steps; update the order of steps in the design canvas when reordering steps.

    .. http:post:: /draft/steps/order

    Update the order of steps in the design canvas when reordering steps.

    :form order: A comma-separated string representing the new order of steps.
    :status 200: Successfully updated the order of steps.
    """
    order = request.form.get('order', '')
    script = get_script_file()
    editor = ScriptEditor(script)
    warning = None

    if order:
        order_ids = [int(i) for i in order.split(",") if i.strip()]
        action_dict = {action['id']: action for action in editor.currently_editing_script}
        new_script = []
        for action_id in order_ids:
            if action_id in action_dict:
                new_script.append(action_dict[action_id])
                del action_dict[action_id]

        # Append any remaining actions just in case
        new_script.extend(action_dict.values())
        # an else or end can't be moved above its own if/while/repeat, nor an else below its end:
        # the move is refused and the canvas comes back in its old order
        problem = ScriptEditor.block_order_problem(new_script, before=editor.currently_editing_script)
        if problem:
            warning = f"{problem} The steps were left in their old order."
        else:
            editor.currently_editing_script = new_script

    if not warning:
        editor.sort_actions()
        post_script_file(script)
        try:
            exec_string = ScriptRenderer(script).compile(current_app.config['SCRIPT_FOLDER'])
        except Exception as e:
            exec_string = {}
            warning = f"Compilation failed: {str(e)}"
    # session['python_code'] = exec_string

    # Return the updated canvas HTML instead of JSON
    design_buttons = create_action_buttons(script)
    return render_template("components/canvas_main.html",
                           script=script,
                           buttons_dict=design_buttons, warning=warning)
