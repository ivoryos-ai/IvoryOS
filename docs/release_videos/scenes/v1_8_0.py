"""IvoryOS 1.8.0: dict, list, set and tuple arguments, typed arguments at the driver, safer expressions.

The story: try the dye lab's instruments, build a screen of dye recipes as a workflow, run it and look
at the data. Each caption names the CHANGELOG entry it shows; its ``say`` line is what the narration
speaks, and a short ``hold`` lets the scene act while the line goes on.
"""

SUBTITLE = "Shown on a simulated dye-mixing lab: a liquid handler mixes dyes, a plate reader measures the color."
INTRO = ("We'll show it on a simulated dye-mixing lab: a liquid handler mixes yellow and blue dye, "
         "and a plate reader measures the color.")
START = "/instruments/deck.liquid_handler"
COVER_POINTS = ["Table editor for dict arguments", "List, set & tuple inputs", "Typed values, safer expressions"]
YOUTUBE_TITLE = "What's new in IvoryOS 1.8: dict and list arguments, typed values, safer expressions"
DESCRIPTION = """\
IvoryOS 1.8 gives dictionary arguments a table editor, lets forms take list, set and tuple arguments, and \
passes every argument to your driver as the type it is annotated with. Workflow conditions and variable and \
math steps are now parsed safely instead of being run with eval, and the Instruments page runs methods \
without reloading.

Everything is shown on a simulated dye-mixing lab: a liquid handler mixes yellow and blue dye, a plate reader \
measures the color, and a workflow screens four recipes for the one closest to green."""
CANVAS = 790  # middle of the designer canvas, clear of the toolbox

SCREEN = [  # one well per recipe, from yellow to blue; the target color is green
    {"well": "A1", "yellow_ul": 80, "blue_ul": 20},
    {"well": "A2", "yellow_ul": 60, "blue_ul": 40},
    {"well": "A3", "yellow_ul": 40, "blue_ul": 60},
    {"well": "A4", "yellow_ul": 20, "blue_ul": 80},
]


def play(v):
    page = v.page
    v.chapter("Dict arguments get a table editor")
    instruments(v, page)
    v.chapter("List, set and tuple arguments")
    plate_reader(v, page)
    v.chapter("#variables inside a dict")
    designer(v, page)
    v.chapter("Typed values at the driver")
    run(v, page)
    v.chapter("Every sample in the data")
    data(v, page)
    v.clear_caption()
    v.chapter("Heads-up when upgrading")
    v.slide("Heads-up when upgrading", kicker="Upgrading to 1.8.0", bullets=[
        "`if` / `while` conditions and `variable` / `math` steps are parsed, no longer run with `eval`. "
        "`#reading['A540'] > 0.5` still works; lambdas, comprehensions and names starting with `_` are refused.",
        "Run inputs are checked before a run starts: a repeat run or API call that leaves `#yellow_ul` out "
        "is refused, instead of calling the driver with `None`.",
    ], hold=11, say="A heads-up before upgrading. If and while conditions, variables and math steps are now parsed "
                    "safely, instead of being evaluated as Python. Ordinary comparisons still work, but lambdas, "
                    "comprehensions and names starting with an underscore are refused. And run inputs are checked "
                    "before a run starts: a repeat run that leaves an input out is refused, instead of calling the "
                    "driver with None.")
    v.chapter("Also in 1.8.0")
    v.slide("Also in 1.8.0", kicker="1.8.0", bullets=[
        "Step-by-step user tutorials with annotated screenshots in the docs",
        "Steps cut off by a server restart show as interrupted",
        "Building blocks and registered workflows update once set",
        "Unfinished batches: every sample goes into the data CSV",
        "Fixes for the single-task overlay and blank pause/repeat defaults in older drafts",
    ], hold=9, say="Also in this release: step-by-step tutorials in the docs, steps cut off by a server restart "
                   "now show as interrupted, building blocks and registered workflows update once set, "
                   "and a few fixes.")


