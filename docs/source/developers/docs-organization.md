# Docs organization

Use `/docs/source` as the home for long-form documentation.

## Audience folders

- `users/`: browser UI workflows, direct control, workflow execution, run phases, data review, screenshots, output files, and operator guidance.
- `examples/`: cross-audience platform examples, community integrations, gallery links, and showcase material.
- `integrators/`: launch settings, instrument exposure, input type annotations, Enum dropdowns, plugins, Python clients, MCP, remote instruments, and external systems.
- `developers/`: contributor setup, development workflow, testing, codebase structure, runtime internals, extension points, data model, HTTP route reference, ADRs, release notes, refactor notes, and docs maintenance.

## Format

Write narrative docs in Markdown. Use reStructuredText for pages that depend on Sphinx autodoc, Flask route extraction, or other directive-heavy behavior.

The root index, runtime API reference, and route reference pages stay in reStructuredText because `autodoc` and `sphinxcontrib.autohttp.flask` render reliably there.

## Canonical locations

- Keep `CHANGELOG.md` at the repository root because packaging, release tooling, and contributors expect it there. The docs site includes it from [Release notes](release-notes.md).
- Keep architecture and migration notes under `developers/`. If a root-level summary is needed for visibility, make it short and link back to the docs page.
- Keep package directories focused on Python code and docstrings. Do not add standalone `.md` docs under `ivoryos/`.
- Keep generated docs output out of source control. Build output belongs in ignored directories such as `docs/build/` or `docs/source/_build/`.
- Add an ADR under `developers/adr/` when a change affects runtime shape, integration contracts, deployment model, or optimizer/plugin extension contracts.

## Screenshots

The annotated screenshots in the user docs live in `_static/screenshots/` and are generated,
not taken by hand. `docs/screenshots/capture_screenshots.py` starts the abstract SDL example in
a temporary folder, drives the UI with Playwright the way a user would (it builds and runs the
`solubility_screen` workflow), draws the numbered markers, and overwrites the PNGs:

```console
pip install -e ".[doc]" playwright
playwright install chromium
python docs/screenshots/capture_screenshots.py
python docs/screenshots/capture_screenshots.py --only execute-config,execute-running
```

Re-run it after a UI change so the pictures match what users see. Each screenshot's markers are
listed in the script next to the docs page that explains them; when a marker is added, moved or
removed, update the numbered list under that image too. The Bayesian Optimization screenshot
needs an optimizer installed (`pip install -e ".[optimizer-ax]"`) and is skipped otherwise.
On a machine that cannot reach the CDNs the UI loads its libraries from, pass `--cdn-mirror`
with an npm `node_modules` folder holding them (the script lists the packages).

## External docs

Suite project pages are generated from their upstream README files during the Sphinx build:

- `integrators/client-api.md` from `ivoryos-client` `README.md`.
- `integrators/mcp-server.md` from `ivoryos-mcp` `README.md`.
- `integrators/plugins.md` from `ivoryos-plugin-template` `README.md`.

Do not edit those generated files directly. Update `external_readmes` in `docs/source/conf.py` if a source URL or target path changes.
