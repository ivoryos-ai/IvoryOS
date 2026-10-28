# Instruments

The **Instruments** page lets you call any instrument method directly, without building a
workflow. Use it for setup, manual checks, calibration, or one-off operations.

Every card on this page is generated from the Python code of the running platform: one card
per public method, one field per argument. When the platform code changes, the page follows.

## The page at a glance

```{image} ../_static/screenshots/instruments-overview.png
:alt: Instruments page for the sdl module of the abstract SDL example, with numbered markers
:width: 1440px
```

1. **Instruments.** Pick one to see its methods.
2. **A method.** One field per argument and a button that runs it. A red asterisk marks a
   required field; defaults are filled in.
3. **Safety limit** for that field. See [Safety limits](#safety-limits).
4. **Hide** a method you never use. It moves to **Hidden functions** at the bottom of the page.
5. **Python console.** See [Python console](#python-console).

Also on this page: the search box above the cards, the **ⓘ** on each card for the method's
description, and, under the instrument list, **Download proxy** (a Python file that calls these
instruments over the network, see [Remote instrument proxy](../integrators/remote-instrument-proxy.md))
and **New connection** (add an instrument that is not in the running script). Drag a card to
reorder the page.

## Calling a method

Fill in the fields and click the method's button. IvoryOS converts each value to the
argument's type, calls the method, and shows the result at the top of the page. The cards are
covered while the call runs, and if a workflow is running or paused, IvoryOS asks before
calling an instrument directly.

```{image} ../_static/screenshots/instruments-call.png
:alt: The analyze method called from its card, with its result shown above
:width: 1344px
```

1. The values to call the method with.
2. The method's button runs it.
3. The value the method returned.

If the method raises an error, the message is shown in the same place instead.

## Safety limits

A driver says what an instrument *can* do. A safety limit says what it is *allowed* to do on
this bench: this heater may go to 250 °C, but with these vials nothing above 80. Limits are
kept outside the driver code, so setting one never means editing a vendor's package.

Click the shield at the end of a numeric or text field to set its limit:

```{image} ../_static/screenshots/instruments-safety-limit.png
:alt: The safety limit editor open under the temp field of the equilibrate method
:width: 618px
```

1. The shield of the field you are limiting.
2. **Min**, **Max** and **Unit** for a number; a text field takes a list of
   **Allowed values** instead. The unit is a label for people: nothing is converted.
3. **Save** keeps the limit. Open the shield again to change it or **Remove** it.

Once a limit is set, the shield shows it, and any call outside it is refused before it
reaches the instrument:

```{image} ../_static/screenshots/instruments-limit-blocked.png
:alt: A call with temp = 120 refused because the limit is 20 to 80 °C
:width: 1416px
```

1. The call is refused, with the limit it broke.
2. The shield now shows the limit, here `°C · 20 to 80`.

Limits apply everywhere a value can come from, not just this page: a workflow step, a
parameter table, or an optimizer suggestion. In a run, a refused step pauses the run like
any other error (see [Run behavior](run-behavior.md)), and a run whose saved values are
already out of bounds is refused before anything moves. The parameter table on the
**Execution** page shows each column's limit under its name.

Limits are saved in `ivoryos_data/safety.json`, so they survive a restart and can be copied to
another IvoryOS installation. An `Enum`, `Literal` or `bool` field needs no limit, since its
choices are already fixed. If the file cannot be read, every call is refused until it is fixed
or deleted.

## Python console

The terminal button in the bottom-right corner opens a console for the moments a form is not
enough: chaining two calls, checking an attribute, or printing a value.

```{image} ../_static/screenshots/instruments-console.png
:alt: The interactive console with two lines of Python and their output
:width: 447px
```

1. Python code. Every instrument is available by its name, here `sdl`, `balance` and `pump`.
2. **Execute** runs it.
3. Anything the code prints.

The console calls the instrument objects directly, so **safety limits are not checked
there**, and the calls go to the same objects a running workflow is using: avoid it while a
run is in progress. Importing modules is not allowed in the console.