def cover(v):
    """The cover's screenshot, taken after the recording: the dye screen in the designer, with its Python."""
    page = v.page
    page.locator("#navbarSupportedContent .nav-link", has_text="Workflow").first.click()
    page.wait_for_load_state("networkidle")
    page.click("#showPythonCodeSwitch")
    page.wait_for_function("document.getElementById('python-code').textContent.includes('def ')")


def instruments(v, page):
    card = page.locator(".draggable-method-card#dispense")
    v.caption("Dict arguments get a table editor", "`dispense(recipe_ul: Dict[str, float])`: one row per dye, "
              "or switch to JSON.", tag="New · !223", hold=4.0,
              say="We start on the instruments page. Dictionary arguments now get a table editor: one row per dye, "
                  "here 60 microliters of yellow and 40 of blue. You can switch to JSON, and back.")
    v.dict_rows(card.locator(".structured-group"), {"yellow": "60", "blue": "40"})
    v.click(card.locator(".structured-switch button", has_text="JSON"), after=2.0)
    v.click(card.locator(".structured-switch button", has_text="Table"), after=0.8)

    v.caption("Run methods without reloading the page", "The result shows up in place; the form keeps "
              "what you typed.", tag="QoL · !225", kind="qol", hold=2.5,
              say="Methods now run without reloading the page. The result shows up in place, "
                  "and the form keeps what you typed.")
    v.click(card.locator("button[type=submit]"), after=0.8)
    v.ring(page.locator(".alert", has_text="Run Success").first, hold=3.5)
    v.clear_rings()


def plate_reader(v, page):
    v.click(page.locator("nav .list-group a, nav .list-group button", has_text="Plate reader"), after=0.3)
    page.wait_for_load_state("networkidle")
    card = page.locator(".draggable-method-card#read_absorbance")
    v.caption("List, set and tuple arguments", "Type `450, 540, 630` or Python syntax: "
              "`wavelengths_nm: Set[int]` arrives as `{450, 540, 630}`.", tag="New · !229", hold=3.5,
              say="On the plate reader: list, set and tuple arguments are new. Type the wavelengths with commas, "
                  "or in Python syntax, and the reader receives a set of integers.")
    v.type(card.locator("[name=wavelengths_nm]"), "450, 540, 630", after=1.5)
    v.caption("Optional Literal choices", "`shake: Optional[Literal['orbital', 'linear']]`: "
              "pick one, or leave it blank for None.", tag="Fix · !226", kind="fix", hold=2.5,
              say="Optional choices are fixed too: pick orbital or linear shaking, or leave it blank for none.")
    v.type(card.locator("[name=shake]"), "orbital", after=0.6)
    page.keyboard.press("Escape")
    v.click(card.locator("button[type=submit]"), after=0.8)
    v.ring(page.locator(".alert", has_text="Run Success").first, hold=4.0)
    v.clear_rings()


