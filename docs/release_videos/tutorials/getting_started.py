"""Getting started with IvoryOS: from a few Python classes to a lab run from the browser.

A narrated walkthrough for new users, not tied to a release: the Python a lab needs (a shortened
``dye_lab.py``, shown as code), then each page of the web app on the dye-mixing demo lab, in the order
of work: Home, Instruments, Workflow, Library, Execution and Data.

    python docs/release_videos/record.py --tutorial getting_started
"""

TITLE = "Getting started with IvoryOS"
SUBTITLE = "From a few Python classes to a lab you can control, script and run from the browser."
INTRO = ("This is a tour of IvoryOS, an open-source orchestrator for self-driving labs. We'll start from a few "
         "lines of Python, then walk through each part of the web app it makes: the instruments, the workflow "
         "designer, running an experiment, and the data.")
OUTRO_TITLE = "pip install ivoryos"
OUTRO = ("To try it, pip install ivoryos and point it at your own lab's Python. The documentation, linked in the "
         "description, covers every page in depth. Thanks for watching!")
COVER_TITLE = "Getting started"
COVER_POINTS = ["Your instruments as Python classes", "Design, run and track workflows", "No front-end code to write"]
YOUTUBE_TITLE = "Getting started with IvoryOS: turn your lab's Python into a web app"
DESCRIPTION = """\
A walkthrough of IvoryOS for new users. We start from a few lines of Python that drive a simulated \
dye-mixing lab, start IvoryOS on them, and go through each part of the web app it makes: calling \
instrument methods directly, building a workflow with run inputs, running it from a table of values, and \
reading the results.

To follow along without hardware, start the abstract SDL example from the IvoryOS repository; the \
documentation shows how."""
START = "/"
CANVAS = 790  # middle of the designer canvas, clear of the toolbox

# dye_lab.py, shortened to what the walkthrough talks about; the line numbers below point into it
MY_LAB = '''\
from typing import Dict, Literal
import ivoryos


class LiquidHandler:
    def dispense(self, recipe_ul: Dict[str, float], well: str = "A1"):
        """Dispense each dye of the recipe into a well."""

    def mix(self, well: str = "A1", cycles: int = 3):
        """Aspirate and dispense the well a few times."""


class PlateReader:
    def read_absorbance(self, well: str = "A1") -> Dict[str, float]:
        """Absorbance of the well at 450, 540 and 630 nm."""

    def color_distance(self, well: str, target: Literal["green", "orange"] = "green") -> float:
        """How far the well's color is from a target color."""


liquid_handler = LiquidHandler()
plate_reader = PlateReader()

ivoryos.run(__name__)'''

TERMINAL = '''\
$ pip install ivoryos
$ python my_lab.py
 * Running on http://127.0.0.1:8000
# open 127.0.0.1:8000/ivoryos in a browser, sign in as admin / admin'''

SCREEN = [  # one well per recipe, from yellow to blue; the target color is green
    {"well": "A1", "yellow_ul": 80, "blue_ul": 20},
    {"well": "A2", "yellow_ul": 60, "blue_ul": 40},
    {"well": "A3", "yellow_ul": 40, "blue_ul": 60},
    {"well": "A4", "yellow_ul": 20, "blue_ul": 80},
]


def play(v):
    page = v.page
    v.chapter("Your lab in Python")
    python_code(v)
    v.chapter("The home page")
    home(v, page)
    v.chapter("Instruments: try a method")
    instruments(v, page)
    v.chapter("Build a workflow")
    designer(v, page)
    library(v, page)
    v.chapter("Run an experiment")
    execution(v, page)
    v.chapter("Data and results")
    data(v, page)
    v.clear_caption()
    v.chapter("Recap")
    v.slide("That's the basics", kicker="Recap", bullets=[
        "Write each instrument as a Python class; its type hints make the forms",
        "Try methods one call at a time on the Instruments page",
        "Build workflows in the designer, with `#name` for what changes per run",
        "Run them from a table, a repeat count, or an optimizer",
        "Find every run on the Data page, ready to download",
    ], hold=8, say="That's the basics. Write each instrument as a Python class, and try its methods on the "
                   "instruments page. Build a workflow in the designer, run it from a table, a repeat count, or an "
                   "optimizer, and find every result on the data page.")


