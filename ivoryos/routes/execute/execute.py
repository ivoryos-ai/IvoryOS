import csv
import os
import time
import importlib



from flask import Blueprint, redirect, url_for, flash, jsonify, request, render_template, session, \
    current_app, g, send_file
from flask_login import current_user, login_required
from markupsafe import Markup
from werkzeug.utils import secure_filename

from ivoryos.routes.execute.execute_file import files
from ivoryos.services.draft_service import get_script_file
from ivoryos.services.connection_history import import_history
from ivoryos.parsers.type_conversions import check_config_duplicate, web_config_entry_wrapper
from ivoryos.runtime.safety import guard
from ivoryos.runtime.task_conditions import config_form_problems, optional_inputs, unset_input_problems
from ivoryos.parsers.bo_campaign import parse_optimization_form
from ivoryos.models import db, SingleStep, WorkflowRun, WorkflowStep, WorkflowPhase
from ivoryos.runtime.state import GlobalState
from ivoryos.script import ScriptEditor, ScriptRenderer
from ivoryos.script.compatibility import current_reference, script_issue_summary
from ivoryos.socket_handlers import runner, retry, pause, abort_pending, abort_current


execute = Blueprint('execute', __name__, template_folder='templates')

execute.register_blueprint(files)
# Register sub-blueprints
global_state = GlobalState()


def _unique_run_name(name, keep=None):
    """``name``, or ``name_N`` if a past, running or queued run already uses it.

    ``keep`` is the current name of a queued task being renamed; that task does not
    count as already using it.
    """
    base_name = ScriptEditor.validate_function_name(name)
    taken = runner.reserved_run_names() - {keep}
    final_name = base_name
    counter = 1
    while final_name in taken or WorkflowRun.query.filter_by(name=final_name).first() is not None:
        final_name = f"{base_name}_{counter}"
        counter += 1
    return final_name


def _start_task_info(queued_run_name, queued_batch_size):
    """Name and batch size of the task now starting; both may have been edited while it was queued."""
    task = runner.current_task or {}
    return {
        'run_name': task.get('run_name') or queued_run_name,
        'batch_size': int(task.get('batch_size') or queued_batch_size),
    }


