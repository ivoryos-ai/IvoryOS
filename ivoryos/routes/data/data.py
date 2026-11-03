import os
import csv
import io

from flask import Blueprint, request, render_template, current_app, jsonify, send_file, Response
from flask_login import login_required

from sqlalchemy import or_

from ivoryos.models import db, WorkflowRun, WorkflowPhase
from ivoryos.runtime.run_events import LABELS as RUN_EVENT_LABELS, ROWS_NOT_RUN, TABLE_EDITED
from ivoryos.runtime.state import GlobalState
from ivoryos.script.editor import ScriptEditor

data = Blueprint('data', __name__, template_folder='templates')


def _running_run_id():
    """Id of the workflow run in progress, or ``None``; its outcome is only kept once it ends."""
    state = GlobalState()
    status = state.runner_status
    if not state.runner_lock.locked() or not status or status.get("type") != "workflow":
        return None
    return status.get("id")



@data.route('/executions/records')
@login_required
def list_workflows():
    """
    .. :quickref: Workflow Execution Database; List all execution records

    **List Workflows**

    .. http:get:: /executions/records

    Retrieve a list of all past workflow execution records, with optional keyword searching.

    :query keyword: Optional search term to filter workflows by name or by who submitted them.
    :query page: The page number for pagination.
    :status 200: Returns a list of workflow records (HTML or JSON).
    """
    query = WorkflowRun.query
    search_term = request.args.get("keyword", None)
    if search_term:
        query = query.filter(or_(WorkflowRun.name.like(f'%{search_term}%'),
                                 WorkflowRun.submitted_by.like(f'%{search_term}%')))

    sort_by = request.args.get('sort_by', 'id')
    order = request.args.get('order', 'desc')

    sort_mapping = {
        'name': WorkflowRun.name,
        'id': WorkflowRun.id,
        'submitted_by': WorkflowRun.submitted_by,
        'start_time': WorkflowRun.start_time,
        'end_time': WorkflowRun.end_time
    }

    sort_column = sort_mapping.get(sort_by, WorkflowRun.id)

    if order == 'asc':
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=10, type=int)
    if per_page not in [10, 20, 50]:
        per_page = 10

    workflows = query.paginate(page=page, per_page=per_page, error_out=False)
    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
        workflows = query.all()
        workflow_data = {w.id: {"workflow_name": w.name, "start_time": w.start_time, "submitted_by": w.submitted_by}
                         for w in workflows}
        return jsonify({
            "workflow_data": workflow_data,
        })
    else:
        return render_template('workflow_database.html', workflows=workflows, deck_name=None,
                               current_per_page=per_page, current_sort_by=sort_by, current_order=order,
                               running_run_id=_running_run_id())
