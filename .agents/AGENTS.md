# IvoryOS Agent Rules

This file contains rules and guidelines for AI agents working in this repository.
It applies to **any AI coding agent** (Gemini, Claude, Copilot, Cursor, etc.) — not just one vendor.
The AI system will automatically read this file to customize its behaviour for this codebase.

---

## Project Overview

IvoryOS is a **self-driving laboratory (SDL) operating system** built on Flask + Flask-SocketIO.
It provides a browser-based UI for:
- **Direct instrument control** — call methods on Python instrument objects from a web form
- **Workflow design** — drag-and-drop canvas to build multi-step experiment scripts
- **Automated execution** — run scripts in repeat / config-sweep / Bayesian-optimisation modes
- **Data management** — live CSV streaming and SQLite/PostgreSQL persistence of every run

The primary public API is `ivoryos.server.run(module=__name__, ...)`, where `module` exposes the user's lab deck as Python objects.

---

## Repo Layout (key paths)

```
ivoryos/
  app.py                  # Flask app factory (create_app). Blueprints registered here.
  server.py               # Public entry-point: run(), load_plugins(), import_templates_from_dir()
  config.py               # Config classes: DevelopmentConfig, ProductionConfig, TestingConfig, DemoConfig
  socket_handlers.py      # Module-level socketio + runner singletons; all Socket.IO @on() handlers

  models/
    workflow.py           # WorkflowRun > WorkflowPhase > WorkflowStep (3-level DB hierarchy)
    user.py               # User model (Flask-Login)
    execution.py          # SingleStep model (for direct control)

  runtime/
    state.py              # GlobalState singleton (deck, lock, defined_variables, runner_status…)
    runner_runtime.py     # global_state instance, HumanInterventionRequired, ensure_deck(), pause()
    script_runner.py      # ScriptRunner (composes all three mixins below)
    script_runner_queue.py    # ScriptRunnerQueueMixin – pause/resume/stop/queue management
    script_runner_workflow.py # ScriptRunnerWorkflowMixin – run phases, CSV save, emit progress
    script_runner_steps.py    # ScriptRunnerStepMixin  – execute individual steps/batches
    task_runner.py            # TaskRunner – single direct-control step (non-workflow)
    control_flow.py           # validate_and_nest_control_flow() for if/repeat/while blocks

  routes/
    auth/     design/     execute/     control/     data/     library/     main/
    # Each is a Flask Blueprint; registered in app.py with url_prefix

  parsers/
    introspection.py      # generate_interface_schema() – reflects Python classes → JSON schema
    py_to_json.py         # Script → JSON step representation
    type_conversions.py   # CSV config type coercion
    bo_campaign.py        # BO optimizer campaign helpers
    returns.py            # store_return_value() – writes step return values into context dict
    serialize.py          # sanitize_for_json() – makes any object JSON-serialisable

  script/
    models.py             # Script SQLAlchemy model + Script dataclass
    editor.py             # ScriptEditor  – read/mutate script config
    renderer.py           # ScriptRenderer – compile script dict → executable Python string

  services/
    client_proxy.py       # ProxyGenerator – generates Python proxy classes for remote decks
    llm_agent.py          # LlmAgent – wraps OpenAI-compatible API for design agent
    draft_service.py      # DraftService – manages unsaved script drafts
    connection_history.py # Tracks recent instrument connections

  optimizer/
    base_optimizer.py     # OptimizerBase ABC – suggest(), observe(), append_existing_data()
    ax_optimizer.py       # Ax adapter
    baybe_optimizer.py    # BayBE adapter
    nimo_optimizer.py     # NIMO adapter
    registry.py           # OPTIMIZER_REGISTRY dict

  utils/
    decorators.py         # @block(category=…) decorator + BUILDING_BLOCKS registry dict
    logger.py             # start_logger() – attaches SocketIO handler to a named Python logger

  static/    templates/   forms/
```

---

## Architecture Rules

### 1. Flask App Factory
- The app is created in `create_app()` in `ivoryos/app.py`.
- Blueprints are registered at the **module level** (lines 27–33), *before* `create_app()` is defined.
- Every blueprint uses `url_prefix` from the env var `URL_PREFIX` (default `/ivoryos`). Always reference this prefix when building URLs or registering new blueprints.
- To add a plugin Blueprint call `ivoryos.server.run(..., blueprint_plugins=[my_blueprint])`. Do **not** hardcode it into `app.py`.

