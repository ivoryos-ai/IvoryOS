# Library

The **Library** lists every saved workflow. Open one to edit or run it.

```{image} ../_static/screenshots/library.png
:alt: The Design Library with two saved workflows
:width: 1440px
```

1. **Deck** filter. Each workflow remembers the platform ("deck") it was built for.
2. **Search** workflows by name.
3. **Open** loads it into the [designer](workflow-designer.md). From there, **Prepare Run**
   takes it to the [Execution](execution.md) page.

**Delete** removes a workflow from the library; runs already made with it stay on the
[Data](data.md) page. A workflow's **Status** is `editing`, or `finalized` once editing was
disabled, after which it can only be saved under a new name.

Integrators can have a folder of workflow templates imported into the library each time
IvoryOS starts, so commonly used workflows are always available (`ivoryos.run(templates_dir=...)`).
