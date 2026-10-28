# Workflow designer

The **Workflow** page is where you put instrument actions in order and save them as a
reusable workflow. Nothing moves while you design: the designer only edits the workflow, and
a run starts from the **Execution** page.

The examples on this page build `solubility_screen` from the abstract SDL example: dose a
solid and a solvent, let the sample equilibrate, then measure its purity.

## Adding actions

Open an action in the toolbox on the left, fill in its fields, and click **Add**, or drag the
action by its handle onto the canvas.

```{image} ../_static/screenshots/design-add-action.png
:alt: The equilibrate action open in the toolbox, its temp field set to the run input temp_c
:width: 1440px
```

1. **Search** every action in the toolbox at once.
2. **Auto #** fills every field of a newly opened action with a `#name` input of the same
   name, for workflows where most values are set per run. **Fold** closes every group.
3. **Groups.** Flow control, then one group per instrument, then registered workflows. Click
   a group's name to fold it; the count beside it says how many actions it holds.
4. **A value for each argument.** Type a fixed value, or `#name` to make it an input you set
   when the workflow runs. Here `#temp_c` makes the temperature a run input. Saved values
   from earlier steps are suggested as you type, and a field with a
   [safety limit](instruments.md#safety-limits) shows it underneath (`°C · 20 to 80`).
5. **Save value as** names what the action returns, so later steps can use it as `#name` and
   the run records it. An action that returns a fixed-size tuple gets one field per item.
6. **Add** puts the action at the end of the current phase.
7. **The canvas** shows the steps of the phase you are editing, in the order they run.

**Run once per batch** matters when the workflow runs with a batch size above 1: tick it for
a step that should run once for the whole batch rather than once per sample (homing a robot,
for example).

### Flow control

```{image} ../_static/screenshots/design-flow-control.png
:alt: The flow control group of the toolbox, unfolded
:width: 322px
```

| Action | What it does |
| --- | --- |
| `if`, `while` | Run the steps inside only if, or as long as, a condition holds. The condition can use `#name` values. |
| `repeat` | Run the steps inside a fixed number of times. |
| `wait` | Pause the workflow for a number of seconds. |
| `pause` | Stop and show a message until someone resumes the run, for a manual step. |
| `input` | Ask the person at the bench for a value and save the answer. |
| `variable` | Set a named value: a number, `True`/`False`, or `"text"`. |
| `math` | Compute a value from numbers and `#name` values, such as `#x + 5 * (#y - 2)`. |
| `comment` | Write a line to the run log. |

## The designer at a glance

```{image} ../_static/screenshots/design-overview.png
:alt: The finished solubility_screen workflow in the designer
:width: 1440px
```

1. **Toolbox.** Instruments, flow control and registered workflows (see above).
2. **Phases.** Every workflow has three: **Prep** runs once before the experiment,
   **Experiment** is the part that repeats, and **Clean up** runs once at the end. Click a tab
   to edit that phase. See [Run behavior](run-behavior.md).
3. **A step.** Click it to change its values. Drag it up or down to reorder.
4. **Step buttons.** The eye switches a step off without deleting it (it is shown struck
   through and skipped when the workflow runs), then **Duplicate** and **Delete**.
5. **New** and **Save As.** Start an empty workflow, or save this one under a name. Saving
   with **Register this workflow** ticked makes it available in the toolbox's **Workflows**
   group, so other workflows can use it as a single step.
6. **Undo, redo and history.** See [Undo and history](#undo-and-history).
7. **More.** **Import** and **Export** a workflow as JSON, **Import Python** to turn a Python
   function into a workflow, **Rename**, **Save**, and **Disable editing** to lock a workflow
   so it can only be saved under a new name.
8. **Preview code.** Shows the Python the workflow compiles to. See
   [Previewing the code](#previewing-the-code).
9. **Quick Save** and **Prepare Run.** Save under the current name, and open the
   **Execution** page with this workflow. Neither starts the workflow.

## Undo and history

Every change to the workflow you are editing can be undone: adding, editing, moving,
disabling, duplicating or deleting a step, and renaming it. Undo goes back to when that
workflow was opened from the library, imported, or started with **New**, and no further, so
it never brings back a different workflow.

```{image} ../_static/screenshots/design-history.png
:alt: The history menu open, listing each change to the workflow
:width: 336px
```

1. **Undo** the last change.
2. **Redo** what was undone.
3. **History** lists every change with its time.
4. Pick one to go straight back, or forward, to it. The tick marks where you are now.

| Action | Windows and Linux | macOS |
|---|---|---|
| Undo | Ctrl+Z | ⌘Z |
| Redo | Ctrl+Y or Ctrl+Shift+Z | ⇧⌘Z |

The shortcuts leave text fields alone, so Ctrl+Z while typing undoes the typing. The history
is kept per browser session and survives a server restart.

## Previewing the code

Each workflow compiles to plain Python, which is what actually runs. **Preview code** shows it
beside the canvas.

```{image} ../_static/screenshots/design-code-preview.png
:alt: The Python code panel beside the canvas
:width: 1440px
```

1. **Preview code** opens and closes the panel.
2. **Single** shows the code for one sample at a time; **Batch** shows it for a batch of
   samples, with **Run once per batch** steps run once.
3. Each phase is a function. The `#name` inputs are its arguments, and the **Save value as**
   names are what it returns.
4. **Copy** or **Download** the code to run or share outside IvoryOS.

If a step is marked with a red or yellow icon, the platform has changed since the step was
added. See [Workflow step warnings](deck-compatibility.md).