def nav(page, label):
    return page.locator("#navbarSupportedContent .nav-link", has_text=label).first


def python_code(v):
    v.code(MY_LAB, file="my_lab.py", kicker="Step 1 · Your lab in Python",
           say="Everything starts with the Python that drives your instruments. Here's a shortened version of our "
               "demo lab: a liquid handler that mixes dyes, and a plate reader that measures the color.")
    v.focus("5-10", "13-18", say="Each instrument is a plain Python class. There's no base class to inherit, and no "
                                 "decorator to add.")
    v.focus(6, 9, 17, notes={6: "a table editor", 9: "a number field", 17: "a drop-down"},
            say="Every public method becomes a form you can run, and the type hints pick its fields: a dictionary "
                "becomes a table, an integer a number field, and a fixed set of choices a drop-down list.")
    v.focus(7, 10, 15, 18, say="Docstrings become each method's description in the app.")
    v.focus(14, 17, notes={14: "a result", 17: "a result"},
            say="And what a method returns comes back as a result, which a workflow can save as data.")
    v.focus(21, 22, say="Create one object per instrument at the top of the module. Together, they're the deck "
                        "IvoryOS controls.")
    v.focus(24, say="Then one line hands the module to IvoryOS.")
    v.chapter("Install and start IvoryOS")
    v.code(TERMINAL, file="Terminal", kicker="Step 2 · Start it", console=True,
           say="Install IvoryOS with pip, and run the file. It starts a web server on your computer: open the address "
               "it prints, at slash IvoryOS, and sign in. A new installation has an admin account with the password "
               "admin; change it from the account menu.")
    v.clear_slide()


def home(v, page):
    v.caption("The home page", "Library, Workflow, Execution, Data and Instruments: the main pages, in the order of "
              "work.", hold=2.5,
              say="This is the home page. Along the top are the main pages, in the order you'll use them: the library "
                  "of saved workflows, the workflow designer, execution, data, and the instruments.")
    v.ring(page.locator("#navbarSupportedContent .navbar-nav").first, hold=0)
    v.finish_line()
    v.clear_rings()
    v.caption("The status, on every page", "Idle, Running, Paused, or waiting for you.", hold=1.0,
              say="The status in the corner of every page says whether a run is going: idle, running, paused, or "
                  "waiting for an answer from you.")
    v.ring("#global-status-icon", pad=4, hold=0)
    v.finish_line()
    v.clear_rings()


def instruments(v, page):
    v.clear_caption()
    v.click(nav(page, "Instruments"), after=0.3)
    page.wait_for_load_state("networkidle")
    v.click(page.locator("nav .list-group a, nav .list-group button", has_text="Liquid handler"), after=0.3)
    page.wait_for_load_state("networkidle")
    card = page.locator(".draggable-method-card#dispense")
    v.caption("Instruments", "Every method of every instrument, as a card with a field per argument.", hold=3.0,
              say="On the instruments page, your instruments are listed on the left. Each method is a card, with a "
                  "field for every argument, built from its type hints.")
    v.ring(page.locator("nav .list-group").first, hold=0)
    v.finish_line()
    v.clear_rings()
    v.caption("Try a method", "Fill in the fields and click its button; the result shows at the top.", hold=2.5,
              say="Fill in the fields and run it. Here, 60 microliters of yellow and 40 of blue into well A1.")
    v.dict_rows(card.locator(".structured-group"), {"yellow": "60", "blue": "40"})
    v.click(card.locator("button[type=submit]"), after=0.8)
    v.say("The result shows up at the top. It's the quickest way to check that an instrument does what you expect.",
          hold=0)
    v.ring(page.locator(".alert", has_text="Run Success").first, hold=0)
    v.finish_line()
    v.clear_rings()

    v.click(page.locator("nav .list-group a, nav .list-group button", has_text="Plate reader"), after=0.3)
    page.wait_for_load_state("networkidle")
    card = page.locator(".draggable-method-card#read_absorbance")
    v.caption("Results come back as values", "`read_absorbance` returns the absorbance at each wavelength.",
              hold=2.0, say="Now read that well on the plate reader. It returns the absorbance at each wavelength.")
    v.click(card.locator("button[type=submit]"), after=0.8)
    v.ring(page.locator(".alert", has_text="Run Success").first, hold=0)
    v.finish_line()
    v.wait(1.0)
    v.clear_rings()


