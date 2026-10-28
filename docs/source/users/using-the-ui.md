# Using the UI

The IvoryOS browser UI is built from the Python platform that is running: its instruments,
their methods, and their arguments become the pages, forms and workflow actions you see. This
page is a tour of the main screen; each area has a page of its own.

## Following along

The screenshots in these pages come from the abstract SDL example in the IvoryOS repository,
a pretend lab with a `balance`, a `pump`, and an `sdl` module that doses solids and solvents,
equilibrates a sample, and analyzes it. To try each step yourself, start it from a checkout:

```console
python community/examples/abstract_sdl_example/abstract_sdl.py
```

Then open <http://127.0.0.1:8000/ivoryos> and sign in. A new installation has an `admin`
account with the password `admin`; change it from the account menu.

Numbered orange markers on a screenshot point at what the list below it describes.

## The main screen

```{image} ../_static/screenshots/ui-tour.png
:alt: The IvoryOS home page with its navigation bar
:width: 1440px
```

The navigation bar follows the usual order of work, left to right:

1. **[Library](library.md)**: saved workflows, ready to open.
2. **[Workflow](workflow-designer.md)**: the designer, where actions are put in order.
3. **[Execution](execution.md)**: set up a run, start it, and follow it.
4. **[Data](data.md)**: the record of every run, with downloads.
5. **[Instruments](instruments.md)**: call any instrument method directly, set safety
   limits, and open the Python console.
6. **Account menu**: change your password, customize the logo, or log out.
7. **Status**, in the corner of every page: **Idle**, **Running**, **Paused**, **Error**, or
   **Input** when a run is waiting for an answer. Click it when it says **Error** or **Input**
   to bring back the dialog that is waiting for you.
8. **Workflow tips**: a short guide to building workflows.

The home page also lists the most recently changed workflows, with a button to open each one
in the designer.

## A typical session

1. Try the instruments one call at a time on the [Instruments](instruments.md) page, and set
   [safety limits](instruments.md#safety-limits) on anything that could do harm.
2. Build a workflow in the [Workflow designer](workflow-designer.md), using `#name` for every
   value you want to set per run.
3. Click **Prepare Run**, choose how to run it on the [Execution](execution.md) page, and
   start it. [Run behavior](run-behavior.md) explains pausing, stopping, and errors.
4. Review the results on the [Data](data.md) page, or download them.
5. Next time, open the workflow again from the [Library](library.md).