@execute.route("/executions/config", methods=['GET', 'POST'])
@login_required
def experiment_run():
    """
    .. :quickref: Workflow Execution Config; Execute/iterate the workflow

    .. http:get:: /executions/config

    Load the experiment execution interface.

    .. http:post:: /executions/config

    Start workflow execution with experiment configuration.

    :status 200: Successfully loaded the config page or started the task.
    """
    deck = global_state.deck
    script = get_script_file()
    # runner = global_state.runner
    existing_data = None
    # ScriptEditor(script).sort_actions() # handled in update list
    off_line = current_app.config["OFF_LINE"]
    deck_list = import_history(os.path.join(current_app.config["OUTPUT_FOLDER"], 'deck_history.txt'))
    optimizers_schema = {k: v.get_schema() for k, v in global_state.optimizers.items()}
    # No step buttons here: experiment_run.html stopped rendering them when the
    # accordion was removed (ce38c7b). The compatibility findings it does want -
    # this is the last screen before a run.
    reference = current_reference()
    compat_steps = script_issue_summary(script, reference)
    config_preview = []
    config_file_list = [i for i in os.listdir(current_app.config["CSV_FOLDER"]) if not i == ".gitkeep"]

    try:
        interface_schema = global_state.interface_schema
        exec_string = script.python_script if script.python_script else ScriptRenderer(script).compile(
            current_app.config['SCRIPT_FOLDER'], interface_schema=interface_schema)
    except Exception as e:
        flash(e.__str__())
        if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
            return jsonify({"error": e.__str__()})
        else:
            return redirect(url_for("design.experiment_builder"))

    config_file = request.args.get("filename")
    config = []
    if "filename" in request.args:
        session['config_file'] = config_file
    filename = session.get("config_file")
    if filename:
        config = list(csv.DictReader(open(os.path.join(current_app.config['CSV_FOLDER'], filename))))
        config_preview = config[1:]
        arg_type = config.pop(0)  # first entry is types

    try:
        # Handle both string and dict exec_string
        if isinstance(exec_string, dict):
            # import_str = script.get_required_imports()
            # if import_str:
            #     compile(import_str, '<imports>', 'exec')
            for key, func_str in exec_string.items():
                compile(func_str, f'<function_{key}>', 'exec')

        else:
            if isinstance(exec_string, str):
                compile(exec_string, '<script>', 'exec')
            # Handle string case - you might need to adjust this based on your needs
            line_collection = {}
    except Exception as e:
        g.logger.exception(f"Exception while executing script: {e}")
        flash(f"Please check syntax!! {e}")
        return redirect(url_for("design.experiment_builder"))


    # If there is a current task running, use that script for display
    # otherwise use the current script being configured
    
    current_lines_script = script
    if runner.current_task and runner.current_task.get("script"):
        current_lines_script = runner.current_task["script"]
        
    line_collection = ScriptRenderer(current_lines_script).render_nested_script_lines(current_lines_script.script_dict, interface_schema=interface_schema)

    run_name = script.name if script.name else "untitled"

    dismiss = session.get("dismiss", None)
    # script = get_script_file() 
    no_deck_warning = False

    _, return_list = ScriptEditor(script).config_return()
    config_list, config_type_list = ScriptEditor(script).config("script")
    # read before the Enum columns below are reduced to their choices, which drops the None
    config_optional = optional_inputs(config_type_list)

    for key, type_str in config_type_list.items():
        # Handle Optional/Union types which come as lists
        if isinstance(type_str, list):
             # Find the Enum entry if it exists
             enum_entries = [t for t in type_str if isinstance(t, str) and t.startswith("Enum:")]
             if enum_entries:
                 # Use the first found Enum type
                 type_str = enum_entries[0]
                 # Update the list in place so template gets the simple string?
                 # Or better, just proceed to process it as a string
             literal_entries = [t for t in type_str if isinstance(t, str) and t.startswith("Literal:")] if isinstance(type_str, list) else []
             if literal_entries:
                 # an Optional[Literal]: the config table offers its choices, like a Literal
                 config_type_list[key] = literal_entries[0]

        if isinstance(type_str, str) and type_str.startswith("Enum:"):
            try:
                _, full_path = type_str.split(":", 1)
                module_name, class_name = full_path.rsplit(".", 1)
                mod = importlib.import_module(module_name)
                enum_class = getattr(mod, class_name)
                options = [e.name for e in enum_class]
                config_type_list[key] = f"Enum:{','.join(options)}"
            except Exception:
                pass


    data_list = [f for f in os.listdir(current_app.config['DATA_FOLDER']) if f.endswith('.csv')]
    # Remove .gitkeep if present
    if ".gitkeep" in data_list:
        data_list.remove(".gitkeep")

    # Sort by creation time, newest first
    data_list.sort(key=lambda f: os.path.getctime(os.path.join(current_app.config['DATA_FOLDER'], f)), reverse=True)

    if deck is None:
        no_deck_warning = True
        flash(f"No deck is found, import {script.deck}")
    elif script.deck:
        is_deck_match = script.deck == deck.__name__ or script.deck == \
                        os.path.splitext(os.path.basename(deck.__file__))[0]
        if not is_deck_match:
            flash(f"This script is not compatible with current deck, import {script.deck}")

    if request.method == "POST":
        # bo_args = None
        compiled = False
        display_name = None
        config_problems = []
        if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
            payload_json = request.get_json()
            compiled = True
            if "kwargs" in payload_json:
                config = payload_json["kwargs"]
            # elif "parameters" in payload_json:
            #     bo_args = payload_json
            repeat = payload_json.pop("repeat", None)
            batch_size = payload_json.pop('batch_size', 1)
        else:
            # Extract display name if present
            display_name = request.form.get("display_name")
            
            if "bo" in request.form:
                bo_args = request.form.to_dict()
                existing_data = bo_args.pop("existing_data")
                bo_args.pop("display_name", None)
            if "online-config" in request.form:
                config_args = request.form.to_dict()
                config_args.pop("batch_size", None)
                config_args.pop("display_name", None)
                config = web_config_entry_wrapper(config_args, config_list)
                # the page checks the table before sending it; this repeats the check
                # the way the run converts values, for anything the page let through
                config_problems = config_form_problems(config_args, *ScriptEditor(script).config("script"),
                                                       limits=guard.column_limits(script))
            batch_size = int(request.form.get('batch_size', 1))
            repeat = request.form.get('repeat', None)

        # a #name no step sets has to come from the run: a table row checked above, or an API row
        if not config or compiled:
            config_problems += unset_input_problems(*ScriptEditor(script).config("script"), config)
        # values written into the steps, and an API run's rows, against the instruments' limits
        config_problems += guard.check_steps(script)
        if compiled and config:
            config_problems += guard.check_rows(script, config)
        if config_problems:
            if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
                return jsonify({"error": "Nothing was started: some values can't run.", "problems": config_problems}), 400
            # rendered as HTML, so the values quoted from the table are escaped
            flash(Markup("Nothing was started: some values can't run. Fix them and run again.<br>")
                  + Markup("<br>").join(config_problems))
        else:
            try:
            # if True:
                datapath = current_app.config["DATA_FOLDER"]
                run_name = _unique_run_name(display_name if (display_name and display_name.strip()) else run_name)

                socketio_instance = g.socketio
                def on_start_callback():
                    # This runs inside the thread with app context pushed
                    interface_schema = global_state.interface_schema
                    line_collection = ScriptRenderer(script).render_nested_script_lines(script.script_dict, interface_schema=interface_schema)
                    progress_panel_html = render_template('components/progress_panel.html', line_collection=line_collection)
                    socketio_instance.emit('start_task', {
                        **_start_task_info(run_name, batch_size),
                        'progress_panel_html': progress_panel_html
                    })

                result = runner.run_script(script=script, run_name=run_name, config=config,
                                  logger=g.logger, socketio=g.socketio, repeat_count=repeat,
                                  output_path=datapath, compiled=compiled, history=existing_data,
                                  current_app=current_app._get_current_object(), batch_size=batch_size,
                                  on_start=on_start_callback, display_name=display_name,
                                  submitted_by=current_user.get_id()
                                  )

                # remove queue flash, handled in html/js
                # if result == "queued":
                #     flash(f"System busy. Task {run_name} added to queue.", "popup")
                # else:
                #     flash(f"Task '{run_name}' started.")
                if check_config_duplicate(config):
                    flash(f"WARNING: Duplicate in config entries.")
            except Exception as e:
                if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
                    return jsonify({"error": e.__str__()})
                else:
                    flash(e)

    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
        # wait to get a workflow ID
        while not global_state.runner_status:
            time.sleep(1)
        return jsonify({"status": "task started", "task_id": global_state.runner_status.get("id")})
    else:
        # todo if want to be able to optimize more then add something called objectives_list instead, and add that to the tab_bayesian.html, and add in
        #  more than just the return_list in there; e.g. be able to use math or normal or human input variables as objectives
        return render_template('experiment_run.html', script=script.script_dict, filename=filename,
                               running_config_editable=runner.live_config is not None,
                               column_limits=guard.column_limits(script),
                               dot_py=exec_string, line_collection=line_collection,
                               return_list=return_list, config_list=config_list, config_file_list=config_file_list,
                               config_preview=config_preview, data_list=data_list, config_type_list=config_type_list,
                               config_optional=config_optional,
                               no_deck_warning=no_deck_warning, dismiss=dismiss,
                               compat_steps=compat_steps,
                               history=deck_list, pause_status=runner.pause_status(), optimizer_schema=optimizers_schema)


