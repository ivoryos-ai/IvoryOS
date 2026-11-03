---
name: script_runner_pattern
description: Guidelines for implementing, debugging, or extending script runners and workflow execution in IvoryOS
---

# IvoryOS Script Runner Pattern

Read this skill whenever you are modifying workflow execution logic, adding a new step type,
debugging runner behaviour, or implementing concurrency changes.

---

## 1. Architecture Overview

`ScriptRunner` is assembled from three mixins — each responsible for a distinct layer:

```
ScriptRunner
 ├─ ScriptRunnerQueueMixin    (script_runner_queue.py)
 │    pause / resume / stop / queue management
 ├─ ScriptRunnerWorkflowMixin (script_runner_workflow.py)
 │    phase orchestration, CSV streaming, progress emission
 └─ ScriptRunnerStepMixin     (script_runner_steps.py)
      individual step execution, parameter substitution, control flow
```

There is exactly **one** `ScriptRunner` instance for the entire process, held in
`ivoryos/socket_handlers.py`:

```python
runner = ScriptRunner()
runner.socketio = socketio
```

Never create another `ScriptRunner` instance; import and use the module-level `runner`.

---

## 2. Threading / Async Model

```
Flask request thread
  └─ threading.Thread  ← _run_with_stop_check() runs here
       └─ asyncio.run(...)  ← each phase section gets its own event loop
            └─ await _execute_steps_batched(...)
                 └─ await _execute_action(...)
                      ├─ await asyncio.to_thread(blocking_method, **args)  ← blocking instruments
                      └─ await async_method(**args)                         ← native coroutines
```

**Key rules:**
- `asyncio.run()` is called from a background thread — this is correct and intentional.
- Do **not** share an event loop across threads.
- Blocking instrument calls: `await asyncio.to_thread(method, **kwargs)`.
- Native `async` instrument methods: detected by `step["coroutine"] == True`, called with `await method(**kwargs)`.
- Detecting coroutines: `inspect.iscoroutinefunction(method)` is used at schema-build time in `introspection.py`.

---

## 3. The 3-Level Database Hierarchy

```
WorkflowRun       — created once per button press
  WorkflowPhase   — created per section ("prep", "main" × N, "cleanup")
    WorkflowStep  — created per instrument action
```

**Critical DB pattern** — always flush before long work to release the SQLite lock:

```python
step_db = WorkflowStep(phase_id=phase_id, step_index=step_index,
                       method_name=action, start_time=datetime.now())
db.session.add(step_db)
db.session.flush()
step_id = step_db.id   # ← save before commit resets it
db.session.commit()    # ← commit early, releases SQLite lock

try:
    result = await asyncio.to_thread(method, **args)
except Exception as e:
    step_db = db.session.get(WorkflowStep, step_id)  # re-fetch after commit
    step_db.run_error = True
    db.session.commit()
    ...
finally:
    step_db = db.session.get(WorkflowStep, step_id)
    step_db.end_time = datetime.now()
    step_db.output = sanitize_for_json(context)
    db.session.commit()
```

> **Note**: `WorkflowStep.output` stores the **entire context dict** (all variables at that
> point in the run), not just the method's return value. The CSV download route in
> `data.py` depends on this schema — do not change it without updating that route.

---

## 4. Mandatory Error-Handling Pattern

Every `_execute_action` loop **must** have this structure. Do not simplify it:

```python
while True:
    # 1. Create DB step record early
    step_db = WorkflowStep(...)
    db.session.add(step_db)
    db.session.flush()
    step_id = step_db.id
    db.session.commit()

    try:
        # 2. Run the action
        result = await asyncio.to_thread(method, **args)

    except HumanInterventionRequired as e:
        # 3a. Pause and wait for user to resolve
        self.socketio.emit('human_intervention', {'message': str(e)})
        self.toggle_pause()

    except Exception as e:
        # 3b. Log, emit error to UI, pause
        self.logger.error(f"Error: {e}", exc_info=True)
        self.socketio.emit('error', {'message': str(e)})
        step_db = db.session.get(WorkflowStep, step_id)
        step_db.run_error = True
        db.session.commit()
        self.toggle_pause()

    finally:
        # 4. Always commit timing and output, then check for pause
        step_db = db.session.get(WorkflowStep, step_id)
        step_db.end_time = datetime.now()
        step_db.output = sanitize_for_json(context)
        db.session.commit()
        self.pause_event.wait()   # blocks if paused or after error

    # 5. Retry logic
    if self.retry:
        if step_db.run_error:
            self.retry = False
            continue   # ← retry the while loop
        self.socketio.emit('error_resolved')
        self.retry = False
    break
```

**Never** swallow exceptions silently. Always emit to the UI and update the DB record.

---

## 5. Pause / Resume / Stop Events

Three `threading.Event` objects control execution:

| Event | Set means | Used by |
|---|---|---|
| `pause_event` | Running (clear = paused) | `pause_event.wait()` at end of each step |
| `stop_pending_event` | Stop after current iteration | Checked at top of each iteration loop |
| `stop_current_event` | Stop immediately | Checked inside `_execute_steps_batched` |
| `stop_cleanup_event` | Skip cleanup section | Checked in `_run_actions` when `section_name == "cleanup"` |

```python
# Checking stop inside a loop
if self.stop_current_event.is_set():
    break

# Checking stop between iterations
if self.stop_pending_event.is_set():
    break
```

