
from ivoryos.parsers.serialize import sanitize_for_json
import inspect

import inspect
import asyncio
import ast
import threading
from concurrent.futures import Future
from datetime import datetime

from ivoryos.utils.decorators import BUILDING_BLOCKS
from ivoryos.models import db, SingleStep
from ivoryos.runtime.safety import guard
from ivoryos.parsers.structured_types import (
    is_dict_annotation, is_list_annotation, is_scalar_annotation, is_set_annotation, is_tuple_annotation, to_dict,
    to_list, to_scalar, to_set, to_tuple,
)
from ivoryos.utils.enums import (
    NOT_AN_OPTION, enum_class_of, find_member, find_option, literal_options_of, setter_annotation,
)
from ivoryos.runtime.state import GlobalState

global_state = GlobalState()

INTERRUPTED = "Interrupted: the server stopped before this step finished"


def mark_interrupted_steps():
    """
    Mark the steps a previous server left running. It went down mid-call, losing the instrument
    connection, so they will never finish; the error tells a page or client still waiting on one
    to stop. Their end time stays empty: when they stopped is not known, and a made-up one would
    give them a false duration. Call with an app context, before the server takes calls.

    :return: how many steps were marked
    """
    count = SingleStep.query.filter(SingleStep.end_time.is_(None), SingleStep.run_error.is_(None)).update(
        {"run_error": INTERRUPTED})
    db.session.commit()
    return count


