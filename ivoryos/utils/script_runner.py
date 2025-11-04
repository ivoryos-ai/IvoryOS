import ast
import asyncio
import os
import threading
import time
from datetime import datetime
from typing import List, Dict, Any

import pandas as pd

from ivoryos.utils import utils, bo_campaign
from ivoryos.utils.db_models import Script, WorkflowRun, WorkflowStep, db, WorkflowPhase
from ivoryos.utils.global_config import GlobalConfig
from ivoryos.utils.decorators import BUILDING_BLOCKS
from ivoryos.utils.nest_script import validate_and_nest_control_flow

global_config = GlobalConfig()
global deck
deck = None
# global deck, registered_workflows
# deck, registered_workflows = None, None
class HumanInterventionRequired(Exception):
    pass

def pause(reason="Human intervention required"):
    handlers = global_config.notification_handlers
    if handlers:
        for handler in handlers:
            try:
                handler(reason)
            except Exception as e:
                print(f"[notify] handler {handler} failed: {e}")
    # raise error to pause workflow in gui
    raise HumanInterventionRequired(reason)

class ScriptRunner:
    def __init__(self, globals_dict=None):
        self.logger = None
        self.socketio = None
        self.retry = False
        if globals_dict is None:
            globals_dict = globals()
        self.globals_dict = globals_dict
        self.pause_event = threading.Event()  # A threading event to manage pause/resume
        self.pause_event.set()
        self.stop_pending_event = threading.Event()
        self.stop_current_event = threading.Event()
        self.is_running = False
        self.lock = global_config.runner_lock
        self.paused = False
        self.current_app = None

    def toggle_pause(self):
        """Toggles between pausing and resuming the script"""
        self.paused = not self.paused
        if self.pause_event.is_set():
            self.pause_event.clear()  # Pause the script
            return "Paused"
        else:
            self.pause_event.set()  # Resume the script
            return "Resumed"

    def pause_status(self):
        """Toggles between pausing and resuming the script"""
        return self.paused

    def reset_stop_event(self):
        """Resets the stop event"""
        self.stop_pending_event.clear()
        self.stop_current_event.clear()
        self.pause_event.set()

    def abort_pending(self):
        """Abort the pending iteration after the current is finished"""
        self.stop_pending_event.set()
        # print("Stop pending tasks")

    def stop_execution(self):
        """Force stop everything, including ongoing tasks."""
        self.stop_current_event.set()
        self.abort_pending()
        if self.lock.locked():
            self.lock.release()


    def run_script(self, script, repeat_count=1, run_name=None, logger=None, socketio=None, config=None, bo_args=None,
                   output_path="", compiled=False, current_app=None, history=None, optimizer=None, batch_mode=None,
                   batch_size=1, objectives=None):
        self.socketio = socketio
        self.logger = logger
        global deck
        if deck is None:
            deck = global_config.deck

        # print("history", history)
        if self.current_app is None:
            self.current_app = current_app
        # time.sleep(1)  # Optional: may help ensure deck readiness

        # Try to acquire lock without blocking
        if not self.lock.acquire(blocking=False):
            if logger:
                logger.info("System is busy. Please wait for it to finish or stop it before starting a new one.")
            return None

        self.reset_stop_event()

        thread = threading.Thread(
            target=self._run_with_stop_check,
            args=(script, repeat_count, run_name, logger, socketio, config, bo_args, output_path, current_app, compiled,
                  history, optimizer, batch_mode, batch_size, objectives),
        )
        thread.start()
        return thread



    async def exec_steps(self, script, section_name, phase_id, kwargs_list=None, batch_size=1):
        """
        Executes a function defined in a string line by line
        :param func_str: The function as a string
        :param kwargs: Arguments to pass to the function
        :return: The final result of the function execution
        """
        _func_str = script.python_script or script.compile()
        _, return_list = script.config_return()

        step_list: list = script.convert_to_lines(_func_str).get(section_name, [])
        global deck
        # global deck, registered_workflows
        if deck is None:
            deck = global_config.deck
        # if registered_workflows is None:
        #     registered_workflows = global_config.registered_workflows

        # for i, line in enumerate(step_list):
        #     if line.startswith("registered_workflows"):
        #
        # func_str = script.compile()
        # Parse function body from string
        temp_connections = global_config.defined_variables
        # Prepare execution environment
        exec_globals = {"deck": deck, "time":time, "pause": pause}  # Add required global objects
        # exec_globals = {"deck": deck, "time": time, "registered_workflows":registered_workflows}  # Add required global objects
        exec_globals.update(temp_connections)

        exec_locals = {}  # Local execution scope

        # Define function arguments manually in exec_locals
        # exec_locals.update(kwargs)
        index = 0
        if kwargs_list:
            results = kwargs_list.copy()
        else:
            results = []
        nest_script = validate_and_nest_control_flow(script.script_dict.get(section_name, []))

        for step in nest_script:
            action = step["action"]
            instrument = step["instrument"]
            action_id = step["id"]
            if action == "if":
                await self._execute_if_batched(step, results, phase_id=phase_id, step_index=action_id, section_name=section_name)
            elif action == "repeat":
                await self._execute_repeat_batched(step, results, phase_id=phase_id, step_index=action_id, section_name=section_name)
            elif action == "while":
                await self._execute_while_batched(step, results, phase_id=phase_id, step_index=action_id, section_name=section_name)
            elif instrument == "variable":
                await self._execute_variable_batched(step, results, phase_id=phase_id, step_index=action_id, section_name=section_name)
                print("Variable executed", "current context", context)
            else:
                # Regular action - check if batch
                if step.get("batch_action", False):
                    # Execute once for all samples
                    if results:
                        await self._execute_action_once(step, results[0], phase_id=phase_id, step_index=action_id, section_name=section_name)
                    else:
                        await self._execute_action_once(step, {}, phase_id=phase_id, step_index=action_id, section_name=section_name)
                else:
                    # Execute for each sample
                    if results:
                        for context in results:
                            await self._execute_action(step, context, phase_id=phase_id, step_index=action_id, section_name=section_name)
                            self.pause_event.wait()
                    else:
                        for _ in range(batch_size):
                            await self._execute_action(step, {}, phase_id=phase_id, step_index=action_id, section_name=section_name)
                            self.pause_event.wait()

        return results  # Return the 'results' variable

    def _run_with_stop_check(self, script: Script, repeat_count: int, run_name: str, logger, socketio, config, bo_args,
                             output_path, current_app, compiled, history=None, optimizer=None, batch_mode=None,
                             batch_size=None, objectives=None):
        time.sleep(1)
        # _func_str = script.compile()
        # step_list_dict: dict = script.convert_to_lines(_func_str)
        self._emit_progress(socketio, 1)
        filename = None
        error_flag = False
        # create a new run entry in the database
        repeat_mode = "batch" if config else "optimizer" if bo_args or optimizer else "repeat"
        with current_app.app_context():
            run = WorkflowRun(name=script.name or "untitled", platform=script.deck or "deck", start_time=datetime.now(),
                              repeat_mode=repeat_mode
                              )
            db.session.add(run)
            db.session.flush()
            run_id = run.id  # Save the ID
            db.session.commit()

            try:
            # if True:
                global_config.runner_status = {"id":run_id, "type": "workflow"}
                # Run "prep" section once
                asyncio.run(self._run_actions(script, section_name="prep", logger=logger, socketio=socketio, run_id=run_id))
                output_list = []
                _, arg_type = script.config("script")
                _, return_list = script.config_return()
                # Run "script" section multiple times
                if repeat_count:
                    asyncio.run(
                        self._run_repeat_section(repeat_count, arg_type, bo_args, output_list, script,
                                             run_name, return_list, compiled, logger, socketio,
                                             history, output_path, run_id=run_id, optimizer=optimizer,
                                             batch_mode=batch_mode, batch_size=batch_size, objectives=objectives)
                    )
                elif config:
                    asyncio.run(
                        self._run_config_section(
                            config, arg_type, output_list, script, run_name, logger,
                            socketio, run_id=run_id, compiled=compiled, batch_mode=batch_mode, batch_size=batch_size
                        )
                    )
                    # self._run_config_section(config, arg_type, output_list, script, run_name, logger,
                    #                          socketio, run_id=run_id, compiled=compiled)
                # Run "cleanup" section once
                asyncio.run(self._run_actions(script, section_name="cleanup", logger=logger, socketio=socketio,run_id=run_id))
                # Reset the running flag when done
                # Save results if necessary
                if not script.python_script and return_list:
                    # print(output_list)

                    filename = self._save_results(run_name, arg_type, return_list, output_list, logger, output_path)
                self._emit_progress(socketio, 100)

            except Exception as e:
                logger.error(f"Error during script execution: {e.__str__()}")
                error_flag = True
            finally:
                if self.lock.locked():
                    self.lock.release()
        with current_app.app_context():
            run = db.session.get(WorkflowRun, run_id)
            if run is None:
                logger.info("Error: Run not found in database.")
            else:
                run.end_time = datetime.now()
                run.data_path = filename
                run.run_error = error_flag
                db.session.commit()


    async def _run_actions(self, script, section_name="", logger=None, socketio=None, run_id=None):
        _func_str = script.python_script or script.compile()
        step_list: list = script.convert_to_lines(_func_str).get(section_name, [])
        if not step_list:
            logger.info(f'No {section_name} steps')
            return None

        logger.info(f'Executing {section_name} steps')
        if self.stop_pending_event.is_set():
            logger.info(f"Stopping execution during {section_name} section.")
            return None

        phase = WorkflowPhase(
            run_id=run_id,
            name=section_name,
            repeat_index=0,
            start_time=datetime.now()
        )
        db.session.add(phase)
        db.session.flush()
        phase_id = phase.id

        step_outputs = await self.exec_steps(script, section_name, phase_id=phase_id)
        # Save phase-level output
        phase.outputs = step_outputs
        phase.end_time = datetime.now()
        db.session.commit()
        return step_outputs

    async def _run_config_section(self, config, arg_type, output_list, script, run_name, logger, socketio, run_id,
                                  compiled=True, batch_mode=False, batch_size=1):
        if not compiled:
            for i in config:
                try:
                    i = utils.convert_config_type(i, arg_type)
                    compiled = True
                except Exception as e:
                    logger.info(e)
                    compiled = False
                    break
        if compiled:
            batch_size = int(batch_size)
            nested_list = [config[i:i + batch_size] for i in range(0, len(config), batch_size)]

            for i, kwargs_list in enumerate(nested_list):
                # kwargs = dict(kwargs)
                if self.stop_pending_event.is_set():
                    logger.info(f'Stopping execution during {run_name}: {i + 1}/{len(config)}')
                    break
                logger.info(f'Executing {i + 1} of {len(nested_list)} with kwargs = {kwargs_list}')
                progress = ((i + 1) * 100 / len(nested_list)) - 0.1
                self._emit_progress(socketio, progress)
                # fname = f"{run_name}_script"
                # function = self.globals_dict[fname]

                phase = WorkflowPhase(
                    run_id=run_id,
                    name="main",
                    repeat_index=i,
                    parameters=kwargs_list,
                    start_time=datetime.now()
                )
                db.session.add(phase)
                db.session.flush()

                phase_id = phase.id
                output = await self.exec_steps(script, "script", phase_id, kwargs_list=kwargs_list, )
                # print(output)
                if output:
                    # kwargs.update(output)
                    for output_dict in output:
                        output_list.append(output_dict)
                    phase.outputs = output
                phase.end_time = datetime.now()
                db.session.commit()
        return output_list

    async def _run_repeat_section(self, repeat_count, arg_types, bo_args, output_list, script, run_name, return_list, compiled,
                            logger, socketio, history, output_path, run_id, optimizer=None, batch_mode=None,
                            batch_size=None, objectives=None):
        if bo_args:
            logger.info('Initializing optimizer...')
            if compiled:
                ax_client = bo_campaign.ax_init_opc(bo_args)
            else:
                if history:
                    file_path = os.path.join(output_path, history)
                    previous_runs = pd.read_csv(file_path).to_dict(orient='records')
                    ax_client = bo_campaign.ax_init_form(bo_args, arg_types, len(previous_runs))
                    for row in previous_runs:
                        parameter = {key: value for key, value in row.items() if key in arg_types.keys()}
                        raw_data = {key: value for key, value in row.items() if key in return_list}
                        _, trial_index = ax_client.attach_trial(parameter)
                        ax_client.complete_trial(trial_index=trial_index, raw_data=raw_data)
                        output_list.append(row)
                else:
                    ax_client = bo_campaign.ax_init_form(bo_args, arg_types)
        elif optimizer and history:
            file_path = os.path.join(output_path, history)

            previous_runs = pd.read_csv(file_path)

            expected_cols = list(arg_types.keys()) + list(return_list)

            actual_cols = previous_runs.columns.tolist()

            # NOT okay if it misses columns
            if set(expected_cols) - set(actual_cols):
                logger.warning(f"Missing columns from history .csv file. Expecting {expected_cols} but got {actual_cols}")
                raise ValueError("Missing columns from history .csv file.")

            # okay if there is extra columns
            if set(actual_cols) - set(expected_cols):
                logger.warning(f"Extra columns from history .csv file. Expecting {expected_cols} but got {actual_cols}")

            optimizer.append_existing_data(previous_runs)

            for row in previous_runs.to_dict(orient='records'):
                output_list.append(row)



        for i_progress in range(int(repeat_count)):
            if self.stop_pending_event.is_set():
                logger.info(f'Stopping execution during {run_name}: {i_progress + 1}/{int(repeat_count)}')
                break

            phase = WorkflowPhase(
                run_id=run_id,
                name="main",
                repeat_index=i_progress,
                start_time=datetime.now()
            )
            db.session.add(phase)
            db.session.flush()
            phase_id = phase.id

            logger.info(f'Executing {run_name} experiment: {i_progress + 1}/{int(repeat_count)}')
            progress = (i_progress + 1) * 100 / int(repeat_count) - 0.1
            self._emit_progress(socketio, progress)
            if bo_args:
                try:
                    parameters, trial_index = ax_client.get_next_trial()
                    logger.info(f'Params value: {parameters}')
                    # fname = f"{run_name}_script"
                    # function = self.globals_dict[fname]
                    phase.parameters = parameters
                    if not type(parameters) is list:
                        parameters = [parameters]
                    output = await self.exec_steps(script, "script", phase_id, parameters)

                    _output = {key: value for key, value in output.items() if key in return_list}
                    ax_client.complete_trial(trial_index=trial_index, raw_data=_output)
                    output.update(parameters)
                except Exception as e:
                    logger.info(f'Optimization error: {e}')
                    break
            # Optimizer for UI
            elif optimizer:
                try:
                    parameters = optimizer.suggest(n=batch_size)
                    logger.info(f'Parameters: {parameters}')
                    phase.parameters = parameters

                    output = await self.exec_steps(script, "script",  phase_id, kwargs_list=parameters)
                    if output:
                        optimizer.observe(output)
                        
                    else:
                        logger.info('No output from script')


                except Exception as e:
                    logger.info(f'Optimization error: {e}')
                    break
            else:
                # fname = f"{run_name}_script"
                # function = self.globals_dict[fname]
                output = await self.exec_steps(script, "script", phase_id, batch_size=batch_size)
            if output:
                # print("output: ", output)
                output_list.extend(output)
                logger.info(f'Output value: {output}')
                phase.outputs = output
            phase.end_time = datetime.now()
            db.session.commit()
            
            early_stop = self._check_early_stop(output, objectives)
            if early_stop:
                logger.info('Early stopping')
                break
                
        if bo_args:
            ax_client.save_to_json_file(os.path.join(output_path, f"{run_name}_ax_client.json"))
            logger.info(
                f'Optimization complete. Results saved to {os.path.join(output_path, f"{run_name}_ax_client.json")}'
            )
        return output_list

    @staticmethod
    def _save_results(run_name, arg_type, return_list, output_list, logger, output_path):
        output_columns = list(arg_type.keys()) + list(return_list)

        filename = run_name + "_" + datetime.now().strftime("%Y-%m-%d %H-%M") + ".csv"
        file_path = os.path.join(output_path, filename)
        df = pd.DataFrame(output_list)
        df = df.loc[:, [c for c in output_columns if c in df.columns]]

        df. to_csv(file_path, index=False)
        logger.info(f'Results saved to {file_path}')
        return filename

    @staticmethod
    def _emit_progress(socketio, progress):
        socketio.emit('progress', {'progress': progress})

    def safe_sleep(self, duration: float):
        interval = 1  # check every 1 second
        end_time = time.time() + duration
        while time.time() < end_time:
            if self.stop_current_event.is_set():
                return  # Exit early if stop is requested
            time.sleep(min(interval, end_time - time.time()))

    def get_status(self):
        """Returns current status of the script runner."""
        with self.current_app.app_context():
            return {
                "is_running": self.lock.locked(),
                "paused": self.paused,
                "stop_pending": self.stop_pending_event.is_set(),
                "stop_current": self.stop_current_event.is_set(),
            }


    async def _execute_steps_batched(self, steps: List[Dict], contexts: List[Dict[str, Any]], phase_id, step_index, section_name):
        """
        Execute a list of steps for multiple samples, batching where appropriate.
        """
        for step in steps:
            action = step["action"]

            if action == "if":
                await self._execute_if_batched(step, contexts, phase_id, step_index, section_name)
            elif action == "repeat":
                await self._execute_repeat_batched(step, contexts, phase_id, step_index, section_name)
            elif action == "while":
                await self._execute_while_batched(step, contexts, phase_id, step_index, section_name)
            else:
                # Regular action - check if batch
                if step.get("batch_action", False):
                    # Execute once for all samples
                    await self._execute_action_once(step, contexts[0], phase_id=phase_id, step_index=step_index, section_name=section_name)
                else:
                    # Execute for each sample
                    for context in contexts:
                        await self._execute_action(step, context, phase_id=phase_id, step_index=step_index, section_name=section_name)


    async def _execute_if_batched(self, step: Dict, contexts: List[Dict[str, Any]], phase_id, step_index, section_name):
        """Execute if/else block for multiple samples."""
        # Evaluate condition for each sample
        for context in contexts:
            condition = self._evaluate_condition(step["args"]["statement"], context)

            if condition:
                await self._execute_steps_batched(step["if_block"], [context], phase_id=phase_id, step_index=step_index, section_name=section_name)
            else:
                await self._execute_steps_batched(step["else_block"], [context], phase_id=phase_id, step_index=step_index, section_name=section_name)


    async def _execute_repeat_batched(self, step: Dict, contexts: List[Dict[str, Any]], phase_id, step_index, section_name):
        """Execute repeat block for multiple samples."""
        times = step["args"].get("statement", 1)

        for i in range(times):
            # Add repeat index to all contexts
            # for context in contexts:
            #     context["repeat_index"] = i

            await self._execute_steps_batched(step["repeat_block"], contexts, phase_id=phase_id, step_index=step_index, section_name=section_name)


    async def _execute_while_batched(self, step: Dict, contexts: List[Dict[str, Any]], phase_id, step_index, section_name):
        """Execute while block for multiple samples."""
        max_iterations = step["args"].get("max_iterations", 1000)
        active_contexts = contexts.copy()
        iteration = 0

        while iteration < max_iterations and active_contexts:
            # Filter contexts that still meet the condition
            still_active = []

            for context in active_contexts:
                condition = self._evaluate_condition(step["args"]["statement"], context)

                if condition:
                    context["while_index"] = iteration
                    still_active.append(context)

            if not still_active:
                break

            # Execute for contexts that are still active
            await self._execute_steps_batched(step["while_block"], still_active, phase_id=phase_id, step_index=step_index, section_name=section_name)
            active_contexts = still_active
            iteration += 1

        if iteration >= max_iterations:
            raise RuntimeError(f"While loop exceeded max iterations ({max_iterations})")

    async def _execute_action(self, step: Dict, context: Dict[str, Any], phase_id=1, step_index=1, section_name=None):
        """Execute a single action with parameter substitution."""
        # Substitute parameters in args
        substituted_args = self._substitute_params(step["args"], context)

        # Get the component and method
        instrument = step.get("instrument", "")
        action = step["action"]
        if instrument and "." in instrument:
            instrument_type, instrument = instrument.split(".")
        else:
            instrument_type = ""
        # Execute the action
        step_db = WorkflowStep(
            phase_id=phase_id,
            step_index=step_index,
            method_name=action,
            start_time=datetime.now(),
        )
        db.session.add(step_db)
        db.session.flush()
        try:
            self.socketio.emit('execution', {'section': f"{section_name}-{step_index}"})
            if action == "wait":
                duration = float(substituted_args["statement"])
                self.safe_sleep(duration)

            elif action == "pause":
                msg = substituted_args.get("statement", "")
                pause(msg)

            elif instrument_type == "deck" and hasattr(deck, instrument):
                component = getattr(deck, instrument)
                if hasattr(component, action):
                    method = getattr(component, action)

                    # Execute and handle return value
                    if step.get("coroutine", False):
                        result = await method(**substituted_args)
                    else:
                        result = method(**substituted_args)

                    # Store return value if specified
                    return_var = step.get("return", "")
                    if return_var:
                        context[return_var] = result

            elif instrument_type == "blocks" and instrument in BUILDING_BLOCKS.keys():
                # Inject all block categories
                method_collection = BUILDING_BLOCKS[instrument]
                if action in method_collection.keys():
                    method = method_collection[action]["func"]

                    # Execute and handle return value
                    # print(step.get("coroutine", False))
                    if step.get("coroutine", False):
                        result = await method(**substituted_args)
                    else:
                        result = method(**substituted_args)

                    # Store return value if specified
                    return_var = step.get("return", "")
                    if return_var:
                        context[return_var] = result
        except HumanInterventionRequired as e:
            self.logger.warning(f"Human intervention required: {e}")
            self.socketio.emit('human_intervention', {'message': str(e)})
            # Instead of auto-resume, explicitly stay paused until user action
            # step.run_error = False
            self.toggle_pause()

        except Exception as e:
            self.logger.error(f"Error during script execution: {e}")
            self.socketio.emit('error', {'message': str(e)})

            step_db.run_error = True
            self.toggle_pause()
        finally:
            step_db.end_time = datetime.now()
            step_db.output = context
            db.session.commit()

            self.pause_event.wait()

        return context

    async def _execute_action_once(self, step: Dict, context: Dict[str, Any], phase_id, step_index, section_name):
        """Execute a batch action once (not per sample)."""
        # print(f"Executing batch action: {step['action']}")
        return await self._execute_action(step, context, phase_id=phase_id, step_index=step_index, section_name=section_name)

    @staticmethod
    def _substitute_params(args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Substitute parameter placeholders like #param_1 with actual values."""
        substituted = {}

        for key, value in args.items():
            if isinstance(value, str) and value.startswith("#"):
                param_name = value[1:]  # Remove '#'
                substituted[key] = context.get(param_name, value)
            else:
                substituted[key] = value

        return substituted

    @staticmethod
    def _evaluate_condition(condition_str: str, context: Dict[str, Any]) -> bool:
        """
        Safely evaluate a condition string with context variables.
        """
        # Create evaluation context with all variables
        eval_context = {}

        # Substitute variables in the condition string
        substituted = condition_str
        for key, value in context.items():
            # Replace #variable with actual variable name for eval
            substituted = substituted.replace(f"#{key}", key)
            # Add variable to eval context
            eval_context[key] = value

        try:
            # Safe evaluation with variables in scope
            result = eval(substituted, {"__builtins__": {}}, eval_context)
            return bool(result)
        except Exception as e:
            raise ValueError(f"Error evaluating condition '{condition_str}': {e}")

    def _check_early_stop(self, output, objectives):
        for row in output:
            all_met = True
            for obj in objectives:
                name = obj['name']
                minimize = obj.get('minimize', True)
                threshold = obj.get('early_stop', None)

                if threshold is None:
                    all_met = False
                    break# Skip if no early stop defined

                value = row[name]
                if minimize and value > threshold:
                    all_met = False
                    break
                elif not minimize and value < threshold:
                    all_met = False
                    break

            if all_met:
                return True  # At least one row meets all early stop thresholds

        return False  # No row met all thresholds

    async def _execute_variable_batched(self, step: Dict, contexts: List[Dict[str, Any]], phase_id, step_index,
                                        section_name):
        """Execute variable assignment for multiple samples."""
        var_name = step["action"]  # "vial" in your example
        var_value = step["args"]["statement"]
        arg_type = step["arg_types"]["statement"]

        for context in contexts:
            # Substitute any variable references in the value
            if isinstance(var_value, str):
                substituted_value = var_value

                # Replace all variable references (with or without #) with their values
                for key, val in context.items():
                    # Handle both #variable and variable (without #)
                    substituted_value = substituted_value.replace(f"#{key}", str(val))
                    # For expressions like "vial+10", replace variable name directly
                    # Use word boundaries to avoid partial matches
                    import re
                    substituted_value = re.sub(r'\b' + re.escape(key) + r'\b', str(val), substituted_value)

                # Handle based on type
                if arg_type == "float":
                    try:
                        # Evaluate as expression (e.g., "10.0+10" becomes 20.0)
                        result = eval(substituted_value, {"__builtins__": {}}, {})
                        context[var_name] = float(result)
                    except:
                        # If eval fails, try direct conversion
                        context[var_name] = float(substituted_value)

                elif arg_type == "int":
                    try:
                        result = eval(substituted_value, {"__builtins__": {}}, {})
                        context[var_name] = int(result)
                    except:
                        context[var_name] = int(substituted_value)

                elif arg_type == "bool":
                    try:
                        # Evaluate boolean expressions
                        result = eval(substituted_value, {"__builtins__": {}}, {})
                        context[var_name] = bool(result)
                    except:
                        context[var_name] = substituted_value.lower() in ['true', '1', 'yes']

                else:  # "str"
                    # For strings, check if it looks like an expression
                    if any(char in substituted_value for char in ['+', '-', '*', '/', '>', '<', '=', '(', ')']):
                        try:
                            # Try to evaluate as expression
                            result = eval(substituted_value, {"__builtins__": {}}, {})
                            context[var_name] = result
                        except:
                            # If eval fails, store as string
                            context[var_name] = substituted_value
                    else:
                        context[var_name] = substituted_value
            else:
                # Direct numeric or boolean value
                context[var_name] = var_value

