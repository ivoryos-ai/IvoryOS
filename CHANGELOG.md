# Changelog
## 1.8.0 (November 3rd, 2026)
Arguments now reach the driver as their annotated types, dict, list, set and tuple arguments can be edited in forms, and the user docs are now [step-by-step tutorials](https://ivoryos.readthedocs.io/en/latest/users/index.html).

**Upgrading:** `if`/`while` conditions and [`variable`/`math` steps](https://ivoryos.readthedocs.io/en/latest/users/workflow-designer.html) no longer use `eval`, so lambdas, comprehensions and names or attributes starting with `_` are refused. A run also won't start if a required `#name` that no step sets has no value.

- !230 **[QoL]** include every sample of an unfinished batch in the data CSV
- !229 **[New]** support `List`, `Set` and `Tuple` arguments in forms
- !229 **[Bug]** cast arguments to their annotated types when the driver is called, and remove `eval` from workflows
- !228 **[New]** add user tutorial pages with annotated screenshots
- !227 **[Bug]** resolve building blocks and registered workflows not updating once set
- !226 **[Bug]** resolve `Optional[Literal]` handling in forms, workflows and exported code
- !225 **[QoL]** rework the Instruments page to run methods without reloading, and mark steps left running by a server restart as interrupted
- !224 **[Bug]** resolve single task overlay blocking the pop-up window
- !223 **[New]** add JSON/table editor for dict arguments, resolving their display and editing in the workflow designer
- !222 **[Bug]** resolve blank default pause/repeat input error in older drafts

## 1.7.2 (October 13th, 2026)
- !221 **[Bug]** fix failed to add method: The CSRF tokens do not match

## 1.7.1 (October 12th, 2026)
- !220 **[New]** tag each run with the user who submitted it, shown in the data panel and queue
- !219 **[Bug]** resolve config table editors display, with dropdowns for Enum and Literal inputs
- !218 **[QoL]** update run progress and config table editing over socket
- !217 **[QoL]** allow optional inputs to be empty or None in the config table
- !216 **[Bug]** resolve draft lost on server restart
- !215 **[Bug]** resolve Enum editing issue - number value can't edit
- !214 **[QoL]** collapse instruments in the toolbox by default
- !213 **[Bug]** resolve workflow changed by other sessions
- !187 **[QoL]** add undo/redo while editing the workflow

## 1.7.0 (October 7th, 2026)
- !212 **[New]** add safety guard system to enforce instrument limits with config file
- !211 **[QoL]** resolve designer toolbox UX - remove accordion
- !210 **[QoL]** resolve be able to edit iteration configs during the run
- !209 **[QoL]** resolve be able to edit pending tasks configs
- !208 **[Bug]** resolve queue experiment don't have unique name
- !207 **[Bug]** resolve fix Ax suggestion trial number, BayBE init steps number
- !206 **[QoL]** resolve allow proceeding to clean up for stop
- !205 **[Bug]** resolve Repeat block error when batch_size>1

## 1.6.14 (September 29th, 2026)
- !204 **[Bug]** resolve Ax plot error
- !203 **[QoL]** update to latest UI dependencies
- !202 **[Bug]** resolve error with SQLAlchemy >= 2.1

## 1.6.13 (September 23rd, 2026)
- !201 **[Bug]** resolve task end time not recorded when executing task from ivoryos client
- !200 **[New]** flag workflow steps incompatible with the loaded deck
- !199 **[Bug]** resolve method args dropped from the form when named like step settings (e.g. `batch_action`)
- !198 **[Bug]** resolve method args dropped by argument-name filtering when two args are similarly named

## 1.6.12 (September 8th, 2026)
- !197 **[QoL]** add experiment name upon starting execution
- !196 **[QoL]** remove sequence id order in json
- !195 **[New]** indicate batch in progress
- !194 **[QoL]** allow blank input when none as a default
- !193 **[New]** add built-in server/client busy status

## 1.6.11 (August 21st, 2026)
- !192 **[Bug]** resolve plugin page collapse icon display glitch
- !191 **[New]** display insight from Optimizer
- !190 **[Bug]** resolve arg config column error when toggle skip step

## 1.6.10 (August 13th, 2026)
- !189 **[Bug]** resolve ax optimizer error
- !188 **[Bug]** resolve "pass" in code renderer for skipped steps

## 1.6.9 (August 12th, 2026)
- !186 **[New]** Add .agent documentation
- !185 **[Bug]** resolve incompatible with ax-platform 1.3.1
- !184 **[Bug]** fix skip "none" values when parsing objectives
- !183 **[Bug]** resolve batch execution logging error
- !182 **[QoL]** add being able to skip steps during execution

## 1.6.8 (July 30th, 2026)
- !181 **[QoL]** resolve error status modal doesn't pop up from other tabs
- !180 **[Bug]** resolve error cannot download csv before first iteration done
- !179 **[New]** resolve event loop error from sync func using asyncio.run
- !178 **[Bug]** resolve type hint annotation doesnt work if union 2 types
- !177 **[Bug]** resolve batch step list consolidate render error
- !176 **[Bug]** resolve batch with registered workflows list error
- !175 **[QoL]** add logging for variable evaluation

## 1.6.7 (July 17th, 2026)
- !174 **[Bug]** resolve registered workflow not loading
- !172 **[QoL]** remove pause upon stop when there is no pending workflow
- !171 **[QoL]** minimize user input pop up to status icon
- !170 **[Bug]** resolve error can't stop right after variable expression error

## 1.6.6 (July 14th, 2026)
- !169 **[New]** Add Python console in Instrument panel (test release)
- !168 **[QoL]** enforce variable type from math expression
- !167 **[Bug]** resolve pickle error during introspection
- !164 **[Bug]** resolve error if doing math evaluation and there is a path in the context
- !163 **[QoL]** kwargs do not show up in design area

## 1.6.5 (June 12th, 2026)
- !165 **[Bug]** fix resave workflow to a different name error

## 1.6.4 (June 5th, 2026)
- !162 **[Bug]** handle different url_prefix for hosting multiple demos
- !161 **[Bug]** wait method is class conflict with builtin wait
- !160 **[New]** support Literal
- !159 **[QoL]** auto-hide methods that are not usable on a web app
- using permanent session and databae for demo config

## 1.6.3 (June 4th, 2026)
- !158 **[Bug]** fix error indicator doesn't go back to running
- !157 **[Bug]** fix no return value field for unannotated functions

## 1.6.2 (June 1st, 2026)
- !156 **[QoL]** be able to check task execution output by task ID
- !155 **[QoL]** fix plugin dropdown showing up in nav bar when there is only side bar plugin
- !154 **[QoL]** clean up and add singular server print on startup

## 1.6.1 (May 20th, 2026)
- !150 **[New]** f-string printing in code

## 1.6.0 (May 20th, 2026)
- !153 **[Bug]** fix workflow log and execution data downloads by correctly sanitizing workflow names
- !152 **[Bug]** add pause status check to runner state and update UI warning logic
- !151 **[QoL]** modernize and improve library template layout, styles, and filtering interface
- !149 **[Bug]** fix row index synchronization in configuration tab
- !148 **[Refactor]** major refactor
  - the monolithic `utils` package is now split into modular, domain-specific packages:
    - `forms/`: dynamic form generation
    - `models/`: database models
    - `parsers/`: serialization, type conversions, and code introspection
    - `runtime/`: execution state, task queuing, and the workflow execution engine
    - `script/`: script rendering and editing logic
    - `services/`: API proxies, LLM integration, and file/draft handling
  - extensive codebase refactoring including database queries and API route documentation
  - refactor step highlighting logic

## 1.5.21 (May 13th, 2026)
- **[Patch]** fix the paused queue when submitting

## 1.5.20 (May 13th, 2026)
- !146 **[Bug]** fix setting task name for optimization runs doesn't work
- !145 **[Bug]** fix csv configuration applied for repeat run in queue
- !144 **[QoL]** change iteration count to start at 1 instead of 0
- !143 **[QoL]** remove emoji in printout
- !142 **[Bug]** fix error during direct control function calling
- !141 **[New]** support multiple output in single function
- !140 **[QoL]** prevent saving empty .csv
- !139 **[New]** allow popups to be minimized or brought back, fix queue pause behavior

## 1.5.19 (April 20th, 2026)
- !136 **[New]** only display available optimizers based on installed packages; auto-select optimizer when only one is available
- !135 **[Bug]** stop pending now correctly completes the current iteration before stopping, and always runs the cleanup section
- !134 **[New]** auto-import workflow templates from a directory on startup (`ivoryos.run(templates_dir=...)`)

## 1.5.18 (April 10th, 2026)
- !133 **[Bug]** fix demo error

## 1.5.17 (April 10th, 2026)
- !132 **[New]** allow an always-on side plugin panel
- !130 **[New]** be able to view current run configuration
- !129 **[Bug]** fix undefined display name
- !128 **[New]** be able to do wait in a batch action
- !123 **[QoL]** be able to rename tasks in queue

## 1.5.16 (March 17th, 2026)
- !127 **[Bug]** fix logger removeHandler error on workflow completion
- !126 **[Bug]** fix compile error when if block has no actions (empty if block)
- !125 **[Bug]** fix generated proxy authentication error
- !124 **[QoL]** always display current iteration count out of total iterations during a run
- !122 **[Bug]** fix import class error in generated proxy

## 1.5.15 (March 5th, 2026)
- !119 **[Bug]** use `compile` instead of `exec` to avoid hardware code reloading and device connection issues
- !118 **[New]** downgrade problematic packages to support 32-bit Python installation
- !116 **[Bug]** fix so script will stop execution if error encountered and abort option selected (previously sometimes next step gets executed); save workflow data after each iteration instead of on stop/completion in case of Python/script error
- !115 **[Bug]** fix to improve editing enum arguments and using returned variables as method arguments
- !114 **[Bug]** displaying when login with incorrect combo
- !113 **[Bug]** no reload when checking syntax
- !112 **[QoL]** record step input parameters in workflow steps data CSV file
- !111 **[QoL]** record all app loggers in the downloaded workflow-specific logs CSV file
- !110 **[Bug]** fix syntax error if there is a space in a string configuration parameter

## 1.5.14 (February 8th, 2026)
- !108 **[Bug]** fix nested workflow flow control (if/while) execution bug
- !107 **[New]** save logs from data per run (credit to Veronica)

## 1.5.13 (February 5th, 2026)
- !106 **[QoL]** workflow library display improvement + scroll bar in config window
- !105 **[QoL]** clean up
- !104 **[Bug]** optional str argument input error in config
- !103 **[Bug]** maximum design size bug, replace session with json
- !102 **[QoL]** add a queue task view, check configs in pop-up window
- !101 **[QoL]** be able to add to name of queued tasks
- !100 **[QoL]** list consolidation in workflow designer
- !99 **[Bug]** code indent wrong when if statement used in nested workflow
- !98 **[Bug]** inner workflow missing context value
- !97 **[New]** Design Agent Feature (re-implementation of "Text-To-Code") (credit to ChemistryTobias)
- !96 **[QoL]** be able to scroll the code preview
- !95 **[Bug]** workflow with space in name returns immediately instead of being run

## 1.5.12 (January 30th, 2026)
- !94 **[Bug]** fix loaded CSV doesn't auto-update; show reset button when data doesn't match
- !93 **[New]** support `**kwargs` input
- !92 **[QoL]** add search bar on top of the controller and designer

## 1.5.11 (January 29th, 2026)
- !91 **[Bug]** fix database is locked error during workflow execution
- !90 **[New]** add task queue system

## 1.5.10 (January 26th, 2026)
- !89 **[Bug]** syntax error during execution with list of Enum; remove legacy compile in script runner
- !89 **[Bug]** error page when editing steps with list param

## 1.5.9 (January 26th, 2026)
- !88 **[Bug]** cannot scroll progress region after starting a run
- !87 **[Bug]** step retry not working in workflow execution
- !86 **[Bug]** page load error after proxy download + enum import in proxy
- !85 **[QoL]** dropdown menu showing existing variable names in workflow

## 1.5.8 (January 20th, 2026)
Workflow + batch fixes:
- !83 **[Bug]** remove type conversion for str type in `Union[]`
- !82 **[Bug]** arg substitute bug
- !82 **[Bug]** fix "batch_action" shows in step arg
- !81 **[Bug]** serialize all input args and outputs before db commit

New workflow behaviours:
- Register workflow (only registered workflows will show up in the workflow section)
- Once-per-batch action — duplicate results for all per-sample actions
- Auto-complete return values for workflows (inherit workflow returns)

## 1.5.7 (January 19th, 2026)
- !79 **[Bug]** once-per-batch action execution bug
- !78 **[Bug]** custom type / dropdown menu import

## 1.5.6 (January 16th, 2026)
- !77 **[QoL]** central/cloud db, auth tweak to support PostgreSQL, config from `.env`
- !76 **[QoL]** per-batch / per-sample option for workflow steps
- Minor UI text change for clarity

## 1.5.5 (January 13th, 2026)
- !75 **[Bug]** workflow steps not in sequential execution
- !74 **[Bug]** BO config UI — Choice input not reloaded

## 1.5.4 (January 8th, 2026)
Happy New Year from the IvoryOS team! 🎉
- !73 **[New]** import Python functions as workflow (Finn)
- !72 **[QoL]** UI/UX optimization
- !71 **[Bug]** autofill not working in workflow method
- !70 **[Bug]** BO history CSV upload not working
- !69 **[Bug]** use dynamic param within comment text
- !68 **[Bug]** fix can't add a math variable
- !67 **[QoL]** always save CSV regardless of output

## 1.5.3 (December 20th, 2025)
- !66 **[New]** human-in-the-loop user input (Yusuke)
- !65 **[New]** additional user log (Veronica)
- !64 **[New]** setter/getter support
- !63 **[Bug]** deduplicate in Ax custom strategy
- !62 **[QoL]** always-on progress bar

## 1.5.2 (December 15th, 2025)
- **[Bug]** fix Ax step range input conversion bug (Yusuke)

## 1.5.1 (December 14th, 2025)
- **[Bug]** fix progress HTML

## 1.5.0 (December 14th, 2025)
- **[New]** finalize the design as workflow step (beta)

## 1.4.16 (December 12th, 2025)
- **[Bug]** config list input conversion fix (Leo)

## 1.4.15 (December 12th, 2025)
- **[Bug]** list input type conversion fix (Ryan, Leo)
- **[New]** introduce math variable (credit: Veronica)

## 1.4.14 (December 12th, 2025)
- **[New]** add NIMO 2.0.5 append historical data
- **[New]** additional parameters for NIMO

## 1.4.13 (December 11th, 2025)
- **[Bug]** remove action return value save when `None` return type hinted (Veronica)
- **[New]** support `Optional[Enum]` type hinting (Veronica)

## 1.4.12 (December 5th, 2025)
- **[Bug]** temp fix for property in form loading (Ryan, Yusuke)
- **[Bug]** JSON-safe data check (Yusuke)
- **[Bug]** fix temp connection method call in script

## 1.4.11 (December 3rd, 2025)
- **[New]** add get optimizer schema route

## 1.4.10 (December 3rd, 2025)
- **[Bug]** row addition when switching config tabs
- **[New]** add upload historical data
- **[Bug]** fix Ax `num_trials=0` error

## 1.4.9 (November 27th, 2025)
- **[Bug]** step order sorting bug (everyone)

## 1.4.8 (November 25th, 2025)
- **[New]** stop-pending no longer prompts to continue cleanup (Veronica)
- **[New]** description field in script — add a description when saving (Veronica)

## 1.4.7 (November 23rd, 2025)
- **[QoL]** reorder parameter sweep entries (Irene, Maria, Ekaterina)
- **[New]** gracefully stop pending iterations, move to cleanup steps (Veronica)
- **[Bug]** Ax optimizer: fix bug when using reserved words (e.g. "test", "yield", "product") as objective name
- **[New]** Ax optimizer: allow failed trials — marked as Failed when missing objective(s) (SDL2)
- **[Bug]** fix handling of `None` values; empty string is now treated as `None` (Veronica)
- **[Bug]** fix type hint extraction when using `from __future__ import annotations` (SDL2)

## 1.4.6 (November 19th, 2025)
- **[Bug]** fix error when leading number in str input (Irene, Maria, Ekaterina)

## 1.4.5 (November 19th, 2025)
- **[Bug]** proxy authentication failing message fix (Maria Politi)
- **[Bug]** proxy class won't initialize if username/password combination is wrong
- **[Bug]** faulty display of single/batch code

## 1.4.4 (November 16th, 2025)
- **[Bug]** variable and function return bug (Veronica Lai)
- **[Bug]** handle Ax not accepting "test" as objective name
- **[QoL]** move optimizer init to thread
- Minor bug fixes

## 1.4.3 (November 14th, 2025)
Minor user interface changes:
- **[New]** create default admin user; allow password change by clicking on username
- **[New]** add option to change logo (replace or prepend the IvoryOS logo)
- **[QoL]** auto-create module list from imported modules; further imports will override existing modules
- **[QoL]** remove unused API endpoint
- **[Bug]** fix stop button not working

## 1.4.2 (November 12th, 2025)
- **[New]** add floating help icon (credit to Veronica Lai)
- **[Bug]** fix type conversion for args with no type hint (credit to Maria Politi)

## 1.4.1 (November 5th, 2025)
- **[New]** update optimizer API call
- **[New]** PoC plot for NIMO optimizer
- **[Bug]** minor bugs — device tab display error (credit to Finn Bork)

## 1.4.0 (November 2nd, 2025)
- **[New]** introduce batch execution, step-wise repeat per batch
- **[New]** introduce batch action (light purple) — repeat only once per batch
- **[New]** redesign script runner with granular action control in if/for/while
- **[Bug]** fix Ax/Bayes errors for compatibility with the newest version
- **[QoL]** BO tab and input will restore on reload

## 1.3.6 – 1.3.8 (October 9th, 2025)
- **[Bug]** handle editing error on deleted steps (can occur when multiple browsers are open and inactive tabs are not refreshed)
- **[Bug]** fix Ax platform import path (`No module named 'ax.modelbridge'`)
- **[New]** add NIMO as an optimizer option
- **[Bug]** fix Flask async install
- **[Bug]** forgot to include `nimo_optimizer.py` in 1.3.6 release

## 1.3.5 (October 2nd, 2025)
- **[Bug]** fix output list
- **[New]** allow async
- **[Bug]** variable not found in execution (credit: Jenny Zhou)
- **[New]** missing variable alert (credit: Jenny Zhou)
- **[Bug]** minor fix in `__init__` and add optional installs

## 1.3.4 (September 18th, 2025)
- **[New]** allow customized notification handler for workflow pause (human intervention)
- **[Bug]** fix redundant db backup when there are no workflow records
- **[Bug]** fix function call "Unknown API Error" with "busy"
- **[QoL]** optimize db addition with `flush()`
- **[QoL]** docs (README) update

## 1.3.3 (September 11th, 2025)
- **[Bug]** fix Python-to-JSON conversion; support more deck and blocks

## 1.3.2 (September 10th, 2025)
- **[Bug]** fix old workflow db schema handling; update status too
- **[Bug]** fix `time.sleep()` Python-to-JSON conversion
- **[New]** allow building block execution in MCP
- **[QoL]** fix docs and Sphinx auto-doc

## 1.3.1
- **[Bug]** fix socketio in demos
- **[Bug]** `time.sleep()` execution error in Python 3.7 (credit: Maria Politi)

## 1.3.0
- **[New]** refactor the workflow record db to support visualization (old workflow db backed up and dropped)
- **[Bug]** fix Enum dynamic input and input in Devices
- **[Bug]** fix snapshot converted to str issue

## 1.2.8
- **[New]** add human intervention (pause) to flow control
- **[New]** add `block` decorator for Python functions
- **[QoL]** move `run()` from `__init__.py` to `server.py`
- **[QoL]** optimize drag/drop — no drag when selecting text
- **[Bug]** fix type conversion error for "any" type

## 1.2.7
- **[Security]** remove API function call backdoor
- **[New]** modify RPC script generation to support auth
- **[QoL]** clean up function call error handling
- **[Bug]** fix workflow save flash

## 0.1.23
- **[New]** show line numbers
- **[New]** add dropdown menu option for Enum type
- **[New]** add retry option when erroring out
- **[New]** new wait implementation — can stop during waiting
- **[New]** add direct blueprint plugin config

## 0.1.22
- **[New]** add data page
- **[Bug]** fix phase order in run page
- **[New]** add client feature to device (direct control) page

## 0.1.21
- **[New]** add drag and drop to design
- **[New]** add bool option for variables
- **[QoL]** remove About from top tab
- **[QoL]** move logic (if, while, etc.) to "flow control"

## 0.1.20
- **[New]** add task progress tracking

## 0.1.19
- **[New]** add pause/resume and stop to execution page
- **[Bug]** fix Python script display

## 0.1.18
- **[Bug]** fix prep/cleanup repeat issue
- **[Bug]** remove duplicate return values
- **[QoL]** add plugin docs

## 0.1.17
- **[QoL]** move video feed as plugins

## 0.1.16
- **[Bug]** fix pip setup

## 0.1.15
- **[New]** add modular tabs
- **[New]** add video feed

## 0.1.14
- **[Bug]** fix statement display for logic functions
- **[QoL]** display docstrings in functions

## 0.1.13
- **[Bug]** fix edit action input type bugs
- **[Bug]** fix variable calling in function
- **[New]** add warning for undefined variable

## 0.1.12
- **[New]** add checking for duplicate entry in config file
- **[New]** add return value output in backend control
- **[New]** add repeat in workflow design
