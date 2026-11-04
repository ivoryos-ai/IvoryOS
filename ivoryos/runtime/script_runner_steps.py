import re
import asyncio
import inspect
from datetime import datetime
from typing import Any, Dict, List

from ivoryos.runtime.control_flow import validate_and_nest_control_flow
from ivoryos.runtime.run_events import ERROR, INTERVENTION
from ivoryos.runtime.safety import SafetyViolation, guard
from ivoryos.utils.enums import setter_annotation, to_members
from ivoryos.runtime.runner_runtime import HumanInterventionRequired, ensure_deck, global_state, pause
from ivoryos.models import WorkflowStep, db
from ivoryos.parsers.structured_types import substitute_variables, to_containers
from ivoryos.parsers.returns import store_return_value
from ivoryos.parsers.serialize import sanitize_for_json
from ivoryos.utils.decorators import BUILDING_BLOCKS
from ivoryos.utils.expressions import evaluate


class ScriptRunnerStepMixin:
    # the editable config table of the running task, if it has one
    live_config = None
    # how many shared steps are running nested steps right now; see _apply_live_row_edits
    _shared_step_depth = 0
    # whether a stop has cut off steps that would otherwise have run
    steps_cut_off = False

    def _halted(self):
        """Whether a stop was requested. Every place that skips steps because of
        it asks here, so that a stop arriving during the last step, which skips
        nothing, is not mistaken for one that cut the work short."""
        if self.stop_current_event.is_set():
            self.steps_cut_off = True
            return True
        return False

    def _apply_live_row_edits(self):
        """Hand edits made to the running config rows to the steps still to come.

        Only between steps, and never inside a shared step's nested steps: a shared
        step copies whatever changed in the first sample to the whole batch when it
        ends, which would spread an edit made to one row across all of them.
        """
        if self.live_config is None or self._shared_step_depth:
            return
        for line in self.live_config.apply_running_edits():
            if self.logger:
                self.logger.info(line)

    async def _execute_steps_batched(self, steps: List[Dict], contexts: List[Dict[str, Any]], phase_id, section_name, arg_contexts:List[Dict[str, Any]] = None):
        """
        Execute a list of steps for multiple samples, batching where appropriate.
        """
        for step in steps:
            if self._halted():
                break
            self._apply_live_row_edits()
            if step.get("disabled", False):
                if self.logger:
                    self.logger.info(f"Skipping disabled step: {step.get('action')}")
                continue
            
            action = step["action"]
            instrument = step["instrument"]
            action_id = step["id"]
            
            # Emit execution status so the UI highlights the current step
            section_id = f"{section_name}-{action_id-1}"
            self.last_execution_section = section_id
            if self.socketio:
                self.socketio.emit('execution', {'section': section_id})
            # the phase's own steps move the bar; a called workflow's run under a section of their own
            progress = getattr(self, "progress", None)
            if progress is not None and progress.at_step(section_name, action_id):
                self._emit_progress()
            if instrument == "if" and action == "if":
                await self._execute_if_batched(step, contexts, phase_id=phase_id, step_index=action_id,
                                               section_name=section_name)
            elif instrument == "repeat" and action == "repeat":
                await self._execute_repeat_batched(step, contexts, phase_id=phase_id, step_index=action_id,
                                                   section_name=section_name)
            elif instrument == "while" and action == "while":
                await self._execute_while_batched(step, contexts, phase_id=phase_id, step_index=action_id,
                                                  section_name=section_name)
            elif instrument == "variable":
                await self._execute_variable_batched(step, contexts, phase_id=phase_id, step_index=action_id,
                                                     section_name=section_name)
                # print("Variable executed", "current context", contexts)
            elif instrument == "math_variable":
                await self._execute_variable_batched(step, contexts, phase_id=phase_id, step_index=action_id,
                                                     section_name=section_name)
            elif instrument == "input":
                await self._execute_variable_batched(step, contexts, phase_id=phase_id, step_index=action_id,
                                                     section_name=section_name)
            elif instrument == "workflows":
                # Recursively logic for nested workflows
                # print(step.get("workflow", []))
                workflow_steps = validate_and_nest_control_flow(step.get("workflow", []))
                if workflow_steps:
                    if self.socketio:
                        self.socketio.emit('log', {'message': f"Entering workflow: {action} with args: {step.get('args', {})}"})
                    
                    # Inject parameters into context
                    
                    # For batched contexts:
                    workflow_contexts = []
                    for context in contexts:
                        substituted_args =  self._substitute_params( step.get("args", {}), context)
                        # args = step.get("args", {})
                        # for key, value in args.items():
                        #      if isinstance(value, str) and value.startswith("#"):
                        #          context[key] = context.get(value[1:])
                        #      else:
                        #          context[key] = value
                        workflow_contexts.append(substituted_args)
                        # print("context", context)
                        # print("substituted_args", substituted_args)
                    if step.get("batch_action", False):
                        self._emit_batch_progress(contexts[0], shared=len(contexts) > 1)
                        before = dict(contexts[0])
                        self._shared_step_depth += 1
                        try:
                            await self._execute_steps_batched(workflow_steps, [contexts[0]], arg_contexts=[workflow_contexts[0]], phase_id=phase_id, section_name=f"{section_name}-{action_id-1}")
                        finally:
                            self._shared_step_depth -= 1
                        self._broadcast_shared_values(contexts, before)

                    else:
                        for context, workflow_context in zip(contexts, workflow_contexts):
                            # sequentially execute workflow steps
                            await self._execute_steps_batched(workflow_steps, [context], arg_contexts=[workflow_context], phase_id=phase_id,
                                                              section_name=f"{section_name}-{action_id - 1}")

            else:
                # Regular action - check if batch
                if step.get("batch_action", False):
                    # Execute once for all samples
                    self._emit_batch_progress(contexts[0], shared=len(contexts) > 1)

                    before = dict(contexts[0])
                    consolidate_keys = step.get("consolidate_batch_args", [])
                    if consolidate_keys:
                        # Normalize to list if boolean (backward compat)
                        if isinstance(consolidate_keys, bool):
                            consolidate_keys = [k for k, v in step.get("arg_types", {}).items() if v == "list"]
                        
                        # Aggregate arguments
                        aggregated_args = {}
                        
                        # Initialize based on first context substitution to get keys
                        first_args = self._substitute_params(step["args"], contexts[0])
                        
                        # Identify keys to consolidate
                        # Must be in consolidate_keys AND be a list type (user requirement)
                        target_keys = []
                        arg_types = step.get("arg_types", {})
                        for key in consolidate_keys:
                            if arg_types.get(key) == "list" or key in first_args: # weak check if arg_types invalid
                                target_keys.append(key)
                        
                        # Initialize aggregated args
                        for key, val in first_args.items():
                             if key in target_keys:
                                 aggregated_args[key] = []
                             else:
                                 aggregated_args[key] = val # For non-consolidated args, keep first value

                        # Iterate all contexts to collect lists
                        for ctx in contexts:
                            sub_args = self._substitute_params(step["args"], ctx)
                            for key in target_keys:
                                if key in sub_args:
                                    val = sub_args[key]
                                    if isinstance(val, (list, tuple)):
                                        aggregated_args[key].extend(val)
                                    else:
                                        aggregated_args[key].append(val)
                        
                        await self._execute_action_once(step, contexts[0], arg_contexts=arg_contexts, phase_id=phase_id, step_index=action_id,
                                                            section_name=section_name, override_args=aggregated_args)

                    else:
                        await self._execute_action_once(step, contexts[0], arg_contexts=arg_contexts, phase_id=phase_id, step_index=action_id,
                                                            section_name=section_name)

                    self._broadcast_shared_values(contexts, before)

                else:
                    # Execute for each sample
                    if arg_contexts:
                        for context, arg_context in zip(contexts, arg_contexts):
                            self._emit_batch_progress(context)
                            await self._execute_action(step, context, arg_contexts=arg_context, phase_id=phase_id, step_index=action_id,
                                                       section_name=section_name)
                    else:
                        for context in contexts:
                            self._emit_batch_progress(context)
                            await self._execute_action(step, context, phase_id=phase_id, step_index=action_id,
                                                       section_name=section_name)
                            self.pause_event.wait()



    async def _execute_if_batched(self, step: Dict, contexts: List[Dict[str, Any]], phase_id, step_index, section_name):
        """Execute if/else block for multiple samples.

        Samples are grouped by their condition result and each branch runs once for its
        group, so a shared step inside a branch runs once rather than once per sample.
        """
        if_contexts, else_contexts = [], []
        for context in contexts:
            condition = self._evaluate_condition(step["args"]["statement"], context)
            if self.logger:
                self.logger.info(f"Evaluating if {step['args']['statement']}: {condition}")
            (if_contexts if condition else else_contexts).append(context)
        if if_contexts:
            await self._execute_steps_batched(step["if_block"], if_contexts, phase_id=phase_id, section_name=section_name)
        if else_contexts:
            await self._execute_steps_batched(step["else_block"], else_contexts, phase_id=phase_id, section_name=section_name)


    async def _execute_repeat_batched(self, step: Dict, contexts: List[Dict[str, Any]], phase_id, step_index, section_name):
        """Execute repeat block for multiple samples.

        The whole batch advances through the iterations together, as if the body were
        written out N times: shared steps run once per iteration, per-sample steps once
        per sample. When the count comes from a variable that differs between samples,
        a sample sits out once its own count is reached and the rest carry on as a
        smaller batch.
        """
        times = step["args"].get("statement", 1)
        if times in (None, ""):
            # older drafts saved a blank repeat count as None
            times = 1
        if isinstance(times, str) and times.startswith("#"):
            counts = [int(context.get(times[1:])) for context in contexts]
        else:
            counts = [int(times)] * len(contexts)
        total = max(counts, default=0)
        self._warn_overwritten_returns(step["repeat_block"], total)

        for i in range(total):
            if self._halted():
                break
            active = [context for context, count in zip(contexts, counts) if i < count]
            await self._execute_steps_batched(step["repeat_block"], active, phase_id=phase_id, section_name=section_name)

    def _warn_overwritten_returns(self, steps: List[Dict], times: int):
        """Warn that return values saved inside a repeat only keep the last iteration."""
        if times < 2 or not self.logger:
            return
        names = []

        def collect(block):
            for inner in block:
                if inner.get("disabled", False):
                    continue
                saved = inner.get("return")
                names.extend(name for name in (saved if isinstance(saved, list) else [saved]) if name)
                for key in ("if_block", "else_block", "repeat_block", "while_block"):
                    collect(inner.get(key, []))

        collect(steps)
        if names:
            self.logger.warning(
                f"Repeat runs {times} times: return value(s) {', '.join(dict.fromkeys(names))} are overwritten "
                f"each iteration, only the value from the last iteration is saved."
            )

    def _emit_batch_progress(self, context: Dict[str, Any], shared=False):
        """Show the running sample's place in the current batch, or "-" for a shared step.

        Counted against the whole batch rather than the samples passed in, so a smaller
        leftover batch reads x/3 and a sample inside an if group or a narrowed repeat
        keeps its own number.
        """
        batch = self.current_batch
        if not batch or not self.socketio:
            return
        if shared:
            self.socketio.emit('batch_progress', {'batch_index': 1, 'batch_total': len(batch), 'shared': True})
            return
        index = next((i for i, item in enumerate(batch) if item is context), None)
        if index is not None:
            self.socketio.emit('batch_progress', {'batch_index': index + 1, 'batch_total': len(batch)})

    @staticmethod
    def _broadcast_shared_values(contexts: List[Dict[str, Any]], before: Dict[str, Any]):
        """Copy the values a shared step wrote into the first sample to the rest of the batch.

        Values are overwritten rather than only filled in when missing, so inside a repeat
        every sample gets the latest iteration's value instead of keeping the first one.
        """
        written = {key: value for key, value in contexts[0].items()
                   if key not in before or before[key] is not value}
        for context in contexts[1:]:
            context.update(written)


    async def _execute_while_batched(self, step: Dict, contexts: List[Dict[str, Any]], phase_id, step_index, section_name):
        """Execute while block for multiple samples."""
        max_iterations = step["args"].get("max_iterations", 1000)
        active_contexts = contexts.copy()
        iteration = 0

        while active_contexts and not self._halted():
            # Filter contexts that still meet the condition
            still_active = []

            for context in active_contexts:
                condition = self._evaluate_condition(step["args"]["statement"], context)
                if self.logger:
                    self.logger.info(f"Evaluating while {step['args']['statement']}: {condition}")
                if condition:
                    context["while_index"] = iteration
                    still_active.append(context)

            if not still_active:
                break

            # Execute for contexts that are still active
            await self._execute_steps_batched(step["while_block"], still_active, phase_id=phase_id, section_name=section_name)
            active_contexts = still_active
            iteration += 1

        # if iteration >= max_iterations:
        #     raise RuntimeError(f"While loop exceeded max iterations ({max_iterations})")

    async def _execute_action(self, step: Dict, context: Dict[str, Any], arg_contexts: Dict[str, Any]=None, phase_id=1, step_index=1, section_name=None, override_args=None):
        """Execute a single action with parameter substitution."""
        # Substitute parameters in args
        result = None
        if self._halted():
            return context
        
        def substitute():
            if override_args is not None:
                return override_args
            if arg_contexts:
                # If arg_contexts is a list, use the first element for substitution
                if isinstance(arg_contexts, list):
                    return self._substitute_params(step["args"], arg_contexts[0])
                return self._substitute_params(step["args"], arg_contexts)
            return self._substitute_params(step["args"], context)

        substituted_args = substitute()
        retrying = False

        # Get the component and method
        instrument = step.get("instrument", "")
        action = step["action"]
        if instrument and "." in instrument:
            instrument_type, instrument = instrument.split(".")
        else:
            instrument_type = ""
        current_deck = ensure_deck(required=instrument_type == "deck")
        # Execute the action
        while True:
            if retrying:
                # a value fixed in the running table since the step failed is used on retry
                self._apply_live_row_edits()
                substituted_args = substitute()
            step_db = WorkflowStep(
                phase_id=phase_id,
                step_index=step_index,
                method_name=action,
                start_time=datetime.now(),
            )
            db.session.add(step_db)
            db.session.flush()
            step_id = step_db.id # Save ID
            db.session.commit() # Commit early to release lock
            
            try:

                if self.logger:
                    self.logger.info(f"Executing '{instrument}.{action}' with args {substituted_args}")
                if instrument == "wait" and action == "wait":
                    duration = float(substituted_args["statement"])
                    self.safe_sleep(duration)

                elif instrument == "pause" and action == "pause":
                    msg = substituted_args.get("statement", "")
                    pause(msg)

                elif instrument == "comment" and action == "comment":
                    msg = substituted_args.get("statement", "")
                    if self.logger:
                        self.logger.info(f"Comment: {msg}")

                elif instrument_type == "deck" and hasattr(current_deck, instrument):
                    component = getattr(current_deck, instrument)
                    # the lab's limits hold whatever the value's source; see ivoryos.runtime.safety
                    guard.enforce(step["instrument"], step["action"], substituted_args)
                    if "_(setter)" in action:
                        action = action.replace("_(setter)", "")
                    if hasattr(component, action):
                        attr = getattr(component, action)

                        if callable(attr):
                            # a step stores an Enum argument's key and a tuple as a list; the driver gets
                            # the member and the tuple
                            call_args = to_containers(attr, to_members(attr, substituted_args))
                            # Execute and handle return value
                            if step.get("coroutine", False):
                                result = await attr(**call_args)
                            else:
                                result = await asyncio.to_thread(attr, **call_args)
                        else:
                            # Handle property setter/getter
                            if "value" in substituted_args:
                                setattr(component, action, self._setter_value(component, action, substituted_args["value"]))
                                result = substituted_args["value"]
                            else:
                                result = attr
                        # Store return value if specified
                        # return_var = step.get("return", "")
                        # if return_var:
                        #     context[return_var] = result
                    else:
                        # The module is still here but this method is not, so the
                        # deck was edited after the step was saved. Without this
                        # the step would fall off the end of the branch, record no
                        # error and be reported as a successful no-op.
                        raise AttributeError(
                            f"Method '{action}' no longer exists on '{instrument}'. "
                            f"The deck has changed since this step was saved."
                        )

                elif instrument_type == "blocks" and instrument in BUILDING_BLOCKS.keys():
                    # Inject all block categories
                    method_collection = BUILDING_BLOCKS[instrument]
                    if action in method_collection.keys():
                        method = method_collection[action]["func"]
                        call_args = to_containers(method, to_members(method, substituted_args))

                        # Execute and handle return value
                        # print(step.get("coroutine", False))
                        if step.get("coroutine", False):
                            result = await method(**call_args)
                        else:
                            result = await asyncio.to_thread(method, **call_args)

                        # # Store return value if specified
                        # return_var = step.get("return", "")
                        # if return_var:
                        #     context[return_var] = result
                else:
                    module = global_state.defined_variables.get(instrument, None)
                    if module is None:
                        raise ValueError(f"Unknown instrument '{instrument}'")
                    guard.enforce(instrument, action, substituted_args)
                    method = getattr(module, action)
                    call_args = to_containers(method, to_members(method, substituted_args))
                    if step.get("coroutine", False):
                        result = await method(**call_args)
                    else:
                        result = await asyncio.to_thread(method, **call_args)
                        # Store return value if specified
                return_var = step.get("return", "")
                if return_var and result is not None:
                    store_return_value(context, arg_contexts, return_var, result)

            except HumanInterventionRequired as e:
                self.logger.warning(f"Human intervention required: {e}")
                self.record_event(INTERVENTION, str(e))
                self.socketio.emit('human_intervention', {'message': str(e)})
                # Instead of auto-resume, explicitly stay paused until user action
                # step.run_error = False
                self.toggle_pause()

            except Exception as e:
                # a refusal by the limits is not a crash, so it gets no traceback
                self.logger.error(f"Error during script execution: {e}", exc_info=not isinstance(e, SafetyViolation))
                self.record_event(ERROR, f"{step.get('instrument')}.{step.get('action')}: {e}")
                self.socketio.emit('error', {'message': str(e)})
                
                # Update error status in a fresh transaction
                step_db = db.session.get(WorkflowStep, step_id)
                step_db.run_error = True
                db.session.commit()
                
                self.toggle_pause()
            finally:
                step_db = db.session.get(WorkflowStep, step_id)
                step_db.end_time = datetime.now()
                step_db.output = sanitize_for_json(context) # todo if change so output doesnt include all input values as well then need to update ivoryos.routes.data.data.download_workflow_steps_data_csv
                db.session.commit()

                self.pause_event.wait()
            
            if self.retry:
                # only retry if it errored out
                if step_db.run_error:
                    self.retry = False
                    retrying = True
                    continue
                if self.socketio:
                    self.socketio.emit('error_resolved')
                self.retry = False
            
            break

        return context

    async def _execute_action_once(self, step: Dict, context: Dict[str, Any], arg_contexts, phase_id, step_index, section_name, override_args=None):
        """Execute a batch action once (not per sample)."""
        # print(f"Executing batch action: {step['action']}")
        return await self._execute_action(step, context, arg_contexts=arg_contexts, phase_id=phase_id, step_index=step_index, section_name=section_name, override_args=override_args)

    @staticmethod
    def _setter_value(component, name, value):
        """A step's value for a property, as the driver gets it from a method: the member, option or tuple."""
        prop = getattr(type(component), name, None)
        if not isinstance(prop, property) or prop.fset is None:
            return value

        def setter(value):
            pass

        setter.__signature__ = inspect.Signature([inspect.Parameter(
            "value", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=setter_annotation(prop))])
        return to_containers(setter, to_members(setter, {"value": value}))["value"]

    @staticmethod
    def _substitute_params(args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Substitute parameter placeholders like #param_1 with actual values."""
        substituted = {}

        def substitute_vars(value: str, context: Dict[str, Any]) -> Any:
            # Replace placeholders of the form `#var` in a string with values from a context.
            # Known bug, left for now: any `#` followed by a word character is taken for a variable, so a
            # text argument like `sample #1` raises KeyError here and ends the run before the call.
            def replacer(match):
                var_name = match.group(1)
                if var_name not in context:
                    raise KeyError(f"Missing context value for '{var_name}'")
                return str(context[var_name])

            return re.sub(r"#(\w+)", replacer, value)

        for key, value in args.items():
            if isinstance(value, str) and value.startswith("#"):
                param_name = value[1:]  # Remove '#'
                substituted[key] = context.get(param_name)
            elif isinstance(value, str):
                # for comment need to substitue #args in the arg with the actual values
                substituted[key] = substitute_vars(value, context)
            else:
                # e.g. #variables nested inside a dict value
                substituted[key] = substitute_variables(value, context)

        return substituted

    @staticmethod
    def _evaluate_condition(condition_str: str, context: Dict[str, Any]) -> bool:
        """
        Safely evaluate a condition string with context variables.
        """
        # Create evaluation context with all variables
        eval_context = {}

        # Substitute variables in the condition string
        if isinstance(condition_str, str):
            substituted = condition_str
            for key, value in context.items():
                # Replace #variable with actual variable name for eval
                substituted = substituted.replace(f"#{key}", key)
                # Add variable to eval context
                eval_context[key] = value

            try:
                # Plain expressions only, with variables in scope (see ivoryos.utils.expressions)
                result = evaluate(substituted, eval_context)
                return bool(result)
            except Exception as e:
                raise ValueError(f"Error evaluating condition '{condition_str}': {e}")
        elif isinstance(condition_str, bool):
            return condition_str
        else:
            raise condition_str

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

    def prompt_user(self, prompt: str, var_type) -> str:
        result = None
        if self.socketio:
            self.waiting_for_input = True
            self.input_value = None
            self.socketio.emit('request_input', {
                'prompt': prompt,
                'type': var_type
            })
            if self.logger:
                self.logger.info(f"Requesting input: {prompt} ({var_type})")

            # Pause and wait for input
            self.pause_event.clear()
            self.pause_event.wait()

            # Process result
            result = self.input_value
            self.waiting_for_input = False

            # Log result
            if self.logger:
                self.logger.info(f"Input received: {result}")
        else:
            if self.logger:
                self.logger.warning("No socketio connection, skipping input")
        return result

    async def _execute_variable_batched(self, step: Dict, contexts: List[Dict[str, Any]], phase_id, step_index,
                                        section_name):
        """Execute variable assignment for multiple samples."""
        if self._halted():
            return
            
        var_name = step["action"]
        var_value = step["args"]["statement"]
        arg_type = step["arg_types"]["statement"]

        while True:
            try:
                for context in contexts:
                    if step["instrument"] == "input":
                        value = self.prompt_user(var_value, arg_type)
                        context[var_name] = value
                        continue

                    # Substitute any variable references in the value
                    if isinstance(var_value, str):
                        if self.logger:
                            self.logger.info(f'Executing variable {var_name} ({arg_type}): {var_value}')

                        substituted_value = var_value

                        # Replace all variable references (with or without #) with their values
                        for key, val in context.items():
                            # Handle both #variable and variable (without #)
                            substituted_value = substituted_value.replace(f"#{key}", str(val))
                            # For expressions like "vial+10", replace variable name directly
                            # Use word boundaries to avoid partial matches
                            import re
                            substituted_value = re.sub(r'\b' + re.escape(key) + r'\b', lambda _: str(val), substituted_value)
                        if self.logger:
                            self.logger.info(f'Substituted variable references for {var_name}: {substituted_value}')

                        # Handle based on type
                        if arg_type == "float":
                            try:
                                # Evaluate as expression (e.g., "10.0+10" becomes 20.0)
                                result = evaluate(substituted_value)
                                context[var_name] = float(result)
                            except:
                                # If evaluating fails, try direct conversion
                                context[var_name] = float(substituted_value)

                        elif arg_type == "int":
                            try:
                                result = evaluate(substituted_value)
                                context[var_name] = int(result)
                            except:
                                context[var_name] = int(substituted_value)

                        elif arg_type == "bool":
                            try:
                                # Evaluate boolean expressions
                                result = evaluate(substituted_value)
                                context[var_name] = bool(result)
                            except:
                                context[var_name] = substituted_value.lower() in ['true', '1', 'yes']

                        else:  # "str"
                            # For strings, check if it looks like an expression (including f-strings)
                            # todo add to the list '{', '}' if want those to show up in the string, but then fstring logic might not work? needs testing
                            if any(char in substituted_value for char in ['+', '-', '*', '/', '>', '<', '=', '(', ')']) \
                                    or substituted_value.startswith('f"') or substituted_value.startswith("f'") \
                                    or substituted_value.startswith('"') or substituted_value.startswith("'"):
                                try:
                                    # Try to evaluate as expression
                                    result = evaluate(substituted_value, context)
                                    context[var_name] = result
                                except:
                                    # If evaluating fails, store as string
                                    context[var_name] = substituted_value
                            else:
                                context[var_name] = substituted_value
                    else:
                        # Direct numeric or boolean value
                        context[var_name] = var_value

                # If everything succeeds, break the retry loop
                if self.logger:
                    self.logger.info(f'Evaluated variable {var_name} ({arg_type}) to: {context[var_name]}')
                break

            except Exception as e:
                self.logger.error(f"Error during variable execution: {e}", exc_info=True)
                self.record_event(ERROR, f"Variable {var_name}: {e}")
                if self.socketio:
                    self.socketio.emit('error', {'message': f"Variable error ({var_name}): {str(e)}"})

                self.toggle_pause()
                self.pause_event.wait()

                if self._halted():
                    break

                if self.retry:
                    self.retry = False
                    continue
                else:
                    if self.socketio:
                        self.socketio.emit('error_resolved')
                    break