class TaskRunner:
    def __init__(self, globals_dict=None, on_busy_change=None, on_step_finished=None):
        self.retry = False
        if globals_dict is None:
            globals_dict = globals()
        self.globals_dict = globals_dict
        self.lock = global_state.runner_lock
        # called when a step takes or lets go of the runner lock, so open pages
        # can update their status pill without a reload
        self.on_busy_change = on_busy_change
        # called with (step_id, result) once a step ends, so a page or client
        # waiting on a background step hears about it without polling
        self.on_step_finished = on_step_finished

    def _busy_changed(self):
        if self.on_busy_change:
            self.on_busy_change()

    def _release(self):
        self.lock.release()
        self._busy_changed()

    async def run_single_step(self, component, method, kwargs, wait=True, current_app=None, override_busy=False):
        # Try to acquire lock without blocking
        acquired = False
        if not override_busy:
            if not self.lock.acquire(blocking=False):
                # a copy: the busy reply must not change what the running step reports
                current_status = dict(global_state.runner_status or {})
                current_status.update(success=False, status="busy", output="busy")
                return current_status
            acquired = True
            self._busy_changed()

        if wait:
            output = await self._run_single_step(component, method, kwargs, current_app, override_busy=override_busy, acquired=acquired)
        else:
            # the request's event loop closes once the reply is sent and would cancel a step
            # left on it, letting go of the lock mid-call; the step gets a thread of its own
            started = Future()
            threading.Thread(
                target=self._run_in_background,
                args=(started, component, method, kwargs, current_app, override_busy, acquired),
                daemon=True,
            ).start()
            step_id = await asyncio.wrap_future(started)
            if isinstance(step_id, dict):
                return step_id  # it failed before it could start
            output = {"status": "task started", "task_id": step_id}

        return output

    def _run_in_background(self, started, component, method, kwargs, current_app, override_busy, acquired):
        try:
            asyncio.run(self._run_single_step(component, method, kwargs, current_app,
                                              override_busy=override_busy, acquired=acquired, started=started))
        except Exception as e:
            # don't leave the request waiting on a step that never started
            if not started.done():
                started.set_exception(e)
            raise

    def _get_executable(self, component, deck, method):
        if component.startswith("deck."):
            component = component.split(".")[1]
            if deck is None:
                deck = global_state.require_deck()
            instrument = getattr(deck, component)
        elif component.startswith("blocks."):
            component = component.split(".")[1]
            return BUILDING_BLOCKS[component][method]["func"]
        else:
            temp_connections = global_state.defined_variables
            instrument = temp_connections.get(component)
        
        # Check for property setter convention: "<prop>_(setter)"
        if method.endswith("_(setter)"):
            prop_name = method[:-9] # remove "_(setter)"
            # Check trait on class to avoid triggering property
            if hasattr(type(instrument), prop_name):
                 attr = getattr(type(instrument), prop_name)
                 if isinstance(attr, property) and attr.fset:
                     def setter(**kwargs):
                         if len(kwargs) == 1:
                             val = next(iter(kwargs.values()))
                             setattr(instrument, prop_name, val)
                             return None
                         elif "value" in kwargs:
                             setattr(instrument, prop_name, kwargs["value"])
                             return None
                         raise ValueError(f"Setter for {prop_name} expects 1 argument")
                     
                     # Copy signature from fset but remove self
                     try:
                         sig = inspect.signature(attr.fset)
                         params = [p.replace(annotation=setter_annotation(attr))
                                   for n, p in sig.parameters.items() if n != 'self']
                         setter.__signature__ = sig.replace(parameters=params)
                     except Exception:
                         # Fallback if signature extraction fails
                         pass
                     
                     return setter
        
        # Check for property getter
        if hasattr(type(instrument), method):
            attr = getattr(type(instrument), method)
            if isinstance(attr, property):
                def getter(**kwargs):
                    return getattr(instrument, method)
                return getter

        function_executable = getattr(instrument, method)
        return function_executable

    async def _run_single_step(self, component, method, kwargs, current_app=None, override_busy=False, acquired=False,
                               started=None):
        # `started` (background steps only) gets the step's id once it is recorded
        def report_start(value):
            if started is not None and not started.done():
                started.set_result(value)

        try:
            function_executable = self._get_executable(component, global_state.deck, method)
            method_name = f"{component}.{method}"
        except Exception as e:
            if acquired:
                self._release()
            output = {"status": "error", "msg": str(e)}
            report_start(output)
            return output

        # Flask context is NOT async → just use normal "with"
        with current_app.app_context():
            step = SingleStep(
                method_name=method_name,
                kwargs=sanitize_for_json(kwargs),
                run_error=None,
                start_time=datetime.now()
            )
            db.session.add(step)
            # committed now, not when it ends, so the step can be looked up while it runs
            db.session.commit()
            step_id = step.id
            report_start(step_id)

            if not override_busy:
                global_state.runner_status = {"id": step_id, "type": "task"}
            if acquired:
                # tell open pages which step is running, so one on its instrument shows it
                global_state.running_step = {"id": step_id, "component": component, "method": method}
                self._busy_changed()

            try:
                kwargs = self._convert_kwargs_type(kwargs, function_executable)
                # the lab's limits apply to a call from the Instruments page too
                guard.enforce(component, method, kwargs)

                if inspect.iscoroutinefunction(function_executable):
                    output = await function_executable(**kwargs)
                else:
                    output = await asyncio.to_thread(function_executable, **kwargs)
                output = sanitize_for_json(output)
                step.output = output
                success = True
            except Exception as e:
                step.run_error = str(e)
                success = False
                output = str(e)
            finally:
                step.end_time = datetime.now()
                db.session.commit()
                if acquired:
                    global_state.running_step = None
                    self._release()

            result = dict(success=success, output=output)
            if self.on_step_finished:
                self.on_step_finished(step_id, result)
            return result

    @staticmethod
    def _convert_kwargs_type(kwargs, function_executable):
        def convert_guess(str_value):
            if not isinstance(str_value, str):
                return str_value
                
            str_value = str_value.strip()
            
            # Try python evaluation first (handles ints, floats, lists, dicts, sets, tuples, booleans, None)
            try:
                return ast.literal_eval(str_value)
            except (ValueError, SyntaxError):
                pass
            
            # Fallback for unquoted strings lists: "a, b, c" -> ["a", "b", "c"]
            # We only split if it clearly looks like a list (has comma) and literal_eval failed
            if "," in str_value:
                 # Check if it might be a malformed structure vs just comma separated strings
                 # For safety, if literal_eval failed, we treat it as comma separated strings.
                 return [convert_guess(i) for i in str_value.split(",")]

            return str_value

        sig = inspect.signature(function_executable)
        converted = {}

        for name, value in kwargs.items():
            if name in sig.parameters:
                param = sig.parameters[name]
                enum_class = enum_class_of(param.annotation)
                options = literal_options_of(param.annotation)
                if enum_class is not None:
                    # a key or a value, from the form or JSON: the driver gets the member
                    member = find_member(enum_class, value)
                    if member is None and value is not None:
                        raise ValueError(f"{value!r} is not one of {list(enum_class.__members__)}")
                    converted[name] = member
                elif options is not None:
                    # the option as text from the form, or as it is from JSON: the driver gets the option
                    option = find_option(options, value)
                    if option is NOT_AN_OPTION and value is not None:
                        raise ValueError(f"{value!r} is not one of {list(options)}")
                    converted[name] = None if option is NOT_AN_OPTION else option
                elif is_tuple_annotation(param.annotation):
                    converted[name] = to_tuple(value, param.annotation)
                elif is_dict_annotation(param.annotation):
                    converted[name] = to_dict(value, param.annotation)
                elif is_list_annotation(param.annotation):
                    converted[name] = to_list(value, param.annotation)
                elif is_set_annotation(param.annotation):
                    converted[name] = to_set(value, param.annotation)
                elif is_scalar_annotation(param.annotation):
                    # never guessed from the text: `a, b` is not a list to a str, and 2.5 is not an int
                    converted[name] = to_scalar(value, param.annotation)
                # Check for explicit typing
                elif param.annotation != inspect.Parameter.empty:
                    # If explicitly typed, we still want to try smart conversion if the value is a string
                    
                    if isinstance(value, str):
                       val = convert_guess(value)

                       # Try to cast to target type if possible (fails for typing generics)
                       try:
                           converted[name] = param.annotation(val)
                       except Exception:
                           # Casting failed (common for typing generics), just use the guessed/casts val
                           converted[name] = val
                    else:
                        try:
                            converted[name] = param.annotation(value)
                        except Exception:
                            converted[name] = value
                else:
                    # no type hint → guess
                    converted[name] = convert_guess(value)
            else:
                 pass
                 
        return converted
