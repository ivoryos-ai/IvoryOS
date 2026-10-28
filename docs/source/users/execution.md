# Execution

The **Execution** page sets up a run of the workflow you opened in the designer, starts it,
and follows it while it runs. The top half is the run setup; the bottom half is the monitor.
Drag the bar between them to give either more room.

## Choosing how to run

The tabs at the top offer the ways this workflow can run. Which ones are available depends on
the workflow:

| Workflow shape | Run option |
| --- | --- |
| No `#name` inputs | **Repeat** the workflow a number of times |
| `#name` inputs | **Configuration**: a table of values, one row per run of the workflow |
| `#name` inputs and a numeric saved value | **Bayesian Optimization**: an optimizer picks the values |

Every option also asks for:

- **Experiment name**, to find the run later on the **Data** page. It defaults to the
  workflow's name.
- **Batch size**, the number of samples handled together in each iteration. Steps marked
  **Run once per batch** in the designer run once per batch; every other step runs once per
  sample.

### Repeat

```{image} ../_static/screenshots/execute-repeat.png
:alt: The Repeat tab for a workflow with no inputs
:width: 1320px
```

1. **Repeat for**: how many times the **Experiment** phase runs.
2. **Run** starts it.

### Parameter table

```{image} ../_static/screenshots/execute-config.png
:alt: The Configuration tab with three rows of values for solubility_screen
:width: 1440px
```

1. **Run options.** Options this workflow cannot use are greyed out.
2. **File actions.** Download an empty CSV template, fill it in a spreadsheet, and upload it,
   or pick one you saved before.
3. **The table.** One column per `#name` input and one row per run of the workflow. Rows left
   empty are skipped. A [safety limit](instruments.md#safety-limits) is shown under its
   column's name, here `°C · 20 to 80` under `temp_c`.
4. **Experiment name.**
5. **Run** starts the run, or queues it if another run is in progress.

An input is optional when its argument is typed `Optional[...]` or `X | None`. When a
table has both kinds, the required columns are marked with a red asterisk. In a filled row:

- An empty optional cell runs as `None`.
- To give `None` on purpose, type `None` in a text cell, or pick **None** at the end of an
  optional dropdown. It shows in italics. It also counts as filling the row, so a table
  whose only input is optional runs one row for each `None` you enter.
- An empty required cell is marked, and the table does not run until it is filled. A
  required dropdown offers only its choices; a required text cell still accepts `None`.

### Bayesian Optimization

The optimizer suggests the input values, runs the workflow, reads the saved values you chose
as objectives, and suggests the next values from what it learned. It is offered when the
workflow has `#name` inputs and saves at least one numeric value, and an optimizer package
(Ax, BayBE or NIMO) is installed.

```{image} ../_static/screenshots/execute-optimizer.png
:alt: The Bayesian Optimization tab set up for solubility_screen
:width: 1440px
```

1. **Optimizer.** Only installed optimizers are listed.
2. **Input parameters.** For each `#name` input: a range to search, a set of choices, or a
   fixed value.
3. **Objective.** Maximize or minimize each saved value, with an optional threshold that ends
   the run early.
4. **Run Optimization** starts it.

On the left, **Data Source** gives the optimizer earlier results to learn from (optional), and
**Run Settings** sets how many suggestions to try per iteration and when to stop. The
**Optimizer Plot** tab in the monitor shows what the optimizer has learned as the run goes.

## Watching a run

Once a run starts, the monitor shows where it is. Drag the bar up to see more of it.

```{image} ../_static/screenshots/execute-running.png
:alt: The monitor during a run, with the current step highlighted and the log streaming
:width: 1440px
```

1. **The step running now**, highlighted in the workflow.
2. **Where the run is**: `Prep`, `Iteration: 2/3`, or `Clean up`, then how the run ended.
3. **Run controls**, left to right: edit the run's table (see
   [Changing a table while it runs](#changing-a-table-while-it-runs)), **Pause**/**Resume**,
   **Stop**, and **Stop pending** (finish this iteration, then stop).
4. **Log** of every step and its values. The **Queue** and **Optimizer Plot** tabs sit beside it.
5. **Status**, on every page: **Idle**, **Running**, **Paused**, **Error** or **Input**. When
   it says **Error** or **Input**, click it to bring back the dialog waiting for you.

What pausing, stopping, and errors do is described in [Run behavior](run-behavior.md).

### Changing a table while it runs

The pencil opens the running table. Rows that have not started yet can still be changed.

```{image} ../_static/screenshots/execute-edit-running.png
:alt: The Current Run dialog, listing each row of the table with its status
:width: 848px
```

1. Each row's status: **done**, **running** or **pending**. Finished rows are locked.
2. A pending row can still be changed, or removed with the **×** at its end.
3. **Add entry** appends a row. **Save** applies the changes.

An `Enum` or `Literal` input is a dropdown here, as in the table. Rows that cannot run as
entered are reported as soon as the run starts.

## Queueing runs

Only one run happens at a time. Pressing **Run** while another run is in progress asks for a
name and adds the new run to the queue:

```{image} ../_static/screenshots/execute-queue-name.png
:alt: The System Busy dialog asking for a name for the queued run
:width: 620px
```

1. A name for the queued run, to tell it apart in the queue and on the **Data** page.
2. **Add to Queue.**

The **Queue** tab in the monitor lists the runs waiting their turn:

```{image} ../_static/screenshots/execute-queue.png
:alt: The Queue tab with one waiting run
:width: 684px
```

1. The queued run: its name, how many rows it has, and who submitted it.
2. **Edit** it before it starts, move it up or down, or remove it.

The next run starts by itself when the current one finishes, unless the queue was paused
(see [Run behavior](run-behavior.md#execution-queue)).
