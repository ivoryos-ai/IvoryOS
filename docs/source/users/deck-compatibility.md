# Workflow step warnings

Sometimes a step in your workflow is marked with a red or yellow icon. This page
explains what those marks mean and what to do about them.

## Why a step gets marked

Your workflow remembers the exact actions you built it from. Those actions come
from the platform's code, which belongs to whoever maintains it, and they can
rename, move, or remove things at any time.

When that happens your workflow still looks fine, but a step in it no longer
points at anything real. You would normally only find out when the run stopped
partway through.

IvoryOS checks every step against the platform that is loaded right now, and
marks the ones that no longer match. You do not have to check for this yourself.

## What the marks mean

| Icon | What it means | What to do |
| --- | --- | --- |
| Red | The step will stop the run with an error. | Fix it before running. |
| Yellow | The step will still run, but something about it changed, so the result may not be what you intended. | Worth a look. |

## Where you will see them

**Workflow designer** — beside each affected step. Hover the icon to read the
reason. A banner at the top counts how many steps are affected.

```{image} ../_static/screenshots/design-step-warnings.png
:alt: A workflow with two red and one yellow step marker, and the banner above them
:width: 1190px
```

1. A red icon: this step will stop the run.
2. A yellow icon: this step will run, but something about it changed.
3. Hover an icon to read the reason.

The banner above the steps counts them and names the phases they are in.

**Step edit panel** — when you open a step, the reasons are listed at the top.

```{image} ../_static/screenshots/design-step-warning-edit.png
:alt: The edit panel of a flagged step, suggesting the method was renamed
:width: 532px
```

The reason is listed at the top, with a suggestion when the platform has something similar.

**Execution page** — before you start a run, naming every step that will fail,
so nothing starts that cannot finish.

```{image} ../_static/screenshots/execute-step-warnings.png
:alt: The warning on the Execution page listing the steps that will fail
:width: 1328px
```

The heading counts the steps that will stop the run; the list names every flagged step,
including those that may still run. Hover a line for the full reason.

Steps you have switched off are still marked in the designer, but they are not
counted on the execution page, because a switched-off step never runs.

## What the reasons are telling you

| The message says | What it means |
| --- | --- |
| Module is not on the current deck | The whole device or component this step uses is gone. |
| Method no longer exists | The device is still there, but this particular action is not. |
| No longer takes ... | The action no longer accepts one of the values this step fills in. |
| Now requires ... | The action needs a new value that this step does not provide. |
| Takes a different type ... now | The action still accepts this value, but expects a different kind of thing — a whole number instead of a decimal, for example. |
| Workflow is no longer registered | This step runs another workflow that has since been deleted or renamed. The step still runs, using the copy saved inside it, but that copy may be out of date. |

Where something similar exists on the platform now, the message suggests it — for
example *"It now has 'analyze' — was it renamed?"*.

"Deck" is the word the interface uses for the set of instruments and actions your
platform makes available.

## How to fix a step

Click the step in the designer to open it. The reasons are listed at the top of
the panel, along with any suggested name.

The most reliable fix is to **delete the step and add the action again** from the
left panel, so the form matches what the platform offers today. Editing the
existing step does not always work: its form is built from what the step saved,
so a value the platform has newly added will not appear as a field to fill in.

If many steps are flagged at once, check the deck selector at the top of the left
panel. You may be looking at a workflow that was built for a different platform
than the one currently loaded — the banner will say so when that is the case.

If you are not sure what changed, ask whoever maintains the platform code. The
messages name the exact action and value involved, which is usually all they
need.

## When no marks appear

No marks does not always mean everything was checked. IvoryOS stays quiet rather
than guessing when it has nothing to compare against — for example when no
platform is loaded at all. In that case an unmarked step has not been cleared; it
simply has not been checked.

---

If you maintain the platform code and want to know exactly which changes break a
saved workflow and which do not, see
[Keeping saved workflows working](../integrators/workflow-compatibility.md).