@execute.route("/executions/optimizer_schema", methods=["POST"])
def optimizer_schema():
    """
    .. :quickref: Workflow Execution; Get optimizer schema

    **Optimizer Schema**

    .. http:post:: /executions/optimizer_schema

    Retrieve the parameter and configuration schema for a specific optimizer or all available optimizers.

    :json optimizer_type: Optional name of the optimizer to get the schema for.
    :status 200: Returns the requested schema as JSON.
    """
    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
        payload_json = request.get_json()
        optimizer_type = payload_json.pop("optimizer_type", None)
        if optimizer_type:
            _schema = global_state.optimizers.get(optimizer_type, None)
            if _schema is None:
                return jsonify({"error": f"Optimizer {optimizer_type} is not supported or not found."})
            return jsonify(_schema.get_schema())
        else:
            optimizers_schema = {k: v.get_schema() for k, v in global_state.optimizers.items()}
            return jsonify(optimizers_schema)
    return None


@execute.route("/executions/campaign", methods=["POST"])
@login_required
def run_bo():
    """
    .. :quickref: Workflow Execution; Run Bayesian Optimization campaign

    Run Bayesian Optimization with the given parameters and objectives.

    .. http:post:: /executions/campaign

    Start a Bayesian Optimization (BO) campaign using the specified optimizer, parameters, and objectives.

    :form repeat: The number of iterations/repeats to run.
    :form optimizer_type: The name of the optimizer to use (e.g., 'GPyOpt').
    :form existing_data: Path to an existing CSV file for warm-starting the optimization.
    :form parameters: The search space configuration for parameters.
    :form objectives: The return values to optimize.
    :status 302: Redirects to the execution config page after starting.
    """
    script = get_script_file()
    run_name = script.name if script.name else "untitled"

    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
        payload_json = request.get_json()
        objectives = payload_json.pop("objectives", None)
        parameters = payload_json.pop("parameters", None)
        steps = payload_json.pop("steps", None)
        constraints = payload_json.pop("parameter_constraints", None)
        repeat = payload_json.pop("repeat", None)
        batch_size = payload_json.pop("batch_size", None)
        optimizer_type = payload_json.pop("optimizer_type", None)
        existing_data = payload_json.pop("existing_data", None)
        additional_params = payload_json.pop("additional_params", None)
        display_name = payload_json.pop("display_name", None)
    else:
        payload = request.form.to_dict()
        display_name = payload.pop("display_name", None)
        repeat = payload.pop("repeat", None)
        optimizer_type = payload.pop("optimizer_type", None)
        existing_data = payload.pop("existing_data", None)
        upload_new_data = payload.pop("data_mode_toggle", None)

        # warning - existing data may be set if selected a file in choose existing data, BUT if you choose to upload
        #   data then the uplodaded data payload will also exist. choose the one to use based on the data mode toggle
        if upload_new_data == 'on': # use custom uploaded data
            uploaded_file = request.files.get("uploaded_data")
            # Handle file upload if present
            if uploaded_file and uploaded_file.filename:
                filename = secure_filename(uploaded_file.filename)
                filepath = os.path.join(current_app.config['DATA_FOLDER'], filename)
                uploaded_file.save(filepath)
                existing_data = filename
            else:
                existing_data = ''
        else:
            # use previous existing data
            existing_data = existing_data

        batch_mode = payload.pop("batch_mode", None)
        batch_size = payload.pop("batch_size", 1)

        # Get constraint expressions (new single-line input)
        constraint_exprs = request.form.getlist("constraint_expr")
        constraints = [expr.strip() for expr in constraint_exprs if expr.strip()]

        # Remove constraint_expr entries from payload before parsing parameters
        for key in list(payload.keys()):
            if key.startswith("constraint_expr"):
                payload.pop(key, None)

        parameters, objectives, steps, additional_params = parse_optimization_form(payload)
        # print(additional_params)
    # the steps' own values, and a search range or choices reaching past a limit
    limit_problems = guard.check_steps(script) + guard.check_search_space(script, parameters)
    # a #name no step sets has to be a parameter of the campaign
    fields, arg_types = ScriptEditor(script).config("script")
    named = {parameter.get("name") for parameter in parameters or [] if isinstance(parameter, dict)}
    limit_problems += unset_input_problems([field for field in fields if field not in named], arg_types)
    if limit_problems:
        if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
            return jsonify({"error": "Nothing was started: some values can't run.", "problems": limit_problems}), 400
        flash(Markup("Nothing was started: some values can't run. Fix them and run again.<br>")
              + Markup("<br>").join(limit_problems))
        return redirect(url_for("execute.experiment_run"))
    # if True:
    try:
        datapath = current_app.config["DATA_FOLDER"]
        run_name = _unique_run_name(display_name if (display_name and display_name.strip()) else run_name)

        Optimizer = global_state.optimizers.get(optimizer_type, None)
        if not Optimizer:
            raise ValueError(f"Optimizer {optimizer_type} is not supported or not found.")

        socketio_instance = g.socketio
        def on_start_callback():
            # This runs inside the thread with app context pushed
            interface_schema = global_state.interface_schema
            line_collection = ScriptRenderer(script).render_nested_script_lines(script.script_dict, interface_schema=interface_schema)
            progress_panel_html = render_template('components/progress_panel.html', line_collection=line_collection)
            socketio_instance.emit('start_task', {
                **_start_task_info(run_name, batch_size),
                'progress_panel_html': progress_panel_html
            })

        result = runner.run_script(script=script, run_name=run_name, optimizer=None,
                          logger=g.logger, socketio=g.socketio, repeat_count=repeat,
                          output_path=datapath, compiled=False, history=existing_data,
                          current_app=current_app._get_current_object(), batch_size=int(batch_size),
                          objectives=objectives, parameters=parameters, constraints=constraints, steps=steps,
                          optimizer_cls=Optimizer, additional_params=additional_params,
                          on_start=on_start_callback, display_name=display_name,
                          submitted_by=current_user.get_id()
                          )
        # if result == "queued":
        #     flash(f"System busy. Optimization {run_name} added to queue.")
        # else:
        #     flash(f"Optimization {run_name} started.")

    except Exception as e:
        if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
            return jsonify({"error": e.__str__()})
        else:
            flash(e.__str__())
    return redirect(url_for("execute.experiment_run"))


