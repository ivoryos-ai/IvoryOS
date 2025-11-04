import csv
import os
import time

from flask import Blueprint, redirect, url_for, flash, jsonify, request, render_template, session, \
    current_app, g
from flask_login import login_required

from ivoryos.routes.execute.execute_file import files
from ivoryos.utils import utils
from ivoryos.utils.bo_campaign import parse_optimization_form
from ivoryos.utils.db_models import SingleStep, WorkflowRun, WorkflowStep, WorkflowPhase
from ivoryos.utils.global_config import GlobalConfig
from ivoryos.utils.form import create_action_button

from werkzeug.utils import secure_filename

from ivoryos.socket_handlers import runner, retry, pause, abort_pending, abort_current

execute = Blueprint('execute', __name__, template_folder='templates')

execute.register_blueprint(files)
# Register sub-blueprints
global_config = GlobalConfig()


@execute.route("/executions/config", methods=['GET', 'POST'])
@login_required
def experiment_run():
    """
    .. :quickref: Workflow Execution Config; Execute/iterate the workflow

    .. http:get:: /executions/config

    Load the experiment execution interface.

    .. http:post:: /executions/config

    Start workflow execution with experiment configuration.

    """
    deck = global_config.deck
    script = utils.get_script_file()
    # runner = global_config.runner
    existing_data = None
    # script.sort_actions() # handled in update list
    off_line = current_app.config["OFF_LINE"]
    deck_list = utils.import_history(os.path.join(current_app.config["OUTPUT_FOLDER"], 'deck_history.txt'))
    optimizers_schema = {k: v.get_schema() for k, v in global_config.optimizers.items()}
    design_buttons = {stype: create_action_button(script, stype) for stype in script.stypes}
    config_preview = []
    config_file_list = [i for i in os.listdir(current_app.config["CSV_FOLDER"]) if not i == ".gitkeep"]

    try:
        exec_string = script.python_script if script.python_script else script.compile(
            current_app.config['SCRIPT_FOLDER'])
    except Exception as e:
        flash(e.__str__())
        if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
            return jsonify({"error": e.__str__()})
        else:
            return redirect(url_for("design.experiment_builder"))

    config_file = request.args.get("filename")
    config = []
    if config_file:
        session['config_file'] = config_file
    filename = session.get("config_file")
    if filename:
        config = list(csv.DictReader(open(os.path.join(current_app.config['CSV_FOLDER'], filename))))
        config_preview = config[1:]
        arg_type = config.pop(0)  # first entry is types

    try:
        # Handle both string and dict exec_string
        if isinstance(exec_string, dict):
            for key, func_str in exec_string.items():
                exec(func_str)

        else:
            # Handle string case - you might need to adjust this based on your needs
            line_collection = {}
    except Exception:
        flash(f"Please check syntax!!")
        return redirect(url_for("design.experiment_builder"))


    line_collection = script.render_script_lines(script.script_dict)

    run_name = script.name if script.name else "untitled"

    dismiss = session.get("dismiss", None)
    script = utils.get_script_file()
    no_deck_warning = False

    _, return_list = script.config_return()
    config_list, config_type_list = script.config("script")
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
        bo_args = None
        compiled = False
        if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
            payload_json = request.get_json()
            compiled = True
            if "kwargs" in payload_json:
                config = payload_json["kwargs"]
            elif "parameters" in payload_json:
                bo_args = payload_json
            repeat = payload_json.pop("repeat", None)
            batch_size = payload_json.pop('batch_size', 1)
        else:
            if "bo" in request.form:
                bo_args = request.form.to_dict()
                existing_data = bo_args.pop("existing_data")
            if "online-config" in request.form:
                config_args = request.form.to_dict()
                config_args.pop("batch_size", None)
                config = utils.web_config_entry_wrapper(config_args, config_list)
            batch_size = int(request.form.get('batch_size', 1))
            repeat = request.form.get('repeat', None)

        try:
        # if True:
            datapath = current_app.config["DATA_FOLDER"]
            run_name = script.validate_function_name(run_name)
            runner.run_script(script=script, run_name=run_name, config=config, bo_args=bo_args,
                              logger=g.logger, socketio=g.socketio, repeat_count=repeat,
                              output_path=datapath, compiled=compiled, history=existing_data,
                              current_app=current_app._get_current_object(), batch_size=batch_size
                              )
            if utils.check_config_duplicate(config):
                flash(f"WARNING: Duplicate in config entries.")
        except Exception as e:
            if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
                return jsonify({"error": e.__str__()})
            else:
                flash(e)

    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
        # wait to get a workflow ID
        while not global_config.runner_status:
            time.sleep(1)
        return jsonify({"status": "task started", "task_id": global_config.runner_status.get("id")})
    else:
        return render_template('experiment_run.html', script=script.script_dict, filename=filename,
                               dot_py=exec_string, line_collection=line_collection,
                               return_list=return_list, config_list=config_list, config_file_list=config_file_list,
                               config_preview=config_preview, data_list=data_list, config_type_list=config_type_list,
                               no_deck_warning=no_deck_warning, dismiss=dismiss, design_buttons=design_buttons,
                               history=deck_list, pause_status=runner.pause_status(), optimizer_schema=optimizers_schema)

