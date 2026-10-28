# Data

The **Data** page keeps a record of every run: when it ran, who submitted it, every step and
value, and the log. Records are kept from the moment a run starts, so a run that stopped
early or failed still has one.

## Runs

```{image} ../_static/screenshots/data-runs.png
:alt: The list of runs on the Data page
:width: 1440px
```

1. **Search** runs by name or by who submitted them.
2. **A run.** Click its name (or **View Logs**) to open it.
3. **Submitted By**: who started the run. Click a column name to sort by it.
4. **Download CSV** of the run's results: one row per sample, with its inputs and saved values.

## One run

The top of a run's page shows how it went:

```{image} ../_static/screenshots/data-run-overview.png
:alt: The page of one run, with its timeline and the results of its parameter table
:width: 1440px
```

1. Who submitted the run. Its number, name and how it ended are in the title above.
2. **Timeline** of the phases and iterations. Click one to jump to its details further
   down; Ctrl + scroll zooms.
3. **Config table results**: every row of the parameter table, its status, the values it ran
   with, and what it saved.

Further down are a plot of any recorded value, the downloads, and the details of each phase:

```{image} ../_static/screenshots/data-run-steps.png
:alt: The value plot, the download buttons and the details of the prep phase
:width: 1440px
```

1. **The value to plot** across the run's iterations. Hover a point to read it.
2. **Downloads**: **workflow data** (the results CSV), **workflow steps** (every step with its
   inputs, outputs and times), and **logs** (everything logged during this run).

Below them, a card for each phase and iteration lists its steps with their start and end
times, the input values it ran with (**Parameters**) and the values it saved (**Outputs**).
A step that failed is marked in red.

## Output files

IvoryOS stores run data under `ivoryos_data/` in the folder it was started from. The most
commonly inspected folders are:

- `results/`: workflow result CSV files.
- `scripts/`: generated workflow scripts and JSON workflow definitions.
- `config_csv/`: saved run configuration CSV files.
- `llm_output/`: design-agent prompts and raw responses.

See [Introduction](introduction.md#ivoryos-output-files) for the full layout.
