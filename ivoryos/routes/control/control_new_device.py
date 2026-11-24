import inspect
import importlib
import os
from flask import Blueprint, request, current_app, flash, redirect, url_for, session, render_template
from flask_login import login_required

from ivoryos.services.connection_history import save_to_history
from ivoryos.services.draft_service import get_script_file
from ivoryos.runtime.state import GlobalState
from ivoryos.parsers.type_conversions import convert_config_type
from ivoryos.parsers.introspection import create_module_interface_schema, generate_interface_schema
from ivoryos.routes.control.utils import import_module_by_filepath


global_state = GlobalState()

control_temp = Blueprint('temp', __name__)

@control_temp.route("/new/module", methods=['POST'])
def import_api():
    """
    .. :quickref: Advanced Features; Manually import API module(s)

    importing other Python modules

    .. http:post:: /instruments/new/module

    :form filepath: API (Python class) module filepath

    import the module and redirect to :http:get:`/ivoryos/instruments/new/`

    """
    filepath = request.form.get('filepath')
    # filepath.replace('\\', '/')
    name = os.path.split(filepath)[-1].split('.')[0]
    try:
        spec = importlib.util.spec_from_file_location(name, filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls_dict = create_module_interface_schema(module=module)

        def merge_to_global(old: dict, new: dict):
            overwritten = []

            for key, value in new.items():
                if key in old:
                    overwritten.append(key)  # record duplicates
                old[key] = value  # overwrite or insert

            return overwritten

        duplicates = merge_to_global(global_state.api_variables, cls_dict)
        if duplicates:
            # optionally, you can log duplicates
            flash(f"Overwritten classes: {', '.join(duplicates)}")
    # should handle path error and file type error
    except Exception as e:
        flash(e.__str__())
    return redirect(url_for("control.temp.new_controller"))



@control_temp.route("/new/deck-python", methods=['POST'])
def import_deck():
    """
    .. :quickref: Advanced Features; Manually import a deck

    .. http:post:: /instruments/new/deck-python

    :form filepath: deck module filepath

    import the module and redirect to the previous page

    """
    script = get_script_file()
    filepath = request.form.get('filepath')
    session['dismiss'] = request.form.get('dismiss')
    update = request.form.get('update')
    back = request.referrer
    if session['dismiss']:
        return redirect(back)
    name = os.path.split(filepath)[-1].split('.')[0]
    try:
        module = import_module_by_filepath(filepath=filepath, name=name)
        save_to_history(filepath, current_app.config["DECK_HISTORY"])
        module_sigs = generate_interface_schema(module, save=update, output_path=current_app.config["DUMMY_DECK"],
                                                exclude_names=current_app.config.get("DECK_EXCLUDE_NAMES"),
                                                include_names=current_app.config.get("DECK_INCLUDE_NAMES"))
        if not len(module_sigs) > 0:
            flash("Invalid hardware deck, connect instruments in deck script", "error")
            return redirect(url_for("control.deck_controllers"))
        global_state.deck = module
        global_state.interface_schema = module_sigs

        if script.deck is None:
            script.deck = module.__name__
    # file path error exception
    except Exception as e:
        flash(e.__str__())
    return redirect(back)


@control_temp.route("/new/", strict_slashes=False)
@control_temp.route("/new/<string:instrument>", methods=['GET', 'POST'])
@login_required
def new_controller(instrument:str=None):
    """
    .. :quickref: Advanced Features; connect to a new device

    interface for connecting a new <instrument>

    .. http:get:: /instruments/new/

    .. http:get:: /instruments/new/<string:instrument>

    :param instrument: instrument name
    :type instrument: str

    .. http:post:: /instruments/new/<string:instrument>

    :form device_name: module instance name (e.g. my_instance = MyClass())
    :form kwargs: dynamic module initialization kwargs fields

    """
    device = None
    args = None
    if instrument:

        device = global_state.api_variables[instrument]
        args = inspect.signature(device.__init__)

        if request.method == 'POST':
            device_name = request.form.get("device_name", "")
            if device_name and device_name in globals():
                flash("Device name is defined. Try another name, or leave it as blank to auto-configure")
                # return render_template('controllers_new.html', instrument=instrument,
                #                        api_variables=global_state.api_variables,
                #                        device=device, args=args, defined_variables=global_state.defined_variables)
            if device_name == "":
                device_name = device.__name__.lower() + "_"
                num = 1
                while device_name + str(num) in global_state.defined_variables:
                    num += 1
                device_name = device_name + str(num)
            kwargs = request.form.to_dict()
            kwargs.pop("device_name")
            for i in kwargs:
                if kwargs[i] in global_state.defined_variables:
                    kwargs[i] = global_state.defined_variables[kwargs[i]]
            try:
                convert_config_type(kwargs, device.__init__.__annotations__, is_class=True)
            except Exception as e:
                flash(e)
            try:
                global_state.defined_variables[device_name] = device(**kwargs)
                # global_state.defined_variables.add(device_name)
                return redirect(url_for('control.deck_controllers'))
            except Exception as e:
                flash(e)
    return render_template('controllers_new.html', instrument=instrument, api_variables=global_state.api_variables,
                           device=device, args=args, defined_variables=global_state.defined_variables)