def designer(v, page):
    v.clear_caption()
    v.click(nav(page, "Workflow"), after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(0.5)
    v.caption("The workflow designer", "The toolbox holds every method, and flow control: `if`, `repeat`, `while`.",
              offset=72, center=CANVAS, hold=3.0,
              say="The workflow designer puts steps in order. The toolbox on the left holds every instrument's "
                  "methods, and flow control, like if, repeat and while.")
    v.ring("#toolbox", hold=0)
    v.finish_line()
    v.clear_rings()
    v.caption("Three phases", "`Prep` runs once before, `Experiment` once per sample, `Clean up` once at the end.",
              offset=72, center=CANVAS, hold=2.0,
              say="A workflow has three phases. Preparation runs once at the start, the experiment runs once for "
                  "every sample, and clean up runs once at the end.")
    v.ring(page.locator(".nav-tabs", has=page.locator(".nav-link", has_text="Clean up")).first, hold=0)
    v.finish_line()
    v.clear_rings()

    v.caption("`#name` makes a run input", "Values that change from run to run: here the recipe and the well.",
              offset=72, center=CANVAS, hold=3.5,
              say="Add a step from the toolbox. Any value that should change from run to run, mark with a hash "
                  "sign: it becomes an input of the run. Here, the volume of each dye, and the well.")
    form = v.toolbox_form("deck.liquid_handler", "dispense")
    v.dict_rows(form.locator(".structured-group"), {"yellow": "#yellow_ul", "blue": "#blue_ul"})
    v.type(form.locator("[name=well]"), "#well")
    v.add_step(form)
    form = v.toolbox_form("deck.liquid_handler", "mix")
    v.type(form.locator("[name=well]"), "#well")
    v.add_step(form)

    v.caption("Save results under a name", "Use them in later steps; the Data page records them.",
              offset=72, center=CANVAS, hold=3.0,
              say="Save a step's result under a name, like reading, to use it in later steps. Saved results are also "
                  "what the data page records.")
    form = v.toolbox_form("deck.plate_reader", "read_absorbance")
    v.type(form.locator("[name=well]"), "#well")
    v.type(form.locator("[name=return]"), "reading")
    v.add_step(form)
    form = v.toolbox_form("deck.plate_reader", "color_distance")
    v.type(form.locator("[name=well]"), "#well")
    v.type(form.locator("[name=return]"), "distance")
    v.add_step(form)
    v.wait(1.0)

    v.caption("It's Python underneath", "The preview shows the script the workflow runs; copy or download it.",
              offset=72, center=CANVAS, hold=2.0,
              say="Underneath, a workflow is Python. The preview shows the script it runs, and you can copy or "
                  "download it.")
    v.click("#showPythonCodeSwitch", after=0.3)
    page.wait_for_function("document.getElementById('python-code').textContent.includes('def ')")
    v.ring("#python-code", hold=0)
    v.finish_line()
    v.wait(1.0)
    v.clear_rings()
    v.click("#showPythonCodeSwitch", after=0.3)

    v.clear_caption()
    v.click(page.locator("button", has_text="Save As"), after=0)
    page.wait_for_selector("#saveasModal.show")
    v.say("Then save it with a name.", hold=0)
    v.type("#saveasModal #run_name", "green_screen")
    v.fill("#saveasModal #description", "Mix yellow and blue dye, score each well against green.")
    with page.expect_navigation():
        v.click("#saveasModal button[type=submit]", after=0)
    page.wait_for_load_state("networkidle")
    v.wait(0.6)


def library(v, page):
    v.click(nav(page, "Library"), after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(0.5)
    row = page.locator("tbody tr", has_text="green_screen").first
    v.caption("The library", "Every saved workflow, ready to open again.", hold=2.0,
              say="Saved workflows go to the library, where you can search for one and open it again.")
    v.ring(row, hold=0)
    v.finish_line()
    v.clear_rings()
    v.click(row.locator("a, button", has_text="Open").first, after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(0.8)


def execution(v, page):
    v.clear_caption()
    v.click(page.locator("a", has_text="Prepare Run").first, after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(0.5)
    v.caption("Three ways to run", "Repeat, a table of values, or Bayesian optimization, depending on the workflow.",
              hold=3.0, say="Prepare Run opens the execution page. A workflow without inputs runs a number of "
                            "times. One with inputs runs from a table of values, or an optimizer can choose the "
                            "values, when the workflow returns a number.")
    v.ring("#myTabs", hold=0)
    v.finish_line()
    v.clear_rings()
    v.caption("One row per sample", "The columns are the workflow's `#name` inputs.", hold=3.0,
              say="Our workflow has inputs, so we fill in a table: one row for each sample, here four recipes, one per "
                  "well.")
    v.config_rows([{k: str(val) for k, val in row.items()} for row in SCREEN])
    v.type("#display_name_config", "green_screen")
    v.click(page.locator("#tab2 button:has-text('Run')").first, after=1.0)
    v.drag("#resizer", y=210)
    v.caption("Follow the run", "The step running now is highlighted; the log shows every call and its values.",
              where="top", offset=56, hold=0,
              say="While it runs, the current step is highlighted, and the log shows every call with its values.")
    page.wait_for_function("document.getElementById('logging-panel').textContent.includes('dispense')",
                           timeout=30000)
    v.ring("#logging-panel", hold=0)
    v.finish_line()
    v.clear_rings()
    v.caption("Pause or stop", "Pause, stop now, or finish the current sample and stop.", where="top", offset=56,
              hold=0, say="You can pause it at any time, stop it right away, or let the current sample finish and "
                          "stop after it.")
    v.ring("#pause-resume", "#abort-current", "#abort-pending", pad=4, hold=0)
    v.finish_line()
    v.clear_rings()
    v.wait_until_idle()
    v.wait(1.5)


def data(v, page):
    v.clear_caption()
    v.click(nav(page, "Data"), after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(0.5)
    row = page.locator("tbody tr", has_text="green_screen").first
    v.caption("Every run, recorded", "Search runs by name, and download any of them as CSV.", hold=2.0,
              say="The data page keeps a record of every run. Search them by name, or download a run's results as a "
                  "CSV file.")
    v.ring(row, hold=0)
    v.wait(2.5)
    v.ring(row.locator("a, button", has_text="Download CSV").first, pad=4, hold=0)
    v.finish_line()
    v.clear_rings()

    v.clear_caption()
    v.click(row.locator("a", has_text="green_screen").first, after=0.2)
    page.wait_for_load_state("networkidle")
    v.wait(1.0)
    page.evaluate("window.scrollTo({top: document.getElementById('config-results').offsetTop - 110, "
                  "behavior: 'smooth'})")
    v.wait(1.0)
    v.caption("Inputs and outputs, side by side", "One row per sample: A2 is the closest to green.", hold=2.5,
              say="Opening a run shows each sample's inputs and outputs, side by side. Well A2, 60 yellow and 40 "
                  "blue, is the closest to green.")
    v.ring("#config-results table", hold=0)
    v.finish_line()
    v.clear_rings()
    v.clear_caption()
    page.evaluate("window.scrollTo({top: document.getElementById('output-select').getBoundingClientRect().top "
                  "+ window.scrollY - 90, behavior: 'smooth'})")
    v.wait(1.0)
    v.caption("Plot any result", "Pick a saved value to plot it across the samples.", hold=2.0,
              say="And you can plot any saved result across the samples: here, the distance to green, lowest for A2.")
    v.move("#output-select")
    page.select_option("#output-select", "distance")
    v.wait(1.0)
    v.ring("#phase-plot", hold=0)
    v.finish_line()
    v.wait(1.0)
    v.clear_rings()


def cover(v):
    """The cover's screenshot, taken after the recording: the workflow the tutorial built, in the designer."""
    page = v.page
    nav(page, "Workflow").click()
    page.wait_for_load_state("networkidle")
