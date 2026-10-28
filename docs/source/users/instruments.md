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

1. **Instrument list.** Each instrument (Python object) on the platform. Pick one to see its
   methods.
2. **Search.** Filter the cards by method name.
3. **Method card.** One per method. The fields come from the method's arguments: a red
   asterisk marks a required argument, a default value is filled in already, and an `Enum`
   or `Literal` argument offers its choices in a dropdown. The button at the bottom runs the
   method. Drag a card to put it somewhere else on the page; the order is kept.
4. **Safety limit.** The shield at the end of a field sets the range of values the
   instrument may be given. See [Safety limits](#safety-limits).
5. **Description.** Click to read the method's docstring.
6. **Hide.** Moves a method you never use out of the way, into **Hidden functions**.
7. **Hidden functions.** Lists the hidden methods; click the eye beside one to show it again.
8. **Download proxy** and **New connection.** Download a Python file that calls these
   instruments over the network (see [Remote instrument proxy](../integrators/remote-instrument-proxy.md)),
   or connect an instrument that is not in the running script by creating it from one of the
   Python classes IvoryOS can see.
9. **Python console.** Run a few lines of Python against the instruments. See
   [Python console](#python-console).

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
:width: 546px
```

1. The shield of the field you are limiting.
2. **Min**, **Max** and **Unit** for a number; a text field takes a list of
   **Allowed values** instead. The unit is a label for people: nothing is converted.
3. **Save** keeps the limit. Open the shield again to change it or **Remove** it.

Once a limit is set, the shield shows it, and any call outside it is refused before it
reaches the instrument:

```{image} ../_static/screenshots/instruments-limit-blocked.png
:alt: A call with temp = 120 refused because the limit is 20 to 80 °C
:width: 1344px
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
:width: 407px
```

1. Python code. Every instrument is available by its name, here `sdl`, `balance` and `pump`.
2. **Execute** runs it.
3. Anything the code prints.

The console calls the instrument objects directly, so **safety limits are not checked
there**, and the calls go to the same objects a running workflow is using: avoid it while a
run is in progress. Importing modules is not allowed in the console.