`safe_sleep(duration)` in `ScriptRunnerWorkflowMixin` polls `stop_current_event` every 1 second
and exits early if set — always use it instead of `time.sleep()`.

---

## 6. Progress and UI Emission

```python
# Emit a progress update (0–100)
self._emit_progress(progress, iteration=i+1, total=total)

# Highlight the current step in the canvas
self.socketio.emit('execution', {'section': f"{section_name}-{action_id-1}"})

# Log a message to the UI log panel
self.socketio.emit('log', {'message': "..."})

# Emit progress at 100% at the very end (always in `finally`)
self._emit_progress(100)
```

`_emit_progress` also caches the last known progress in `self.last_progress`,
`self.last_iteration`, and `self.last_total` so they can be re-emitted on
client reconnect (`handle_connect` in `socket_handlers.py`).

---

## 7. CSV Streaming Pattern

Results are written row-by-row — never all at once at the end:

```python
output_list = []

for i, kwargs_list in enumerate(nested_list):
    output = await self.exec_steps(script, "script", phase_id, kwargs_list=kwargs_list)
    output_list.extend(output)

    if not script.python_script and any(output_list):
        if i == 0:
            self._save_results(filename, arg_type, return_list, output_list, output_path)
        else:
            self._save_results_last_row(filename, arg_type, return_list, output_list, output_path)
```

- `_save_results()` — writes the full DataFrame with header (first iteration only).
- `_save_results_last_row()` — appends only the last row (`mode="a"`) for all subsequent iterations.
- Raw Python scripts (`script.python_script` is not None) skip CSV output entirely.

---

## 8. Context Dict and Parameter Substitution

Each sample carries a `context: Dict[str, Any]` that acts as its variable scope:

```python
# Variables set by "variable" steps
context["my_var"] = 42.0

# #param syntax in step args is replaced at runtime
step["args"] = {"volume": "#my_var"}
substituted = self._substitute_params(step["args"], context)
# → {"volume": 42.0}

# Return values stored back into context
store_return_value(context, arg_contexts, return_var="result", result=output)
# context["result"] = output
```

`_substitute_params` supports:
- `"#var_name"` → direct lookup in context
- `"prefix_#var_name_suffix"` → inline substitution via regex

Condition evaluation (`if`, `while`) uses `_evaluate_condition(condition_str, context)`, and
variable and math steps use `_execute_variable_batched`. Both read the expression with
`ivoryos.utils.expressions.evaluate` instead of `eval()`: plain expressions only (literals,
variables, arithmetic, comparisons, indexing, f-strings, a value's public methods), with
underscore names and attributes refused.

---

## 9. Batch Execution

Steps can run in **batch mode** (`step["batch_action"] == True`):

- `batch_action=True` → execute the step **once** for the first context, then propagate new
  context values to all other contexts.
- `consolidate_batch_args` → list of argument keys whose values should be aggregated from all
  contexts into a single list before calling the method once.
- `batch_action=False` (default) → execute the step once **per sample** in the batch.

---

## 10. Workflow Sections (prep / script / cleanup)

A script has three named sections:

| Section | Runs | Phase `name` |
|---|---|---|
| `prep` | Once at start | `"prep"` |
| `script` | N times (repeat / config / optimizer) | `"main"` |
| `cleanup` | Once at end (unless `stop_cleanup_event` set) | `"cleanup"` |

`_run_actions(script, section_name, run_id)` handles `prep` and `cleanup`.
`_run_config_section` or `_run_repeat_section` handle the `script` section.

---

## 11. Adding a New Control-Flow Step Type

To add a new control-flow type (e.g. `"for_each"`):

1. In `ivoryos/runtime/control_flow.py`: update `validate_and_nest_control_flow()` to recognise the new `instrument` key.
2. In `ivoryos/runtime/script_runner_steps.py`: add an `elif instrument == "for_each"` branch in `_execute_steps_batched` that calls a new `_execute_for_each_batched()` method.
3. In the frontend JS/canvas: add the new block type to the step palette.
4. Ensure the new method respects `self.stop_current_event.is_set()` and calls `self.pause_event.wait()`.

---

## 12. TaskRunner (Direct Control — not workflow)

For **single instrument calls** from the Control page (not a workflow run), use `TaskRunner`:

```python
# ivoryos/runtime/task_runner.py
runner = TaskRunner()
result = await runner.run_single_step(component="deck.my_instrument",
                                      method="my_method",
                                      kwargs={"param": 1},
                                      wait=True,
                                      current_app=current_app)
```

`TaskRunner` also uses `global_state.runner_lock` — it will return `{"status": "busy"}` if
the `ScriptRunner` is currently running a workflow.

---

## 13. Debugging Checklist

When a workflow step silently fails or produces wrong data:

- [ ] Is the DB step `run_error=True` but no error emitted? → Missing `except Exception` handler.
- [ ] Is `WorkflowStep.output` empty? → `sanitize_for_json(context)` may have failed; check for non-serialisable objects.
- [ ] Is the CSV not streaming? → Check `script.python_script` is None and `any(output_list)` is True.
- [ ] Is execution stuck? → The `pause_event` may be cleared; call `toggle_pause()` or check for unresumed error state.
- [ ] Is a variable not substituted? → Verify the context dict key matches the `#var_name` exactly (case-sensitive).
- [ ] Is `stop_current_event` set but loop still running? → Not all inner loops check `is_set()`; add the check.
