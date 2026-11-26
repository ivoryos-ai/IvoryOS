# Runtime walkthrough

This page follows the main path from a platform script to a completed workflow run.

## Startup path

```mermaid
flowchart TD
    script["User platform script"] --> run["ivoryos.run(#95;#95;name#95;#95;)"]
    run --> app["create_app(...)"]
    app --> register["register Flask routes, SocketIO, database, auth"]
    register --> inspect["inspect active Python module"]
    inspect --> store["store deck and interface schema in global_state"]
    store --> serve["start SocketIO Flask server"]
```

`ivoryos.run(...)` lives in `ivoryos/server.py`. It creates the Flask app, imports workflow templates, loads plugins, registers loggers and notification handlers, configures optimizers, and starts the server.

When `module` is provided, IvoryOS starts from the active Python module:

- `global_state.deck` stores the active Python module.
- `generate_interface_schema(...)` inspects the deck and writes a pseudo-deck schema.
- `generate_block_schema(...)` registers built-in flow-control blocks.
- `create_module_interface_schema(...)` builds the API variable view.

## Interface generation

```mermaid
flowchart TD
    method["Python function or method"] --> signature["inspect.Signature"]
    signature --> details["argument types, defaults, docstring, return annotation"]
    details --> fields["dynamic WTForms fields"]
    fields --> forms["direct-control form and workflow action form"]
```

Key files:

- `ivoryos/parsers/introspection.py`
- `ivoryos/forms/dynamic_forms.py`
- `ivoryos/parsers/type_conversions.py`
- `ivoryos/parsers/returns.py`

Return annotations matter. Scalar returns show one save field. Fixed-length tuple returns show one save field per tuple item.

## Workflow design path

```mermaid
flowchart TD
    ui["Design UI"] --> routes["design routes"]
    routes --> model["Script model + ScriptEditor"]
    model --> json["workflow JSON in database"]
    json --> python["generated workflow Python script"]
```

Key files:

- `ivoryos/routes/design/`
- `ivoryos/script/models.py`
- `ivoryos/script/editor.py`
- `ivoryos/script/renderer.py`

Workflows are stored as structured data with three phases: `prep`, `script`, and `cleanup`.

## Execution path

```mermaid
flowchart TD
    ui["Execute UI"] --> routes["execute routes"]
    routes --> queue["ScriptRunner queue"]
    queue --> prep["prep phase"]
    prep --> main["script phase repeated by run mode"]
    main --> cleanup["cleanup phase"]
    cleanup --> records["WorkflowRun, WorkflowPhase, WorkflowStep records"]
```

Key files:

- `ivoryos/routes/execute/`
- `ivoryos/runtime/script_runner.py`
- `ivoryos/runtime/script_runner_queue.py`
- `ivoryos/runtime/script_runner_workflow.py`
- `ivoryos/runtime/script_runner_steps.py`
- `ivoryos/parsers/returns.py`

Only one workflow task runs at a time through the shared runner lock. Queue behavior, pause/resume, stop pending, stop current, and cleanup behavior are user-facing runtime behavior; see [Run behavior](../users/run-behavior.md).

## Direct-control path

```mermaid
flowchart TD
    caller["Devices UI or generated proxy"] --> post["POST /ivoryos/instruments/#lt;instrument#gt;"]
    post --> resolve["control route resolves object and method"]
    resolve --> convert["argument conversion"]
    convert --> invoke["method call on live deck object"]
    invoke --> record["SingleStep record and JSON response"]
```

Key files:

- `ivoryos/routes/control/`
- `ivoryos/services/client_proxy.py`
- `ivoryos/models/execution.py`

Direct-control calls are logged as `SingleStep` records. Remote proxy clients use the same route contract.
