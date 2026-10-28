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

1. **A value for each argument.** Type a fixed value, or `#name` to make it an input you fill
   in when the workflow runs. Here `#temp_c` makes the temperature a run input. A
   [safety limit](instruments.md#safety-limits) on the field is shown under it.
2. **Save value as** names what the action returns, so later steps can use it as `#name` and
   the run records it.
3. **The steps** of the phase you are editing, in the order they run.

Above the toolbox, **Search** finds an action in any group, **Auto #** fills every field of
a newly opened action with a `#name` input, and **Fold** closes every group. **Run once per
batch** is for runs with a batch size above 1: tick it for a step that should run once for the
whole batch rather than once per sample, such as homing a robot.

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

1. **Toolbox**: instruments, flow control and registered workflows.
2. **Phases.** **Prep** runs once before the experiment, **Experiment** is the part that
   repeats, and **Clean up** runs once at the end. See [Run behavior](run-behavior.md).
3. **A step.** Click it to change its values; drag it to reorder.
4. **Switch off** (the eye), **Duplicate** and **Delete** the step. A switched-off step is
   struck through and skipped.
5. **Toolbar**: **New**, **Save As**, [undo and history](#undo-and-history), and **More**
   (import and export, rename, lock).
6. **Quick Save**, and **Prepare Run** to open the **Execution** page. Neither starts the
   workflow.

Ticking **Register this workflow** in **Save As** adds it to the toolbox's **Workflows** group,
so other workflows can use it as a single step. **More** also has **Import Python**, to turn a
Python function into a workflow, and **Disable editing**, after which the workflow can only be
saved under a new name.

## Undo and history

Every change to the workflow you are editing can be undone: adding, editing, moving,
disabling, duplicating or deleting a step, and renaming it. Undo goes back to when that
workflow was opened from the library, imported, or started with **New**, and no further, so
it never brings back a different workflow.

```{image} ../_static/screenshots/design-history.png
:alt: The history menu open, listing each change to the workflow
:width: 408px
```

1. **Undo** and **Redo**.
2. **History** lists every change with its time.
3. Pick one to go straight back, or forward, to it. The tick marks where you are now.

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
2. **Single** or **Batch**: the code for one sample at a time, or for a batch.
3. **Copy** or **Download** the code to run or share outside IvoryOS.

Each phase is a function: the `#name` inputs are its arguments, and the **Save value as** names
are what it returns.

If a step is marked with a red or yellow icon, the platform has changed since the step was
added. See [Workflow step warnings](deck-compatibility.md).
