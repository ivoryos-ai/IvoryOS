# Data model

This page summarizes the main runtime data structures contributors usually touch.

## Runtime directories

IvoryOS creates `ivoryos_data/` in the current working directory.

```text
ivoryos_data/
|-- config_csv/
|-- llm_output/
|-- logs/
|-- pseudo_deck/
|-- results/
|-- scripts/
|   `-- drafts/
|-- default.log
`-- ivoryos.db
```

Unsaved workflow drafts live in `scripts/drafts/`, one JSON file per login session
(`draft_<user>_<draft_id>.json`), so the browser and a Python client logged in as the
same user edit separate drafts. The server caches them in memory and reads the files
back after a restart, so a design that was open in the designer is still there when the
server comes back, as long as the browser is still logged in. Logging out deletes that
session's draft; files left by sessions that never logged out are pruned oldest-first
once there are more than 256.

Beside each draft, `draft_<user>_<draft_id>.history.json` holds its undo history: up to
100 earlier states of the draft, each labelled with the change that led to it, and which
one the draft is at now (`ivoryos/services/draft_history.py`). Every save of a draft goes
through `post_script_file`, which records the change, so new designer routes get undo
without extra code. Pass `record=False` for a save the user did not make, such as filling
in the deck, and `label=` to name a change the comparison cannot describe. The history
covers one workflow: a route that puts another workflow in the designer (opening from the
library, importing, **New**) passes `new_history=True`, so undo stops there. The history is
deleted and pruned with its draft.

These directories are runtime output. Do not commit newly generated local run data.

## Database location

By default, IvoryOS uses SQLite:

```text
ivoryos_data/ivoryos.db
```

Set `IVORYOS_DB_URI` or `DATABASE_URL` to use another database. PostgreSQL support requires the `db` extra.

## Workflow definition model

Saved workflow definitions use the `Script` model in `ivoryos/script/models.py`.

Important fields:

| Field | Meaning |
| --- | --- |
| `name` | Workflow name and primary key. |
| `deck` | Platform/deck name associated with the workflow. |
| `script_dict` | Workflow actions grouped into `prep`, `script`, and `cleanup`. |
| `id_order` | UI ordering metadata for workflow actions. |
| `status` | Editing/finalized state. |
| `registered` | Whether a workflow should appear as a registered workflow action. |
| `return_values` | Declared output names. |
| `uuid` | Stable identifier for saved scripts. |

## Execution records

Workflow run records live in `ivoryos/models/workflow.py`.

```mermaid
flowchart LR
    run["WorkflowRun"] -->|has many| phase["WorkflowPhase"]
    phase -->|has many| step["WorkflowStep"]
```

`WorkflowRun` represents one submitted run. It stores the run name, platform, timing, data path, repeat mode, and related phases. `submitted_by` is the username of whoever submitted it, from the browser or a client, passed from the run routes through the queued task, so it is right however long the run waits in the queue. Runs from before it was kept have none. Existing databases get the column when the app starts, like the run's other newer columns (`reset_old_schema` in `ivoryos/app.py`).

`WorkflowPhase` represents one phase execution, such as `prep`, a repeated `script` iteration, or `cleanup`. It stores iteration parameters, outputs, timing, and related steps.

`WorkflowStep` represents one action call inside a phase. It stores method name, timing, error state, and output.

## Direct-control records

Direct-control calls use `SingleStep` in `ivoryos/models/execution.py`.

`SingleStep` stores:

- method name;
- submitted kwargs;
- start and end time;
- error text;
- output.

Generated proxy calls use the same direct-control route behavior and are recorded as single-step calls.

## Interface schemas

When IvoryOS starts with `ivoryos.run(__name__)`, it inspects the active module and writes a pseudo-deck schema under:

```text
ivoryos_data/pseudo_deck/
```

The schema records exposed functions, methods, parameter types, docstrings, and generated UI metadata used by the browser session and workflow designer.

## Result files

Workflow outputs are written under:

```text
ivoryos_data/results/
```

Generated workflow scripts and workflow JSON files are written under:

```text
ivoryos_data/scripts/
```

Run configuration CSV files are written under:

```text
ivoryos_data/config_csv/
```