@execute.route("/executions/latest_plot", methods=["GET"])
@login_required
def get_optimizer_plot():
    """
    .. :quickref: Workflow Execution; Get latest optimization plots

    **Optimizer Plots**

    .. http:get:: /executions/latest_plot

    Retrieve the most recently generated visualization plots from the active Bayesian Optimization campaign.

    :status 200: Returns a JSON dictionary of plot HTML snippets or an image file.
    :status 404: No plots found.
    """

    optimizer = current_app.config.get("LAST_OPTIMIZER")
    if optimizer is not None:
        plots = optimizer.get_plots('all')
        if plots:
            if isinstance(plots, dict):
                return jsonify(plots)
            else:
                return send_file(plots, mimetype="image/png")
    return jsonify({"error": "No plots found"}), 404



@execute.route("/executions/queue", methods=["GET"])
@login_required
def get_queue():
    """
    .. :quickref: Workflow Execution Queue; Get queued tasks

    .. http:get:: /executions/queue

    Retrieve the current execution queue and queue state.

    :status 200: Returns queue status as JSON.
    """
    return jsonify(runner.get_queue_status())


@execute.route("/executions/queue/delete", methods=["POST"])
@login_required
def delete_queue_task():
    """
    .. :quickref: Workflow Execution Queue; Delete queued task

    .. http:post:: /executions/queue/delete

    Remove a pending task from the execution queue.

    :json id: Queue task ID to remove.
    :status 200: Task removed.
    :status 400: Task could not be removed.
    """
    try:
        data = request.get_json()
        task_id = data.get("id")
        if runner.remove_task(task_id):
            return jsonify({"status": "ok"})
        return jsonify({"error": "Failed to remove task"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@execute.route("/executions/queue/reorder", methods=["POST"])
@login_required
def reorder_queue_task():
    """
    .. :quickref: Workflow Execution Queue; Reorder queued task

    .. http:post:: /executions/queue/reorder

    Move a pending task up or down in the execution queue.

    :json id: Queue task ID to move.
    :json direction: Direction to move the task.
    :status 200: Task reordered.
    :status 400: Task could not be reordered.
    """
    try:
        data = request.get_json()
        task_id = data.get("id")
        direction = data.get("direction")
        if runner.reorder_tasks(task_id, direction):
            return jsonify({"status": "ok"})
        return jsonify({"error": "Failed to reorder task"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@execute.route("/executions/queue/task/<int:task_id>", methods=["GET"])
@login_required
def get_queue_task_details(task_id):
    """
    .. :quickref: Workflow Execution Queue; Get queued task details

    .. http:get:: /executions/queue/task/<int:task_id>

    Retrieve the full payload for a queued task.

    :param task_id: Queue task ID.
    :status 200: Returns task details.
    :status 404: Task not found.
    """
    details = runner.get_task_details(task_id)
    if details:
        return jsonify(details)
    return jsonify({"error": "Task not found"}), 404


@execute.route("/executions/current_task", methods=["GET"])
@login_required
def get_current_task_details():
    """
    .. :quickref: Workflow Execution Queue; Get current task details

    .. http:get:: /executions/current_task

    Retrieve details for the currently running task.

    :status 200: Returns current task details.
    :status 404: No task currently running.
    """
    details = runner.get_current_task_details()
    if details:
        return details
    return jsonify({"error": "No task currently running"}), 200


@execute.route("/executions/queue/task/rename", methods=["POST"])
@login_required
def rename_queue_task():
    """
    .. :quickref: Workflow Execution Queue; Rename queued task

    .. http:post:: /executions/queue/task/rename

    Update the display name for a queued task.

    :json id: Queue task ID to rename.
    :json new_name: New display name.
    :status 200: Task renamed.
    :status 400: Task could not be renamed.
    """
    try:
        data = request.get_json()
        task_id = data.get("id")
        new_name = data.get("new_name")
        if runner.update_task_name(task_id, new_name):
            return jsonify({"status": "ok"})
        return jsonify({"error": "Failed to rename task"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


TASK_NOT_QUEUED = "This task is no longer in the queue; it has started or was removed."


@execute.route("/executions/queue/task/<uid>/conditions", methods=["GET"])
@login_required
def get_queue_task_conditions(uid):
    """
    .. :quickref: Workflow Execution Queue; Get editable conditions of a queued task

    .. http:get:: /executions/queue/task/<uid>/conditions

    Retrieve the experiment name and run conditions of a queued task in a shape
    that can be edited: its repeat count, its config entries, or its optimization
    campaign settings.

    :param uid: Queue task UID, as listed by :http:get:`/executions/queue`.
    :status 200: Returns the task's conditions.
    :status 404: The task has started or was removed from the queue.
    """
    conditions = runner.get_task_conditions(uid)
    if conditions is None:
        return jsonify({"error": TASK_NOT_QUEUED}), 404
    return jsonify(conditions)


@execute.route("/executions/queue/task/<uid>/conditions", methods=["POST"])
@login_required
def update_queue_task_conditions(uid):
    """
    .. :quickref: Workflow Execution Queue; Edit conditions of a queued task

    .. http:post:: /executions/queue/task/<uid>/conditions

    Change the experiment name and run conditions of a task that has not started
    yet. Only the fields sent are changed, and nothing is changed if any of them
    is invalid.

    :param uid: Queue task UID, as listed by :http:get:`/executions/queue`.
    :json name: Experiment name the run is saved under; made unique like a new run's.
    :json repeat_count: Repeat count, or iterations of an optimization campaign.
    :json batch_size: Batch size.
    :json config: Config entries, as a list of ``{input name: value}``.
    :json parameters: Campaign parameters, as ``{name, type, min, max, step, choices, value}``.
    :json objectives: Campaign objectives, as ``{name, goal, early_stop}``.
    :json constraints: Campaign constraint expressions.
    :json steps: Optimizer steps, as ``{step key: {model, num_samples}}``.
    :json additional_params: Optimizer settings, as ``{name: value}``.
    :status 200: Conditions updated.
    :status 400: A value is not usable; the error says which.
    :status 404: The task has started or was removed from the queue.
    """
    try:
        updated = runner.update_task_conditions(uid, request.get_json(silent=True), unique_name=_unique_run_name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not updated:
        return jsonify({"error": TASK_NOT_QUEUED}), 404
    return jsonify({"status": "ok"})


NO_CONFIG_RUN = "No config table run is in progress; it may have just finished."


@execute.route("/executions/current_task/config", methods=["GET"])
@login_required
def get_running_config():
    """
    .. :quickref: Workflow Execution Queue; Get the running task's config table

    .. http:get:: /executions/current_task/config

    Retrieve the config table of the running task, with each row's status:
    ``done``, ``running``, ``pending``, or ``skipped`` with the reason.

    :status 200: Returns the table.
    :status 404: The running task does not run a config table, or nothing runs.
    """
    table = runner.get_running_config()
    if table is None:
        return jsonify({"error": NO_CONFIG_RUN}), 404
    return jsonify(table)


@execute.route("/executions/current_task/config", methods=["POST"])
@login_required
def edit_running_config():
    """
    .. :quickref: Workflow Execution Queue; Edit the running task's config table

    .. http:post:: /executions/current_task/config

    Edit, add, remove or reorder the rows the running task has not finished.
    Edits to the running row reach the steps it has not run yet. Rows that
    finished are left as they ran.

    :json uid: UID of the running task, as returned by :http:get:`/executions/current_task/config`.
    :json rows: The running and pending rows in their new order, as ``{id, values, number}``,
                with ``id`` null for a new row.
    :status 200: Applied; ``notes`` lists changes the run had already moved past.
    :status 400: A value cannot run; the error says which, and nothing changed.
    :status 404: That task is no longer running.
    """
    payload = request.get_json(silent=True) or {}
    try:
        notes = runner.edit_running_config(payload.get("uid"), payload.get("rows"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if notes is None:
        return jsonify({"error": NO_CONFIG_RUN}), 404
    return jsonify({"status": "ok", "notes": notes})


@execute.route("/executions/status", methods=["GET"])
def runner_status():
    """
    .. :quickref: Workflow Execution Control; Get backend runner status

    **Runner Status**

    .. http:get:: /executions/status

    Check if the system is currently busy and retrieve details about the active task or workflow.

    :status 200: Returns a JSON object containing the 'busy' state and current task details.
    """
    # runner = global_state.runner
    runner_busy = global_state.runner_lock.locked() or len(runner.execution_queue) > 0
    status = {"busy": runner_busy, "paused": runner.pause_status()}
    task_status = global_state.runner_status
    current_step = {}

    if task_status is not None:
        task_type = task_status["type"]
        task_id = task_status["id"]
        if task_type == "task":
            # todo
            step = db.session.get(SingleStep, task_id)
            if step is not None:
                current_step = step.as_dict()
        if task_type == "workflow":
            workflow = db.session.get(WorkflowRun, task_id)
            if workflow is not None:
                phases = WorkflowPhase.query.filter_by(run_id=workflow.id).order_by(WorkflowPhase.start_time).all()
                latest_step = None
                if phases:
                    current_phase = phases[-1]
                    latest_step = WorkflowStep.query.filter_by(phase_id=current_phase.id).order_by(
                        WorkflowStep.start_time.desc()).first()
                    if latest_step is not None:
                        current_step = latest_step.as_dict()
                status["workflow_status"] = {"workflow_info": workflow.as_dict(), "runner_status": runner.get_status()}
    status["current_task"] = current_step
    return jsonify(status), 200


@execute.route("/executions/abort/next-iteration", methods=["POST"])
def api_abort_pending():
    """
    .. :quickref: Workflow Execution control; abort pending workflow

    finish the current iteration and stop pending workflow iterations

    .. http:post:: /executions/abort/next-iteration

    """
    abort_pending()
    return jsonify({"status": "ok"}), 200


@execute.route("/executions/abort/next-task", methods=["POST"])
def api_abort_current():
    """
    .. :quickref: Workflow Execution Control; abort all pending tasks starting from the next task

    finish the current task and stop all pending tasks or iterations

    .. http:post:: /executions/abort/next-task

    """
    abort_current()
    return jsonify({"status": "ok"}), 200


@execute.route("/executions/pause-resume", methods=["POST"])
def api_pause():
    """
    .. :quickref: Workflow Execution Control; pause and resume

    pause workflow iterations or resume workflow iterations

    .. http:post:: /executions/pause-resume

    """
    msg = pause()
    return jsonify({"status": "ok", "pause_status": msg}), 200


@execute.route("/executions/retry", methods=["POST"])
def api_retry():
    """
    .. :quickref: Workflow Execution Control; retry the failed workflow execution step.

    retry the failed workflow execution step.

    .. http:post:: /executions/retry

    """
    retry()
    return jsonify({"status": "ok, retrying failed step"}), 200


@execute.route('/files/preview/<string:filename>')
@login_required
def data_preview(filename):
    """
    .. :quickref: Workflow Execution Files; preview a workflow history file (.CSV)

    Preview the contents of a workflow history file in CSV format.

    .. http:get:: /files/preview/<str:filename>
    """
    import csv
    import os
    from flask import abort

    data_folder = current_app.config['DATA_FOLDER']
    file_path = os.path.join(data_folder, filename)
    if not os.path.exists(file_path):
        abort(404)
    with open(file_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)
    # Limit preview to first 10 rows
    return jsonify({"columns": reader.fieldnames, "rows": rows})


