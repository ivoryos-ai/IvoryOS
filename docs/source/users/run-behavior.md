# Run behavior

This page explains what happens when a workflow is executed from the IvoryOS UI.

## Workflow phases

Every workflow has three phases:

1. **Prep** runs once before the main experiment.
2. **Script** runs the main workflow actions. This phase may repeat by repeat count, parameter rows, batches, or optimizer iterations.
3. **Cleanup** runs once after the script phase, unless the run is stopped in a way that skips cleanup.

Use prep for setup that should happen once, such as homing a robot, priming a line, or checking an initial condition. Use cleanup for shutdown steps such as turning off heaters, closing valves, or returning a device to a safe state.

## Repeat, parameter, and optimizer runs

The available run setup depends on the workflow:

| Workflow shape | Run setup |
| --- | --- |
| No configurable parameters | Repeat count |
| Configurable parameters | Parameter table or CSV |
| Configurable parameters and numerical outputs | Optimizer setup |

The script phase is the part that repeats. Prep and cleanup stay once-per-run.

## Progress

The progress bar moves between steps, through every phase. Prep and cleanup each count as
their number of steps, and the script phase counts as its steps times the number of
iterations. The step running now counts, out of every step plus one, so the bar shows
progress from the first step and only fills when the run ends. The label beside it says where the run is: `Prep`, `Iteration: 3/12`, or
`Clean up`, while the workflow beside it marks the step running. When the run ends, the
label says how: finished, stopped, or ended with an error.

For a parameter table, the total follows the table. Adding or removing rows while it runs
moves the bar. From the moment the run starts, prep included, the button above the
progress bar shows a pencil. It opens the table, so a row can be fixed or changed before
the run reaches it. There, and in a queued task's editor, an Enum or Literal input
is a dropdown of its values, as in the parameter table, and an optional one also offers None. Each row shows its status as it starts and finishes, and rows that
finished are locked and show the values they ran with. Rows that cannot run as entered
are reported as soon as the run starts. The batch counter beside the label only shows
during the script phase.

Reloading the page, or losing the connection for a while, loses nothing. The page is sent
where the run is as soon as it connects, and an open table catches up on what it missed.

## Saved outputs

Workflow actions can save return values for later steps. When an action returns a fixed-length tuple, each tuple item can be saved under its own name.

Saved outputs are recorded with the workflow run and can be reviewed from the data pages.

## Pause and resume

Pause is cooperative. If a device call is already running, IvoryOS waits for that action to finish before pausing.

Use **Resume** to continue the paused workflow. The execution queue is also paused while the current run is paused.

## Human intervention and errors

A workflow can pause for human intervention, or IvoryOS can pause after an execution error.
A `pause` step shows its message and waits for someone to resume the run; an `input` step
asks for a value and waits for the answer.

When a step raises an error, including a value refused by a
[safety limit](instruments.md#safety-limits), the run pauses and asks what to do:

```{image} ../_static/screenshots/execute-error.png
:alt: The Error Detected dialog during a run, with Rerun Current Step, Continue and Stop Execution
:width: 1440px
```

1. Choose what happens next:
   - **Rerun Current Step** tries the failed step again, for example after fixing a jammed
     vial or reconnecting a cable.
   - **Continue** carries on with the next step, leaving the failed one as it is.
   - **Stop Execution** stops the run, skips cleanup, and pauses the queue.
2. The status shows **Error** on every page. If you close the dialog, click it to bring the
   dialog back.

A common cause is a workflow that no longer matches the deck, because the deck was edited after the workflow was saved. The execution page warns about those steps before you start a run. See [Workflow step warnings](deck-compatibility.md) for what each warning means.

## Stop pending

Use **Stop pending** (the hourglass) when the current iteration should finish but future iterations should be skipped.

## Stop current

Use **Stop current** (the stop button) when the current workflow should stop as soon as IvoryOS reaches a cooperative stop check.

This does not force-kill a Python function or hardware call that is already running. IvoryOS waits for the active action to return, then skips the remaining workflow steps.

## Cleanup and the queue after a stop

Both stop buttons ask how the run should wind down:

```{image} ../_static/screenshots/execute-stop.png
:alt: The Stop Workflow dialog with its two checkboxes
:width: 548px
```

1. **Proceed to cleanup steps**: tick it to run the **Clean up** phase before stopping, for
   example to turn off a heater. Left unticked, cleanup is skipped.
2. **Continue execution queue**: tick it to let the next queued run start once this one has
   stopped. Left unticked, the queue pauses (see below).

Both start unticked: **Stop current** clears them each time its dialog opens, and **Stop pending**
keeps your last choice until the page is reloaded.

## Execution queue

Only one workflow task runs at a time. Additional submitted runs wait in the execution queue.

The **Continue execution queue** option controls what happens after a stopped workflow winds down:

| Option | Behavior |
| --- | --- |
| Checked | The next queued task can start. |
| Unchecked | The queue stays paused until resumed. |

Normal task completion does not pause the queue. If queued tasks exist and the queue is not paused, the next task starts automatically.