@data.get("/executions/records/<int:workflow_id>")
def workflow_logs(workflow_id:int):
    """
    .. :quickref: Workflow Data Database; Get workflow logs and steps

    **Workflow Logs**

    .. http:get:: /executions/records/<int:workflow_id>

    Retrieve detailed logs, execution steps, and phases for a specific workflow by its ID.

    :param workflow_id: The unique ID of the workflow run.
    :status 200: Returns the workflow logs and phase details.
    :status 404: Workflow record not found.
    """
    workflow = db.session.get(WorkflowRun, workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    # Query all phases for this run, ordered by start_time
    phases = WorkflowPhase.query.filter_by(run_id=workflow_id).order_by(WorkflowPhase.start_time).all()

    # Prepare grouped data for template (full objects)
    grouped = {
        "prep": [],
        "script": {},
        "cleanup": [],
    }

    # Prepare grouped data for JSON (dicts)
    grouped_json = {
        "prep": [],
        "script": {},
        "cleanup": [],
    }

    for phase in phases:
        phase_dict = phase.as_dict()

        # Steps sorted by step_index
        steps = sorted(phase.steps, key=lambda s: s.step_index)
        phase_steps_dicts = [s.as_dict() for s in steps]

        if phase.name == "prep":
            grouped["prep"].append(phase)
            grouped_json["prep"].append({
                **phase_dict,
                "steps": phase_steps_dicts
            })

        elif phase.name == "main":
            grouped["script"].setdefault(phase.repeat_index, []).append(phase)
            grouped_json["script"].setdefault(phase.repeat_index, []).append({
                **phase_dict,
                "steps": phase_steps_dicts
            })

        elif phase.name == "cleanup":
            grouped["cleanup"].append(phase)
            grouped_json["cleanup"].append({
                **phase_dict,
                "steps": phase_steps_dicts
            })

    if request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json':
        return jsonify({
            "workflow_info": workflow.as_dict(),
            "phases": grouped_json,
            "csv_file_name": f"{workflow.data_path}"
        })
    else:
        run_events = [{**event, "label": RUN_EVENT_LABELS.get(event.get("kind"), event.get("kind"))}
                      for event in workflow.events or []]
        # each line of a table edit's event is one change, already described
        config_changes = [(event["time"], line) for event in run_events if event.get("kind") == TABLE_EDITED
                          for line in (event.get("detail") or "").split("\n") if line]
        return render_template("workflow_view.html", workflow=workflow, grouped=grouped,
                               running_run_id=_running_run_id(), run_events=run_events,
                               config_results=_config_results(workflow, grouped["script"]),
                               config_changes=config_changes)


def _config_results(workflow, iterations):
    """A config run's table as the run worked through it, read from its iterations.

    Every row the run reached became an iteration, in table order, holding the
    values its last steps used, so the rows are the iterations' parameters one
    after another, and what a row returned is what its output holds besides its
    inputs. Rows the run never reached are kept with its "rows not run" event.
    ``None`` for runs that did not run a config table.
    """
    if workflow.repeat_mode != "batch":
        return None
    rows = []
    # whether rows ran several to an iteration, so the table marks where each batch begins
    batched = False
    for iteration in sorted(iterations):
        for phase in iterations[iteration]:
            samples = phase.parameters if isinstance(phase.parameters, list) else [phase.parameters or {}]
            outputs = phase.outputs if isinstance(phase.outputs, list) else [phase.outputs]
            status = phase.status or ("done" if phase.end_time else "running")
            error = phase.error or {}
            for index, values in enumerate(samples):
                values = values or {}
                returned = outputs[index] if index < len(outputs) and isinstance(outputs[index], dict) else {}
                rows.append({"iteration": iteration, "status": status, "values": values,
                             "outputs": {key: value for key, value in returned.items() if key not in values},
                             "reason": error.get("message"), "invalid": error.get("fields") or {},
                             "starts_batch": index == 0})
            batched = batched or len(samples) > 1
    for event in workflow.events or []:
        if event.get("kind") == ROWS_NOT_RUN:
            rows.extend({"status": "pending", "values": values, "outputs": {}, "starts_batch": index == 0}
                        for index, values in enumerate(event.get("rows") or []))
    columns, outputs = [], []
    for number, row in enumerate(rows, start=1):
        row["row"] = number
        columns.extend(key for key in row["values"] if key not in columns)
        outputs.extend(key for key in row["outputs"] if key not in outputs)
    return {"rows": rows, "columns": columns, "outputs": outputs, "batched": batched}


@data.get("/executions/records/<int:workflow_id>/steps_data_csv")
@login_required
def download_workflow_steps_data_csv(workflow_id: int):
    """
    .. :quickref: Workflow Data Database; Download workflow step data CSV

    .. http:get:: /executions/records/<int:workflow_id>/steps_data_csv

    Download a CSV export of step inputs, outputs, and timing for a workflow run.

    :param workflow_id: The unique ID of the workflow run.
    :status 200: Returns a CSV file.
    :status 404: Workflow record not found.
    """
    workflow = db.session.get(WorkflowRun, workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    run_name = ScriptEditor.validate_function_name(workflow.name)
    base_data_path = workflow.data_path if workflow.data_path else f"{run_name}_{workflow.start_time.strftime('%Y-%m-%d %H-%M')}"
    base_data_path = base_data_path.replace('.csv', '')

    # Query all phases for this run
    phases = WorkflowPhase.query.filter_by(run_id=workflow_id).order_by(WorkflowPhase.start_time).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(["Phase Name", "Phase Repeat Index",
                     "Step Index", "Step Start Time", "Step End Time", "Step Run Error", "Step Method Name", "Step Output",
                     "Step Parameters"
                     ])

    for phase in phases:
        from collections import defaultdict
        steps_sorted = sorted(phase.steps, key=lambda s: s.id)
        steps_by_index = defaultdict(list)
        for step in steps_sorted:
            steps_by_index[step.step_index].append(step)

        for step_idx, steps in steps_by_index.items():
            for batch_index, step in enumerate(steps):
                params = step.workflow_phases.parameters
                if isinstance(params, list):
                    step_parameters = params[batch_index] if batch_index < len(params) else (params[0] if params else {})
                else:
                    step_parameters = params if params else {}

                step_output = step.output  # at time of writing the output contains full context of action, so both input parameters, variables, and returns
                if set(step_output) - set(step_parameters) == set():
                    # there is no difference between the step parameters and the step output -> no set variables/return values in the step
                    step_output = {}
                else:
                    output_keys = set(step_output) - set(step_parameters)
                    step_output = {k: v for k, v in step_output.items() if k in output_keys}

                writer.writerow([
                    phase.name,
                    phase.repeat_index,
                    step.step_index,
                    step.start_time,
                    step.end_time,
                    step.run_error,
                    step.method_name,
                    step_output,
                    step_parameters,
                ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={base_data_path}_steps.csv"}
    )


def _partial_outputs(phase):
    """What an iteration that never finished got done, one row per sample.

    A step keeps the whole context of the sample it ran for, inputs included, so
    each finished step is matched to the sample whose inputs it agrees with most,
    and a sample's row is the last step that ran for it. A shared step only keeps
    the first sample's context, so its values reach the other samples' rows once
    one of their own steps has run.
    """
    from ivoryos.models import WorkflowStep
    samples = phase.parameters if isinstance(phase.parameters, list) else [phase.parameters]
    samples = [sample if isinstance(sample, dict) else {} for sample in samples] or [{}]
    latest = [None] * len(samples)
    steps = WorkflowStep.query.filter(
        WorkflowStep.phase_id == phase.id,
        WorkflowStep.end_time.isnot(None)
    ).order_by(WorkflowStep.id).all()
    for step in steps:
        if not isinstance(step.output, dict):
            continue
        scores = [sum(step.output.get(key) == value for key, value in sample.items()) for sample in samples]
        best = max(scores)
        for index, score in enumerate(scores):
            if score == best:
                latest[index] = step.output
    return [output for output in latest if output]


@data.get("/executions/records/<int:workflow_id>/data_csv")
@login_required
def download_workflow_data_csv(workflow_id: int):
    """
    Download a dynamically generated CSV export of the workflow's main data.
    """
    import pandas as pd
    from ivoryos.script.editor import ScriptEditor

    workflow = db.session.get(WorkflowRun, workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow not found"}), 404

    run_name = ScriptEditor.validate_function_name(workflow.name)
    base_data_path = workflow.data_path if workflow.data_path else f"{run_name}_{workflow.start_time.strftime('%Y-%m-%d %H-%M')}"
    if not base_data_path.endswith('.csv'):
        base_data_path += '.csv'

    main_phases = WorkflowPhase.query.filter_by(run_id=workflow_id, name='main') \
        .order_by(WorkflowPhase.repeat_index).all()

    output_list = []
    for phase in main_phases:
        if phase.outputs:
            outputs = phase.outputs
            if isinstance(outputs, dict):
                outputs = [outputs]
            elif isinstance(outputs, list):
                outputs = [
                    item for sublist in outputs
                    for item in (sublist if isinstance(sublist, list) else [sublist])
                ]
            output_list.extend(outputs)
        else:
            # Phase is running or failed, so its steps hold what it got done
            output_list.extend(_partial_outputs(phase))

    if not output_list:
        return "No data available yet.", 404

    df = pd.DataFrame(output_list)
    return Response(
        df.to_csv(index=False),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={base_data_path}"}
    )


@data.get("/executions/records/<int:workflow_id>/optimizer_plots")
@login_required
def get_optimizer_plots(workflow_id: int):
    """
    Retrieve saved optimizer plots (Ax HTML or Nimo PNG base64) for a workflow.
    """
    import json
    import base64
    from ivoryos.script.editor import ScriptEditor
    
    workflow = db.session.get(WorkflowRun, workflow_id)
    if not workflow:
        print(f"DEBUG get_optimizer_plots: Workflow {workflow_id} not found")
        return jsonify({"error": "Workflow not found"}), 404
        
    run_name = ScriptEditor.validate_function_name(workflow.name)
    base_data_path = workflow.data_path if workflow.data_path else f"{run_name}_{workflow.start_time.strftime('%Y-%m-%d %H-%M')}"
    base_data_path = base_data_path.replace('.csv', '')
    
    output_path = current_app.config["DATA_FOLDER"]
    plots_json_path = os.path.join(output_path, f"{base_data_path}_plots.json")
    print(f"DEBUG get_optimizer_plots: Looking for {plots_json_path}")
    
    if not os.path.exists(plots_json_path):
        print(f"DEBUG get_optimizer_plots: File not found {plots_json_path}")
        return jsonify({"error": "No plots found"}), 404
        
    with open(plots_json_path, 'r') as f:
        try:
            plots_data = json.load(f)
        except Exception:
            return jsonify({"error": "Failed to read plots data"}), 500
            
    if isinstance(plots_data, dict):
        return jsonify({"type": "html", "plots": plots_data})
    elif isinstance(plots_data, str) and plots_data.endswith(".png"):
        if not os.path.exists(plots_data):
             return jsonify({"error": "Image file not found"}), 404
        with open(plots_data, 'rb') as img_f:
             encoded = base64.b64encode(img_f.read()).decode('utf-8')
        return jsonify({"type": "image", "data": encoded})
    else:
        return jsonify({"error": "Unknown plot format"}), 500


@data.get("/executions/records/<int:workflow_id>/logs")
@login_required
def download_workflow_logs(workflow_id: int):
    """
    .. :quickref: Workflow Data Database; Download workflow log file

    .. http:get:: /executions/records/<int:workflow_id>/logs

    Download the log file associated with a workflow run.

    :param workflow_id: The unique ID of the workflow run.
    :status 200: Returns a log file.
    :status 404: Workflow record or log file not found.
    """
    workflow = db.session.get(WorkflowRun, workflow_id)
    if not workflow:
        return jsonify({"error": "Workflow record not found"}), 404

    run_name = ScriptEditor.validate_function_name(workflow.name)
    log_filename = f"{run_name}_{workflow.start_time.strftime('%Y-%m-%d %H-%M-%S')}.log"
    log_path = os.path.join(current_app.config["LOG_FOLDER"], log_filename)
    if not os.path.exists(log_path):
        return jsonify({"error": "Log file not found on disk"}), 404

    return send_file(os.path.abspath(log_path), as_attachment=True)


@data.get("/executions/data/<int:workflow_id>")
def workflow_phase_data(workflow_id: int):
    """
    .. :quickref: Workflow Data Database; Get workflow data for plotting

    **Workflow Phase Data**

    .. http:get:: /executions/data/<int:workflow_id>

    Get normalized data from the 'main' phases of a workflow for visualization and plotting.

    :param workflow_id: The unique ID of the workflow run.
    :status 200: Returns a JSON object with plotting data.
    """

    workflow = db.session.get(WorkflowRun, workflow_id)
    if not workflow:
        return jsonify({})

    phase_data = {}
    main_phases = WorkflowPhase.query.filter_by(run_id=workflow_id, name='main') \
        .order_by(WorkflowPhase.repeat_index).all()

    for phase in main_phases:
        outputs = phase.outputs or {}
        phase_index = phase.repeat_index
        phase_data[phase_index] = {}

        # Normalize everything to a list of dicts
        if isinstance(outputs, dict):
            outputs = [outputs]
        elif isinstance(outputs, list):
            # flatten if it’s nested like [[{...}, {...}]]
            outputs = [
                item for sublist in outputs
                for item in (sublist if isinstance(sublist, list) else [sublist])
            ]

        # convert each output entry to plotting format
        for out in outputs:
            if not isinstance(out, dict):
                continue
            for k, v in out.items():
                if isinstance(v, (int, float)):
                    phase_data[phase_index].setdefault(k, []).append(
                        {"x": phase_index, "y": v}
                    )
                elif isinstance(v, list) and all(isinstance(i, (int, float)) for i in v):
                    phase_data[phase_index].setdefault(k, []).extend(
                        {"x": phase_index, "y": val} for val in v
                    )

    return jsonify(phase_data)


@data.delete("/executions/records/<int:workflow_id>")
@login_required
def delete_workflow_record(workflow_id: int):
    """
    .. :quickref: Workflow Data Database; Delete an execution record

    **Delete Workflow Record**

    .. http:delete:: /executions/records/<int:workflow_id>

    Permanently delete a workflow execution record from the database by its ID.

    :param workflow_id: The unique ID of the workflow run.
    :status 200: Returns success on deletion.
    :status 404: Workflow record not found.
    """
    run = db.session.get(WorkflowRun, workflow_id)
    if run is None:
        return jsonify(success=False, error="Workflow run not found"), 404

    db.session.delete(run)
    db.session.commit()
    return jsonify(success=True)


@data.route('/files/execution-data/<string:filename>')
@login_required
def download_results(filename:str):
    """
    .. :quickref: Workflow data; download a workflow data file (.CSV)

    .. http:get:: /files/execution-data/<string:filename>

    :param filename: workflow data filename
    :type filename: str

    # :status 302: load pseudo deck and then redirects to :http:get:`/ivoryos/executions/records`
    """

    filepath = os.path.join(current_app.config["DATA_FOLDER"], filename)
    return send_file(os.path.abspath(filepath), as_attachment=True)