### 2. Global Singletons (never re-create)
| Singleton | Location | Purpose |
|---|---|---|
| `global_state` | `ivoryos.runtime.runner_runtime` | Process-wide registry (deck, lock, etc.) |
| `socketio` | `ivoryos.socket_handlers` | Single Flask-SocketIO instance |
| `runner` | `ivoryos.socket_handlers` | Single ScriptRunner instance |

- **Never** instantiate `GlobalState()` in route or service code — use the already-imported `global_state`.
- The deck object is stored in `global_state.deck` and must only be set once (`deck.setter` raises `RuntimeError` if already set).
- Access the deck safely via `ensure_deck()` from `ivoryos.runtime.runner_runtime` — it raises a clear error if no deck is configured.

### 3. Database (3-level Workflow Hierarchy)
```
WorkflowRun  (one per execution button press)
  └─ WorkflowPhase  (one per section: "prep" / "main" × N iterations / "cleanup")
       └─ WorkflowStep  (one per action/instrument call within a phase)
```
- Always `db.session.flush()` then save the `id`, then `db.session.commit()` before starting long work — this releases the SQLite lock.
- Use `db.session.get(Model, pk)` (not `Model.query.get`) — preferred SQLAlchemy 2.x style.
- The `output` column on `WorkflowStep` stores the **entire context dict** (all variables at that point), not just the return value of the step. Keep this in mind for the CSV download route (`data.download_workflow_steps_data_csv`).

### 4. Script Runner Concurrency Pattern
- `ScriptRunner` runs inside a **background thread** (via `threading.Thread`), but each individual `_execute_action` is `async` and runs under `asyncio.run(...)`.
- `threading.Lock` (`global_state.runner_lock`) gates the runner; check `self.lock.locked()` before starting a new run.
- Blocking instrument calls must be offloaded with `await asyncio.to_thread(method, **args)`.
- Native coroutine instrument calls use `await method(**args)` directly (flagged by `step["coroutine"] == True`).
- **pause/resume** is implemented with `threading.Event` (`pause_event`). Steps call `self.pause_event.wait()` at safe checkpoints.
- **stop** uses two separate events: `stop_pending_event` (finish current iteration, stop before next) and `stop_current_event` (abort mid-step immediately).

### 5. Error Handling in Runners
Every `_execute_action` loop **must** follow this pattern:
```python
try:
    # ... run the action ...
except HumanInterventionRequired as e:
    self.socketio.emit('human_intervention', {'message': str(e)})
    self.toggle_pause()
except Exception as e:
    self.logger.error(...)
    self.socketio.emit('error', {'message': str(e)})
    # Update step.run_error = True
    self.toggle_pause()
finally:
    # Always: set end_time, commit, call pause_event.wait()
    step_db.end_time = datetime.now()
    db.session.commit()
    self.pause_event.wait()
```
Do **not** swallow exceptions silently. Always emit to the UI and mark the DB step.

### 6. CSV / Results Streaming
- Results are streamed row-by-row during a run, not written at the end.
- First iteration: `_save_results()` → writes the full DataFrame (creates the file with header).
- Subsequent iterations: `_save_results_last_row()` → appends only the last row.
- Scripts that set `script.python_script` skip CSV output (raw Python mode).

### 7. SocketIO Events
Key events emitted by the server:
| Event | Payload | Meaning |
|---|---|---|
| `progress` | `{progress, iteration?, total?}` | Workflow progress 0–100 |
| `execution` | `{section}` | Highlights the current step in the UI |
| `log` | `{message}` | Appended to the UI log panel |
| `error` | `{message}` | Shows an error dialog, pauses execution |
| `human_intervention` | `{message}` | Shows a prompt to the user |
| `pause_status` | `{paused}` | Syncs the pause button state |
| `busy` | `{is_busy}` | Enables/disables the Run button |
| `request_input` | `{prompt, type}` | Requests typed input from the user |
| `error_resolved` | — | Clears the error state after retry |
| `server_boot_id` | `{boot_id}` | Lets the UI detect a server restart |

Key events received from the client:
`abort_pending`, `abort_current`, `pause`, `retry`, `submit_input`

### 8. Instrument Introspection
- `generate_interface_schema(deck, ...)` in `ivoryos/parsers/introspection.py` reflects the deck object and builds the JSON schema used by the UI.
- Only **public** methods (not starting with `_`) and not `UPPERCASE` are included.
- Methods with unsupported parameter types (`BinaryIO`, `TextIO`, etc.) are filtered out automatically.
- Properties with a setter are exposed as `method_name_(setter)` in the step schema.

