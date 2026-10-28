# Library

The **Library** lists every saved workflow. Open one to edit or run it.

```{image} ../_static/screenshots/library.png
:alt: The Design Library with two saved workflows
:width: 1440px
```

1. **Deck** filter. Workflows remember the platform ("deck") they were built for; show only
   those for one deck, or all of them.
2. **Search** workflows by name.
3. **The workflow's name**, with the deck it was built for and its description beside it.
4. **Status**: `editing`, or `finalized` once editing was disabled, so it can only be saved
   under a new name.
5. **Open** loads it into the [designer](workflow-designer.md). From there, **Prepare Run**
   takes it to the [Execution](execution.md) page. **Delete** removes it from the library;
   runs already made with it stay on the [Data](data.md) page.

Integrators can have a folder of workflow templates imported into the library each time
IvoryOS starts, so commonly used workflows are always available (`ivoryos.run(templates_dir=...)`).