@execute.route("/executions/campaign", methods=["POST"])
@login_required
def run_bo():
    """
    .. :quickref: Workflow Execution; run Bayesian Optimization

    Run Bayesian Optimization with the given parameters and objectives.

    .. http:post:: /executions/campaign

    :form repeat: number of iterations to run
    :form optimizer_type: type of optimizer to use
    :form existing_data: existing data to use for optimization
    :form parameters: parameters for optimization
    :form objectives: objectives for optimization

    TODO: merge to experiment_run or not, add more details about the form fields and their expected values.
    """
    script = utils.get_script_file()
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

    else:
        payload = request.form.to_dict()
        repeat = payload.pop("repeat", None)
        optimizer_type = payload.pop("optimizer_type", None)
        existing_data = payload.pop("existing_data", None)
        batch_mode = payload.pop("batch_mode", None)
        batch_size = payload.pop("batch_size", 1)

        # Get constraint expressions (new single-line input)
        constraint_exprs = request.form.getlist("constraint_expr")
        constraints = [expr.strip() for expr in constraint_exprs if expr.strip()]

        # Remove constraint_expr entries from payload before parsing parameters
        for key in list(payload.keys()):
            if key.startswith("constraint_expr"):
                payload.pop(key, None)

        parameters, objectives, steps = parse_optimization_form(payload)

    # if True:
        datapath = current_app.config["DATA_FOLDER"]
        run_name = script.validate_function_name(run_name)
        Optimizer = global_config.optimizers.get(optimizer_type, None)
        if not Optimizer:
            raise ValueError(f"Optimizer {optimizer_type} is not supported or not found.")
        optimizer = Optimizer(experiment_name=run_name, parameter_space=parameters, objective_config=objectives,
                              parameter_constraints = constraints,
                              optimizer_config=steps, datapath=datapath)
        runner.run_script(script=script, run_name=run_name, optimizer=optimizer,
                          logger=g.logger, socketio=g.socketio, repeat_count=repeat,
                          output_path=datapath, compiled=False, history=existing_data,
                          current_app=current_app._get_current_object(), batch_size=int(batch_size),
                          objectives=objectives
                          )

    except Exception as e:
        if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
            return jsonify({"error": e.__str__()})
        else:
            flash(e.__str__())
    return redirect(url_for("execute.experiment_run"))



@execute.route("/executions/status", methods=["GET"])
def runner_status():
    """
    .. :quickref: Workflow Execution Control; backend runner status

    get is system is busy and current task

    .. http:get:: /executions/status


    """
    # runner = global_config.runner
    runner_busy = global_config.runner_lock.locked()
    status = {"busy": runner_busy}
    task_status = global_config.runner_status
    current_step = {}

    if task_status is not None:
        task_type = task_status["type"]
        task_id = task_status["id"]
        if task_type == "task":
            # todo
            step = SingleStep.query.get(task_id)
            current_step = step.as_dict()
        if task_type == "workflow":
            workflow = WorkflowRun.query.get(task_id)
            if workflow is not None:
                phases = WorkflowPhase.query.filter_by(run_id=workflow.id).order_by(WorkflowPhase.start_time).all()
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

    .. http:get:: /executions/abort/next-iteration

    """
    abort_pending()
    return jsonify({"status": "ok"}), 200


@execute.route("/executions/abort/next-task", methods=["POST"])
def api_abort_current():
    """
    .. :quickref: Workflow Execution Control; abort all pending tasks starting from the next task

    finish the current task and stop all pending tasks or iterations

    .. http:get:: /executions/abort/next-task

    """
    abort_current()
    return jsonify({"status": "ok"}), 200


@execute.route("/executions/pause-resume", methods=["POST"])
def api_pause():
    """
    .. :quickref: Workflow Execution Control; pause and resume

    pause workflow iterations or resume workflow iterations

    .. http:get:: /executions/pause-resume

    """
    msg = pause()
    return jsonify({"status": "ok", "pause_status": msg}), 200


@execute.route("/executions/retry", methods=["POST"])
def api_retry():
    """
    .. :quickref: Workflow Execution Control; retry the failed workflow execution step.

    retry the failed workflow execution step.

    .. http:get:: /executions/retry

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