### 9. Building Blocks (`@block` decorator)
- Functions decorated with `@block(category="my_category")` are auto-registered in `BUILDING_BLOCKS` dict.
- They appear alongside instrument methods in the workflow canvas.
- Async building blocks set `coroutine=True` automatically via `inspect.iscoroutinefunction`.
- Building blocks are resolved in `_execute_action` via `BUILDING_BLOCKS[instrument][action]["func"]`.

### 10. Optimizer Pattern
- All optimizers extend `OptimizerBase` (ABC) and implement `suggest(n)`, `observe(results)`, `append_existing_data()`, `get_plots()`.
- Register custom optimizers in `OPTIMIZER_REGISTRY` dict or pass via `run(..., optimizer_registry={...})`.
- `suggest()` returns a list of dicts, one per sample in the batch.
- `observe()` receives the list of output dicts from `exec_steps()`.

### 11. Plugin Blueprints
- Custom pages can be injected via `run(..., blueprint_plugins=[my_blueprint])`.
- Plugins are registered with `url_prefix=f"{url_prefix}/{blueprint.name}"`.
- If a plugin has a `init_socketio(socketio)` method, it is called automatically.
- Plugin `plugin_type` attribute (default `"tab"`) controls where it appears in the nav.

### 12. Context Dict (Workflow Variable Scope)
- Each sample/iteration maintains a `context: Dict[str, Any]` dict that acts as the variable scope.
- Variable steps (`instrument == "variable"`) write to `context[var_name]`.
- Parameter substitution uses `#var_name` syntax — resolved by `_substitute_params()`.
- Return values from instrument calls are stored via `store_return_value(context, arg_contexts, return_var, result)`.

---

## Code Standards

- Match the existing style and format in Python files.
- Python 3.9+ compatible syntax only (no `match/case`, no `|` union syntax in type hints).
- Maintain existing docstrings and typing annotations when refactoring.
- Ensure async code uses the `asyncio.to_thread` / `await` patterns shown in `script_runner_steps.py`.
- Preserve explicit `try...finally` blocks in runner code — they guarantee DB records and CSV output remain consistent even on crash.
- Use `sanitize_for_json()` before storing any Python object to a `JSONType` DB column.
- Do **not** call `time.sleep()` inside async steps — use `self.safe_sleep()` which respects the stop event.

---

## Web Application Development

- **Aesthetics**: Avoid basic placeholders. Use sleek, modern design for UI modifications.
- **Styling**: Responsive and dynamic interfaces using Vanilla CSS (no Tailwind unless user requests it).
- Templates live inside each blueprint's own `templates/` subfolder and extend `base.html`.
- Static JS/CSS lives in `ivoryos/static/js` and `ivoryos/static/css`.
- Always pass `ivoryos_version` to templates that display it, or inherit it from `base.html` context.

---

## Documentation Screenshots

The user docs (`docs/source/users/`) use annotated screenshots in
`docs/source/_static/screenshots/`. They are **generated**, not taken by hand, by
`docs/screenshots/capture_screenshots.py`, which starts the abstract SDL example, drives the
UI with Playwright, and draws numbered markers on the controls each docs page describes.
There is no CI check for this: keeping the pictures current is part of making a UI change.

- After changing anything under `ivoryos/templates/` or `ivoryos/static/` that alters what a
  user sees (layout, labels, buttons, panels, dialogs), regenerate the screenshots and commit
  the updated PNGs together with the UI change:

  ```console
  pip install -e ".[doc]" playwright pillow
  playwright install chromium
  python docs/screenshots/capture_screenshots.py
  python docs/screenshots/capture_screenshots.py --only design-overview,execute-config
  ```

- Every PNG changes on each run (fonts and anti-aliasing differ between machines), so a
  full `git diff` of the folder is expected; commit all of them, not a hand-picked subset.
- If a control the script targets was renamed, moved or removed, the script fails with
  `marker N target is not visible`. Fix the selector in the script, then update the
  numbered list under that image in the matching docs page so markers and text agree.
- Each shot's `name` is the PNG file name and is referenced from one docs page. Adding a
  marker means adding a list item under that image too.
- The Bayesian Optimization screenshot needs an optimizer extra installed
  (`pip install -e ".[optimizer-ax]"`) and is skipped otherwise; that is fine for unrelated
  UI changes.
- Do not hand-edit or re-crop the PNGs. If the picture is wrong, change the script and re-run.

---

## Releases: the "what's new" video