def designer(v, page):
    v.clear_caption()
    v.click(page.locator("#navbarSupportedContent .nav-link", has_text="Workflow").first, after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(0.5)
    v.caption("#variables inside a dict", "Each `#name` becomes a run input: one recipe per well of the screen.",
              tag="New · !223", offset=72, center=CANVAS, hold=4.0,
              say="Now the workflow designer. A dictionary can hold variables: each name with a hash sign becomes "
                  "a run input, so every well of the screen gets its own recipe.")
    form = v.toolbox_form("deck.liquid_handler", "dispense")
    v.dict_rows(form.locator(".structured-group"), {"yellow": "#yellow_ul", "blue": "#blue_ul"})
    v.type(form.locator("[name=well]"), "#well")
    v.add_step(form)
    v.wait(1.0)

    v.caption("Build the rest of the screen", "Mix, read the absorbance at three wavelengths, and score how close "
              "the color is to green.", offset=72, center=CANVAS, hold=2.5,
              say="Then the rest of the screen: mix, read the absorbance at three wavelengths, "
                  "and score how close the color is to green.")
    form = v.toolbox_form("deck.liquid_handler", "mix")
    v.type(form.locator("[name=well]"), "#well")
    v.add_step(form)
    form = v.toolbox_form("deck.plate_reader", "read_absorbance")
    v.type(form.locator("[name=well]"), "#well")
    v.type(form.locator("[name=wavelengths_nm]"), "450, 540, 630")
    v.say("Each measurement is saved under a name, reading, and the score as distance.", hold=0)
    v.type(form.locator("[name=return]"), "reading")
    v.add_step(form)
    form = v.toolbox_form("deck.plate_reader", "color_distance")
    v.type(form.locator("[name=well]"), "#well")
    v.type(form.locator("[name=return]"), "distance")
    v.add_step(form)
    v.wait(1.0)

    v.caption("The exported Python keeps the types", "Dicts, sets and run inputs are written as Python.",
              offset=72, center=CANVAS, hold=2.0,
              say="And the exported Python keeps the types: dictionaries, sets and run inputs are written "
                  "as real Python.")
    v.click("#showPythonCodeSwitch", after=0.3)
    page.wait_for_function("document.getElementById('python-code').textContent.includes('def ')")
    v.wait(0.5)
    v.ring("#python-code", hold=5.0)
    v.clear_rings()
    v.click("#showPythonCodeSwitch", after=0.3)

    v.clear_caption()
    v.click(page.locator("button", has_text="Save As"), after=0)
    page.wait_for_selector("#saveasModal.show")
    v.type("#saveasModal #run_name", "green_screen")
    v.fill("#saveasModal #description", "Mix yellow and blue dye, score each well against green.")
    with page.expect_navigation():
        v.click("#saveasModal button[type=submit]", after=0)
    page.wait_for_load_state("networkidle")
    v.wait(0.6)


def run(v, page):
    v.click(page.locator("a", has_text="Prepare Run").first, after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(0.5)
    v.caption("Run the screen", "Four recipes, one well each: the run inputs come from the dict's `#variables`.",
              hold=3.0, say="On the run page: four recipes, one well each. The columns come straight from the "
                            "variables in the dictionary.")
    v.config_rows([{k: str(val) for k, val in row.items()} for row in SCREEN])
    v.type("#display_name_config", "green_screen")
    v.click(page.locator("#tab2 button:has-text('Run')").first, after=1.0)
    v.drag("#resizer", y=210)
    v.caption("The driver gets typed values", "The run inputs are text; the log shows "
              "`recipe_ul={'yellow': 80.0, 'blue': 20.0}`, cast when the driver is called.",
              tag="Fix · !229", kind="fix", where="top", offset=56, hold=0,
              say="Run inputs are entered as text, but the driver now gets typed values: "
                  "the log shows the recipe arriving as numbers.")
    page.wait_for_function("document.getElementById('logging-panel').textContent.includes('dispense')",
                           timeout=30000)
    v.ring("#logging-panel", hold=0)
    v.wait_until_idle()
    v.wait(3.0)
    v.clear_rings()


def data(v, page):
    v.clear_caption()
    v.click(page.locator("#navbarSupportedContent .nav-link", has_text="Data").first, after=0.2)
    page.wait_for_load_state("networkidle")
    v.click(page.locator("tbody tr a", has_text="green_screen").first, after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(1.0)
    page.evaluate("window.scrollTo({top: document.getElementById('config-results').offsetTop - 110, "
                  "behavior: 'smooth'})")
    v.wait(1.0)
    v.caption("A2 is the closest to green", "Each sample's inputs and outputs; the CSV now also keeps every sample "
              "of a batch that was stopped early.", tag="QoL · !230", kind="qol", hold=3.0,
              say="On the data page, every sample's inputs and outputs. Well A2, 60 yellow and 40 blue, comes "
                  "closest to green. And when a batch is stopped early, the CSV now keeps every sample.")
    v.ring("#config-results table", hold=5.0)
    v.clear_rings()