Every release that is a minor or major release (`x.y.0`) or has a `**[New]**` CHANGELOG entry gets
a short video recorded by `docs/release_videos/record.py` from a scene script,
`docs/release_videos/scenes/v<major>_<minor>_<patch>.py`. A patch release of fixes and small
improvements does not. Whenever you bump `ivoryos/version.py`, write a CHANGELOG section for a
release, or are asked to prepare, tag or publish a release, do this **before the tag**:

1. `python docs/release_videos/record.py --check` (works without the video extras). Exit 1 means the
   scene script is missing. Nothing in CI checks this, so this step is the only reminder.
2. Follow `.agents/skills/release_video/SKILL.md`: write the scene script from the CHANGELOG section
   on the dye-mixing demo lab (`docs/release_videos/dye_lab.py`), with a spoken `say=` line for each
   caption and slide, record it, review the frames and Whisper's check of the narration, and
   re-record until every caption and line matches what is on screen.
3. Commit the scene script with the version bump. The MP4 (`docs/release_videos/output/`, 1080p,
   narrated by a local Kokoro voice), its `.srt` subtitles, its YouTube cover (`-cover.jpg`) and its
   YouTube title and description (`-youtube.txt`) are made locally and not committed. Tell the user
   where all four are.

If a release that needs a video has nothing visible to show, the scene script holds only
`SKIP = "<the reason>"`; say so to the user rather than deciding it silently.

Tutorial videos, walkthroughs not tied to a release, are recorded the same way from
`docs/release_videos/tutorials/<name>.py` with `record.py --tutorial <name>`. When a UI change makes
one of them show something that is no longer there, tell the user it needs re-recording.

Videos are internal release work. Their notes are in `docs/release_videos/README.md`; do not add them
to the published docs in `docs/source/`.

---

## Dependencies

- Core requirements are in `requirements.txt` and `pyproject.toml` (source of truth for extras).
- Optional groups: `[dev]`, `[llm]`, `[db]`, `[optimizer-ax]`, `[optimizer-baybe]`, `[optimizer-nimo]`, `[optimizers]`, `[video]` (release videos).
- Keep `requirements.txt` and `pyproject.toml` in sync when adding new core dependencies.
- Do not add heavy optional dependencies (e.g. `torch`, `ax-platform`) to the core `requirements.txt`.

---

## Testing

- Tests live in `tests/unit/` and `tests/integration/`.
- `tests/conftest.py` provides fixtures: `app`, `client`, `db_session`.
- The test config uses `sqlite:///:memory:` and disables CSRF (`WTF_CSRF_ENABLED = False`).
- Run with `pytest tests/`.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `URL_PREFIX` | `/ivoryos` | Base path prefix for all routes |
| `SECRET_KEY` | `default_secret_key` | Flask session key (override in prod) |
| `OPENAI_API_KEY` | `None` | Enables the in-app LLM design agent |
| `IVORYOS_DB_URI` / `DATABASE_URL` | — | Override SQLite with PostgreSQL URI |
| `PORT` | `8000` | Server port |
| `IVORYOS_ACTIVE` | — | Set automatically to prevent double-launch |

---

## Common Gotchas

1. **Stale deck reference**: Always use `ensure_deck()` — never cache `global_state.deck` in a module-level variable, as it may be `None` at import time.
2. **SQLite lock contention**: Always `flush()` + save the `id` + `commit()` *before* starting long async work in a runner step. Long DB transactions block other threads.
3. **`output` column semantics**: `WorkflowStep.output` stores the entire context dict, not just the return value. The CSV download route depends on this.
4. **`_save_results` vs `_save_results_last_row`**: Use `_save_results` only for the *first* iteration (`i == 0`); use `_save_results_last_row` for all subsequent iterations to avoid rewriting the whole file.
5. **`asyncio.run()` inside a thread**: The runner calls `asyncio.run(...)` from a background thread — this is intentional and correct. Do not try to share the event loop across threads.
6. **Blueprint URL registration order matters**: The `design` and `execute` blueprints share `url_prefix=url_prefix` (no sub-path). Be careful about route conflicts when adding routes to either.
7. **`script.python_script` mode**: When a script has a raw Python string in `python_script`, the step-level runner is bypassed. CSV output and DB snapshotting do **not** apply in this mode.
8. **Demo mode**: `DemoConfig` creates a `SessionDemoUser` per browser session instead of requiring real login. Check `app.config.get("DEMO_MODE", False)` before modifying auth logic.

