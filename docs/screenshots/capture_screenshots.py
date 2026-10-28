"""Capture the annotated UI screenshots used by the user docs.

The script launches the abstract SDL example
(``community/examples/abstract_sdl_example/abstract_sdl.py``) in a fresh temporary folder,
drives the browser UI with Playwright the way a user would (build a workflow, run it, review
the data), draws numbered markers on the parts each page of the docs talks about, and writes
the PNGs to ``docs/source/_static/screenshots/``.

The numbers drawn on each image are listed in ``SHOTS`` below and explained in the matching
docs page, so when a marker moves, update both.

Usage::

    pip install -e ".[doc]" playwright
    playwright install chromium
    python docs/screenshots/capture_screenshots.py              # every screenshot
    python docs/screenshots/capture_screenshots.py --only design-overview,execute-config

Options:

``--base-url``     use an IvoryOS server that is already running instead of launching one;
                   it must be the abstract SDL example with an ``admin``/``admin`` account
                   and no saved workflows.
``--cdn-mirror``   a ``node_modules`` folder holding the front-end libraries the UI loads
                   from CDNs, for machines that cannot reach them (see ``CDN_FILES``).
``--headed``       watch the browser while it works.
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
EXAMPLE_DIR = REPO / "community" / "examples" / "abstract_sdl_example"
OUT_DIR = REPO / "docs" / "source" / "_static" / "screenshots"

VIEWPORT = {"width": 1440, "height": 900}
SCALE = 2  # device pixel ratio: sharp text when the docs theme scales the image down

# The UI loads these from CDNs. With --cdn-mirror they are served from an npm node_modules
# folder instead: ``npm install`` the packages named on the right at the versions in the URLs.
CDN_FILES = {
    "https://code.jquery.com/jquery-3.7.1.min.js": "jquery/dist/jquery.min.js",
    "https://code.jquery.com/ui/1.13.3/jquery-ui.min.js": "jquery-ui/dist/jquery-ui.min.js",
    "https://cdn.plot.ly/plotly-2.31.1.min.js": "plotly.js-dist-min/plotly.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.4.1/socket.io.js": "socket.io-client/dist/socket.io.js",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js": "@highlightjs/cdn-assets/highlight.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/default.min.css": "@highlightjs/cdn-assets/styles/default.min.css",
    "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/codemirror.min.css": "codemirror/lib/codemirror.css",
    "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/codemirror.min.js": "codemirror/lib/codemirror.js",
    "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/mode/python/python.min.js": "codemirror/mode/python/python.js",
}
# cdn.jsdelivr.net/npm/<package>@<version>/<path> and unpkg.com/<package>@<version>/<path>
# map onto node_modules/<package>/<path> (bootstrap, bootstrap-icons, sortablejs, vis-timeline)
NPM_CDN = re.compile(r"https://(?:cdn\.jsdelivr\.net/npm|unpkg\.com)/(@?[^@/]+(?:/[^@/]+)?)@[^/]+/(.*)")
CONTENT_TYPES = {".js": "application/javascript", ".css": "text/css", ".woff2": "font/woff2", ".woff": "font/woff"}

# The example deck, started the way its own ``__main__`` block does, with its loggers attached
# so the execution log has something to show. ``random`` is seeded so analyze() is repeatable.
LAUNCHER = """
import random, sys
random.seed(7)
sys.path.insert(0, {example!r})
import abstract_sdl  # noqa: F401  (builds the deck: balance, pump, sdl)
import ivoryos
ivoryos.run("abstract_sdl", port={port}, debug=False, logger=["logger_name", "balance", "pump"])
"""

ACCENT = "#e8590c"

# Draws the markers: an outline around each target and a numbered badge on one of its corners.
# Fixed positioning against the viewport, so screenshots are taken without scrolling after it.
ANNOTATE_JS = """
({marks, accent}) => {
    document.querySelectorAll('.ivy-doc-mark').forEach(e => e.remove());
    const layer = document.createElement('div');
    layer.className = 'ivy-doc-mark';
    layer.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647;';
    for (const m of marks) {
        const pad = m.pad;
        const x = m.box.x - pad, y = m.box.y - pad, w = m.box.width + 2 * pad, h = m.box.height + 2 * pad;
        if (m.outline) {
            const box = document.createElement('div');
            box.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;` +
                `border:2.5px solid ${accent};border-radius:8px;box-shadow:0 0 0 3px rgba(232,89,12,.18);`;
            layer.appendChild(box);
        }
        const size = 26;
        const spots = {
            tl: [x, y], tr: [x + w, y], bl: [x, y + h], br: [x + w, y + h],
            l: [x, y + h / 2], r: [x + w, y + h / 2], t: [x + w / 2, y], b: [x + w / 2, y + h],
        };
        let [cx, cy] = spots[m.at];
        cx += m.dx; cy += m.dy;
        cx = Math.min(Math.max(cx, size / 2 + 2), window.innerWidth - size / 2 - 2);
        cy = Math.min(Math.max(cy, size / 2 + 2), window.innerHeight - size / 2 - 2);
        const badge = document.createElement('div');
        badge.textContent = m.label;
        badge.style.cssText = `position:absolute;left:${cx - size / 2}px;top:${cy - size / 2}px;` +
            `width:${size}px;height:${size}px;border-radius:50%;background:${accent};color:#fff;` +
            `font:700 14px/26px system-ui,-apple-system,"Segoe UI",sans-serif;text-align:center;` +
            `border:2px solid #fff;box-sizing:content-box;box-shadow:0 2px 6px rgba(0,0,0,.35);`;
        layer.appendChild(badge);
    }
    document.body.appendChild(layer);
}
"""


class Mark:
    """One numbered marker: what it points at and where its badge sits on that target.

    ``target`` is a selector, a locator, a box (``{x, y, width, height}``), or a list of them
    outlined together as one.
    """

    def __init__(self, target, label, at="tl", pad=4, outline=True, dx=0, dy=0, nth=0):
        self.target, self.label, self.at = target, str(label), at
        self.pad, self.outline, self.dx, self.dy, self.nth = pad, outline, dx, dy, nth


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except urllib.error.HTTPError:
            return  # the server answers, even if with a redirect to the login page
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    raise RuntimeError(f"IvoryOS did not start at {url}")


def launch_server(workdir):
    port = free_port()
    launcher = workdir / "launch_example.py"
    launcher.write_text(LAUNCHER.format(example=str(EXAMPLE_DIR), port=port), encoding="utf-8")
    log = open(workdir / "server.log", "w", encoding="utf-8")
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    env.pop("IVORYOS_ACTIVE", None)
    proc = subprocess.Popen([sys.executable, str(launcher)], cwd=workdir, stdout=log,
                            stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{port}/ivoryos"
    try:
        wait_for(base + "/")
    except RuntimeError:
        proc.kill()
        print((workdir / "server.log").read_text(encoding="utf-8"))
        raise
    return proc, base


def cdn_router(mirror):
    def handle(route):
        url = route.request.url.split("?")[0].split("#")[0]
        rel = CDN_FILES.get(url)
        if rel is None:
            match = NPM_CDN.match(url)
            rel = f"{match.group(1)}/{match.group(2)}" if match else None
        path = mirror / rel if rel else None
        if path and path.is_file():
            return route.fulfill(path=str(path), headers={
                "Content-Type": CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
                "Access-Control-Allow-Origin": "*",
            })
        print(f"  [cdn-mirror] not mirrored, skipped: {url}")
        return route.abort()
    return handle


class Capture:
    def __init__(self, page, base, out_dir, only):
        self.page, self.base, self.out_dir, self.only = page, base, out_dir, only
        self.taken = []

    def go(self, path, wait=600):
        self.page.goto(self.base + path, wait_until="networkidle")
        self.page.wait_for_timeout(wait)

    def locate(self, target, nth=0):
        loc = self.page.locator(target) if isinstance(target, str) else target
        return loc.nth(nth) if nth else loc.first

    def shot(self, name, marks=(), clip=None, height=None, keep_mouse=False):
        """Draw ``marks``, save ``<name>.png`` (cropped to ``clip``, a target or a box), clean up.

        The mouse is moved out of the way first, unless ``keep_mouse`` (to keep a tooltip open).
        """
        if self.only and name not in self.only:
            return
        page = self.page
        if height:
            page.set_viewport_size({"width": VIEWPORT["width"], "height": height})
            page.wait_for_timeout(300)
        if not keep_mouse:
            page.mouse.move(0, 0)
        boxes = []
        for m in marks:
            targets = m.target if isinstance(m.target, (list, tuple)) else [m.target]
            found = [t if isinstance(t, dict) else self.locate(t, m.nth).bounding_box() for t in targets]
            if None in found:
                raise RuntimeError(f"{name}: marker {m.label} target is not visible: {m.target}")
            boxes.append({"box": union(found), "label": m.label, "at": m.at, "pad": m.pad,
                          "outline": m.outline, "dx": m.dx, "dy": m.dy})
        page.evaluate(ANNOTATE_JS, {"marks": boxes, "accent": ACCENT})
        if clip is not None and not isinstance(clip, dict):
            clip = self.locate(clip).bounding_box()
        path = self.out_dir / f"{name}.png"
        page.screenshot(path=str(path), clip=clip, animations="disabled")
        page.evaluate("() => document.querySelectorAll('.ivy-doc-mark').forEach(e => e.remove())")
        if height:
            page.set_viewport_size(VIEWPORT)
        compress(path)
        self.taken.append(name)
        print(f"  saved {path.name}")


def compress(path):
    """A palette PNG is a fraction of the size and indistinguishable for UI screenshots."""
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as img:
        small = img.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    small.save(path, optimize=True)


def union(boxes):
    """The smallest box holding all of ``boxes``."""
    x0 = min(b["x"] for b in boxes)
    y0 = min(b["y"] for b in boxes)
    x1 = max(b["x"] + b["width"] for b in boxes)
    y1 = max(b["y"] + b["height"] for b in boxes)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def region(*targets_or_boxes, page, pad=24):
    """A clip box around several targets, ``pad`` pixels outside them, kept inside the viewport."""
    box = union([t if isinstance(t, dict) else (page.locator(t) if isinstance(t, str) else t).first.bounding_box()
                 for t in targets_or_boxes])
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]
    x0, y0 = max(box["x"] - pad, 0), max(box["y"] - pad, 0)
    x1 = min(box["x"] + box["width"] + pad, vw)
    y1 = min(box["y"] + box["height"] + pad, vh)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


# ---------------------------------------------------------------------------------------------
# UI steps, done the way a user does them
# ---------------------------------------------------------------------------------------------

def login(page, base):
    page.goto(base + "/auth/login", wait_until="networkidle")
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", "admin")
    with page.expect_navigation():
        page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")


def toolbox_form(page, instrument, action):
    """Open ``action`` in the designer toolbox (unfolding its group) and return its form."""
    group = page.locator(f"#toolbox-{instrument.replace('.', '-')}")
    if group.get_attribute("hidden") is not None:
        page.locator(f".toolbox-divider[data-group='{instrument}']").click()
    toggle = group.locator(f".toolbox-action-toggle[data-action='{action}']")
    if toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    return group.locator(f".toolbox-action:has(.toolbox-action-toggle[data-action='{action}']) form")


def fill_action(page, instrument, action, values=None, save_as=None):
    form = toolbox_form(page, instrument, action)
    for name, value in (values or {}).items():
        form.locator(f"[name='{name}']").fill(str(value))
    if save_as:
        form.locator("[name='return']").fill(save_as)
    return form


def add_action(page, instrument, action, values=None, save_as=None):
    form = fill_action(page, instrument, action, values, save_as)
    with page.expect_response(lambda r: "/draft/instruments/" in r.url):
        form.locator("button[type=submit]").click()
    page.wait_for_timeout(400)


def set_phase(page, phase):
    label = {"prep": "Prep", "script": "Experiment", "cleanup": "Clean up"}[phase]
    page.locator(".nav-tabs .nav-link", has_text=label).click()
    page.wait_for_timeout(600)


def save_workflow_as(page, name, description):
    page.locator("button", has_text="Save As").click()
    page.wait_for_selector("#saveasModal.show")
    page.fill("#saveasModal #run_name", name)
    page.fill("#saveasModal #description", description)
    with page.expect_navigation():
        page.locator("#saveasModal button[type=submit]").click()
    page.wait_for_load_state("networkidle")


def new_workflow(page):
    page.locator("button", has_text="New").first.click()
    page.wait_for_selector("#newScriptModal.show")
    page.locator("#newScriptModal button", has_text="clear all").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)


def fill_config_table(page, rows):
    page.once("dialog", lambda d: d.accept())  # "clear all rows?"
    page.locator("#tab2 button", has_text="Clear").click()
    page.wait_for_timeout(300)
    while page.locator("#tableBody tr").count() < len(rows):
        page.locator("#tab2 button", has_text="Add Row").click()
    for i, values in enumerate(rows):
        cells = page.locator("#tableBody tr").nth(i).locator("input[type=text]")
        for j, value in enumerate(values):
            cells.nth(j).fill(str(value))


def drag_resizer(page, y):
    """Drag the bar between the run setup and the monitor, as a user does to see more of a run."""
    bar = page.locator("#resizer").bounding_box()
    x = bar["x"] + bar["width"] / 2
    page.mouse.move(x, bar["y"] + bar["height"] / 2)
    page.mouse.down()
    page.mouse.move(x, y, steps=8)
    page.mouse.up()


def wait_until_idle(page, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if page.locator("#global-status-icon").inner_text().strip() == "Idle":
            return
        page.wait_for_timeout(1000)
    raise RuntimeError("the run did not finish in time")


def nav(page, label):
    return page.locator("#navbarSupportedContent .nav-link", has_text=label).first


# The workflow the docs are built around: the abstract SDL doses a solid and a solvent,
# equilibrates, and measures purity. #amount_mg, #volume_ml and #temp_c are run inputs.
WORKFLOW = "solubility_screen"
WORKFLOW_DESCRIPTION = "Dose a solid and a solvent, equilibrate, then measure purity."
SCREEN_ROWS = [(10, 1.0, 25), (10, 2.0, 40), (20, 2.0, 60)]
FOLLOW_UP_ROWS = [(5, 1.0, 30), (15, 1.5, 50)]

# A workflow saved against an older version of the deck: dose_solid took a ``bring_in`` flag,
# solvent names were plain strings, and analyze() was spelled analyse().
LEGACY_WORKFLOW = {
    "name": "legacy_screen", "deck": "abstract_sdl", "author": "admin", "status": "editing",
    "editing_type": "script", "description": "Saved before the deck changed.",
    "script_dict": {"prep": [], "cleanup": [], "script": [
        {"id": 1, "uuid": 101, "instrument": "deck.sdl", "action": "dose_solid", "return": "",
         "args": {"amount_in_mg": 5.0, "bring_in": True},
         "arg_types": {"amount_in_mg": "float", "bring_in": "bool"}},
        {"id": 2, "uuid": 102, "instrument": "deck.sdl", "action": "dose_solvent", "return": "",
         "args": {"solvent_name": "Methanol", "amount_in_ml": 1.0, "rate_ml_per_minute": 1.0},
         "arg_types": {"solvent_name": "str", "amount_in_ml": "float", "rate_ml_per_minute": "float"}},
        {"id": 3, "uuid": 103, "instrument": "deck.sdl", "action": "analyse", "return": "purity",
         "args": {"param_1": 1, "param_2": 2}, "arg_types": {"param_1": "int", "param_2": "int"}},
    ]},
}


# ---------------------------------------------------------------------------------------------
# The screenshots, page by page. Marker numbers are explained in the docs page named on each.
# ---------------------------------------------------------------------------------------------

def instruments(cap):
    """users/instruments.md"""
    page = cap.page
    cap.go("/instruments/deck.sdl")
    card = page.locator(".draggable-method-card#analyze")
    cap.shot("instruments-overview", [
        Mark("nav .list-group", 1, at="tl"),
        Mark("#methodSearch", 2, at="tl"),
        Mark(card, 3, at="bl", pad=6),
        Mark(card.locator(".guard-shield").first, 4, at="r", pad=2, dx=18),
        Mark(card.locator(".bi-info-circle").first, 5, at="r", pad=3, dx=18),
        Mark(card.locator(".bi-eye-slash-fill").first, 6, at="l", pad=3, dx=-18),
        Mark("text=Hidden functions", 7, at="l", pad=8),
        Mark("nav .mb-4:has(a:has-text('Download proxy'))", 8, at="tl"),
        Mark("[data-bs-target='#consoleOffcanvas']", 9, at="tl", pad=2),
    ])

    # call a method from its card
    analyze = page.locator(".draggable-method-card#analyze")
    analyze.locator("input[name=param_1]").fill("1")
    analyze.locator("input[name=param_2]").fill("2")
    analyze.locator("button[type=submit]").click()
    flash = page.locator(".alert", has_text="Run Success").first
    flash.wait_for()
    page.wait_for_timeout(300)
    cap.shot("instruments-call", [
        Mark(analyze.locator(".input-group").first, 1, at="tl"),
        Mark(analyze.locator("button[type=submit]"), 2, at="tl"),
        Mark(flash, 3, at="tl"),
    ], clip=region(flash, analyze, page=page))

    # a safety limit on the equilibrate temperature
    equilibrate = page.locator(".draggable-method-card#equilibrate")
    equilibrate.locator(".guard-shield[data-param='temp']").click()
    editor = page.locator(".guard-editor")
    editor.wait_for()
    inputs = editor.locator("input")
    inputs.nth(0).fill("20")
    inputs.nth(1).fill("80")
    inputs.nth(2).fill("°C")
    page.locator("body").click(position={"x": 5, "y": 300})  # out of the field, the editor stays
    cap.shot("instruments-safety-limit", [
        Mark(equilibrate.locator(".guard-shield[data-param='temp']"), 1, at="tr", pad=2),
        Mark(editor.locator(".row").first, 2, at="tl"),
        Mark(editor.locator("button", has_text="Save"), 3, at="br", pad=3),
    ], clip=region(equilibrate, page=page))
    editor.locator("button", has_text="Save").click()
    page.wait_for_timeout(600)

    # a call outside the limit is refused before it reaches the instrument
    equilibrate.locator("input[name=temp]").fill("120")
    equilibrate.locator("input[name=duration]").fill("5")
    equilibrate.locator("button[type=submit]").click()
    flash = page.locator(".alert", has_text="Safety guard").first
    flash.wait_for()
    page.wait_for_timeout(300)
    cap.shot("instruments-limit-blocked", [
        Mark(flash, 1, at="tl"),
        Mark(equilibrate.locator(".guard-shield.is-set"), 2, at="tr", pad=2),
    ], clip=region(flash, equilibrate, page=page))

    # the Python console
    page.locator("[data-bs-target='#consoleOffcanvas']").click()
    page.wait_for_selector("#consoleOffcanvas.show")
    page.wait_for_timeout(500)
    page.keyboard.type("result = sdl.analyze(param_1=1, param_2=2)\nprint(f'purity: {result:.3f}')")
    page.locator("#consoleExecuteBtn").click()
    page.wait_for_function("document.getElementById('consoleOutput').textContent.includes('purity')")
    console = page.locator("#consoleOffcanvas")
    output = page.locator("#consoleOutput").bounding_box()
    output_top = dict(output, height=110)
    cap.shot("instruments-console", [
        Mark(console.locator(".CodeMirror"), 1, at="tl"),
        Mark("#consoleExecuteBtn", 2, at="tl"),
        Mark(output_top, 3, at="tl"),
    ], clip=region(console.locator(".offcanvas-body label").first, output_top, page=page))
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


def designer(cap):
    """users/workflow-designer.md"""
    page = cap.page
    cap.go("/draft")

    # the flow control group, unfolded
    page.locator(".toolbox-divider[data-group='flow_control']").click()
    page.wait_for_timeout(300)
    cap.shot("design-flow-control", [], clip=region(".toolbox-tools", "#toolbox-flow_control", page=page, pad=8))
    page.locator(".toolbox-divider[data-group='flow_control']").click()

    add_action(page, "deck.sdl", "dose_solid", {"amount_in_mg": "#amount_mg"})
    add_action(page, "deck.sdl", "dose_solvent", {"solvent_name": "Methanol", "amount_in_ml": "#volume_ml"})
    form = fill_action(page, "deck.sdl", "equilibrate", {"temp": "#temp_c", "duration": "10"})
    form.locator("[name='temp']").focus()
    cap.shot("design-add-action", [
        Mark(".toolbox-search", 1, at="tl", pad=2),
        Mark("#autoFillToggle", 2, at="t", pad=2),
        Mark(".toolbox-divider[data-group='deck.sdl']", 3, at="l", pad=2, dx=-16),
        Mark(form.locator("[name='temp']"), 4, at="tr", pad=3),
        Mark(form.locator("[name='return']"), 5, at="tr", pad=3),
        Mark(form.locator("button[type=submit]"), 6, at="br", pad=3),
        Mark("#list li", 7, at="tl", pad=4),
    ])
    with page.expect_response(lambda r: "/draft/instruments/" in r.url):
        form.locator("button[type=submit]").click()
    page.wait_for_timeout(400)
    add_action(page, "deck.sdl", "analyze", {"param_1": "1", "param_2": "2"}, save_as="purity")
    set_phase(page, "prep")
    add_action(page, "deck.balance", "weigh_sample", save_as="tare_g")
    set_phase(page, "cleanup")
    add_action(page, "deck.pump", "dose_liquid", {"amount_in_ml": "2", "rate_ml_per_minute": "5"})
    set_phase(page, "script")
    save_workflow_as(page, WORKFLOW, WORKFLOW_DESCRIPTION)

    cap.go("/draft")  # without the "saved" notice
    steps = page.locator("#list li")
    cap.shot("design-overview", [
        Mark(".toolbox", 1, at="tl", pad=6),
        Mark(".nav-tabs:has(.nav-link:text('Prep'))", 2, at="tl"),
        Mark(steps.nth(0).locator("a"), 3, at="tl", pad=3),
        Mark([steps.nth(0).locator("button").first, steps.nth(0).locator("button").last], 4, at="tr", pad=3),
        Mark(["button:has-text('New')", "button:has-text('Save As')"], 5, at="tl"),
        Mark(".draft-history-controls", 6, at="tl"),
        Mark("button:has-text('More')", 7, at="tr"),
        Mark(".form-switch:has(#showPythonCodeSwitch)", 8, at="tl"),
        Mark(["a:has-text('Quick Save')", "a:has-text('Prepare Run')"], 9, at="tr"),
    ])

    page.locator("#draftHistoryButton").click()
    menu = page.locator("#draftHistoryMenu")
    menu.wait_for()
    page.wait_for_timeout(500)
    cap.shot("design-history", [
        Mark("#draftUndoButton", 1, at="tl", pad=2),
        Mark("#draftRedoButton", 2, at="t", pad=2),
        Mark("#draftHistoryButton", 3, at="tr", pad=2),
        Mark(menu.locator("li").nth(1), 4, at="l", pad=0),
    ], clip=region(".draft-history-controls", menu, "button:has-text('New')", page=page, pad=24))
    page.keyboard.press("Escape")

    page.locator("#showPythonCodeSwitch").check()
    page.wait_for_function("document.getElementById('python-code').textContent.includes('def ')")
    page.wait_for_timeout(500)
    cap.shot("design-code-preview", [
        Mark(".form-switch:has(#showPythonCodeSwitch)", 1, at="tl"),
        Mark(".mode-toggle[data-mode='single']", 2, at="tl"),
        Mark("#python-code", 3, at="tl"),
        Mark("#copy-code", 4, at="bl"),
    ])
    page.locator("#showPythonCodeSwitch").uncheck()
    page.wait_for_timeout(500)


def execution(cap):
    """users/execution.md and users/run-behavior.md"""
    page = cap.page
    cap.go("/executions/config")
    fill_config_table(page, SCREEN_ROWS)
    page.fill("#display_name_config", "methanol_screen")
    page.locator("#display_name_config").blur()
    cap.shot("execute-config", [
        Mark("#myTabs", 1, at="tl"),
        Mark(".card:has(#filenameSelect)", 2, at="tl"),
        Mark("#dataInputTable thead", 3, at="tl"),
        Mark("#tableBody tr >> nth=1", 4, at="l"),
        Mark("#tab2 button:has-text('Add Row')", 5, at="bl"),
        Mark("#display_name_config", 6, at="tl"),
        Mark("#tab2 #batch_size", 7, at="tl"),
        Mark("#tab2 button:has-text('Run')", 8, at="tl"),
    ], clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": 730})

    # start it, then queue a second run behind it
    page.locator("#tab2 button:has-text('Run')").first.click()
    page.wait_for_timeout(1500)
    cap.go("/executions/config")
    fill_config_table(page, FOLLOW_UP_ROWS)
    page.fill("#display_name_config", "follow_up_screen")
    page.locator("#tab2 button:has-text('Run')").first.click()
    page.wait_for_selector("#taskNameModal.show")
    page.fill("#queueTaskName", "follow_up_screen")
    page.wait_for_timeout(300)
    modal = page.locator("#taskNameModal .modal-content")
    cap.shot("execute-queue-name", [
        Mark("#queueTaskName", 1, at="tl"),
        Mark("#confirmQueueBtn", 2, at="br"),
    ], clip=region(modal, page=page, pad=16))
    page.locator("#confirmQueueBtn").click()
    page.wait_for_timeout(800)

    cap.go("/executions/config")
    drag_resizer(page, 200)
    page.wait_for_selector("#code-panel .executing-step", timeout=15000)
    page.wait_for_function("document.getElementById('iteration-display').textContent.includes('Iteration')")
    page.wait_for_timeout(1200)
    cap.shot("execute-running", [
        Mark("#code-panel", 1, at="tl", pad=2),
        Mark("#iteration-display", 2, at="r", pad=3, dx=16),
        Mark("#view-current-config", 3, at="tl", pad=2),
        Mark("#pause-resume", 4, at="t", pad=2),
        Mark("#abort-current", 5, at="t", pad=2),
        Mark("#abort-pending", 6, at="tr", pad=2),
        Mark(".progress:has(#progress-bar-inner)", 7, at="l", pad=3),
        Mark("#logging-panel", 8, at="tl", pad=2),
        Mark("#global-status-icon", 9, at="tr", pad=2),
    ])

    page.locator("#queue-tab").click()
    page.wait_for_timeout(600)
    task = page.locator("#queue-list .list-group-item").first
    cap.shot("execute-queue", [
        Mark(task.locator("div").first, 1, at="tl"),
        Mark(task.locator("button[title='Edit']"), 2, at="b", pad=2),
        Mark([task.locator("button:has(.bi-arrow-up)"), task.locator("button:has(.bi-arrow-down)")], 3, at="b", pad=2),
        Mark(task.locator("button:has(.bi-trash)"), 4, at="b", pad=2),
    ], clip=region(".logging-panel h5", "#queue-list", page=page))

    page.locator("#view-current-config").click()
    table_modal = page.locator(".modal.show .modal-content").first
    table_modal.wait_for()
    page.wait_for_timeout(800)
    rows = table_modal.locator("tbody tr")
    cap.shot("execute-edit-running", [
        Mark(table_modal.locator(".progress").first.locator(".."), 1, at="tl"),
        Mark(rows.nth(0).locator("td").nth(1), 2, at="tl", pad=2),
        Mark(rows.nth(2).locator("input").first, 3, at="tr", pad=2),
        Mark(rows.nth(2).locator("button").last, 4, at="tr", pad=2),
        Mark(table_modal.locator("button", has_text="Add entry"), 5, at="bl"),
    ], clip=region(table_modal, page=page, pad=16))
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    page.locator("#abort-current").click()
    stop = page.locator("#stopWorkflowModal .modal-content")
    stop.wait_for()
    page.wait_for_timeout(500)
    cap.shot("execute-stop", [
        Mark(".form-check:has(#stopCleanupCheckbox)", 1, at="r"),
        Mark(".form-check:has(#continueQueueCheckbox)", 2, at="r"),
    ], clip=region(stop, page=page, pad=16))
    page.locator("#stopWorkflowModal button", has_text="Cancel").click()
    page.wait_for_timeout(500)

    wait_until_idle(page)  # the first run
    page.wait_for_timeout(3000)
    wait_until_idle(page)  # and the queued one after it


def data(cap):
    """users/data.md"""
    page = cap.page
    cap.go("/executions/records")
    row = page.locator("tbody tr").first
    cap.shot("data-runs", [
        Mark("#keyword", 1, at="tl"),
        Mark(row.locator("td").nth(0), 2, at="tl"),
        Mark("th:has-text('Submitted By')", 3, at="t"),
        Mark(row.locator("a, button", has_text="Download CSV"), 4, at="tl"),
        Mark(row.locator("a, button", has_text="View Logs"), 5, at="tl"),
    ], height=600)

    page.locator("tbody tr a", has_text="methanol_screen").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    cap.shot("data-run-overview", [
        Mark("h1", 1, at="tl"),
        Mark("#run-submitted-by", 2, at="l"),
        Mark("#visualization", 3, at="tl"),
        Mark("#config-results table", 4, at="tl"),
    ])
    page.select_option("#output-select", "purity")
    page.wait_for_timeout(800)
    downloads = [page.locator("a, button", has_text=label).first
                 for label in ("Download workflow data", "Download workflow steps", "Download logs")]
    downloads[0].scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -420)")
    page.wait_for_timeout(600)
    cap.shot("data-run-steps", [
        Mark("#output-select", 1, at="tl"),
        Mark("#phase-plot", 2, at="tl"),
        Mark(downloads, 3, at="tl"),
    ])


def library(cap):
    """users/library.md"""
    page = cap.page
    cap.go("/library/")
    row = page.locator("tbody tr").first
    cap.shot("library", [
        Mark("button:has-text('Deck:')", 1, at="tl"),
        Mark("input[placeholder^='Search']", 2, at="tl"),
        Mark(row.locator("td").nth(0), 3, at="tl"),
        Mark(row.locator("td").nth(3), 4, at="t"),
        Mark(row.locator("a, button", has_text="Open"), 5, at="tl"),
    ], height=560)


def home(cap):
    """users/using-the-ui.md"""
    page = cap.page
    cap.go("/")
    cap.shot("ui-tour", [
        Mark(nav(page, "Library"), 1, at="t"),
        Mark(nav(page, "Workflow"), 2, at="t"),
        Mark(nav(page, "Execution"), 3, at="t"),
        Mark(nav(page, "Data"), 4, at="t"),
        Mark(nav(page, "Instruments"), 5, at="t"),
        Mark(".navbar-nav.ms-auto .dropdown-toggle", 6, at="tl"),
        Mark("#global-status-icon", 7, at="tr", pad=2),
        Mark("#tipsButton, button:has-text('Workflow tips')", 8, at="tl"),
    ], height=720)


def errors(cap):
    """users/run-behavior.md: a step that fails and is retried"""
    page = cap.page
    cap.go("/draft")
    new_workflow(page)
    add_action(page, "deck.sdl", "dose_solid", {"amount_in_mg": "5"})
    add_action(page, "deck.sdl", "simulate_error")
    add_action(page, "deck.sdl", "analyze", {"param_1": "1", "param_2": "2"}, save_as="purity")
    save_workflow_as(page, "error_demo", "simulate_error fails twice, then succeeds.")
    cap.go("/executions/config")
    page.fill("#display_name_repeat", "error_demo")
    page.fill("#tab1 #repeat", "1")
    cap.shot("execute-repeat", [
        Mark("#display_name_repeat", 1, at="tl"),
        Mark("#tab1 #batch_size", 2, at="tl"),
        Mark("#tab1 #repeat", 3, at="tl"),
        Mark("#tab1 button:has-text('Run')", 4, at="tl"),
    ], clip={"x": 60, "y": 90, "width": 1320, "height": 430})
    page.locator("#tab1 button:has-text('Run')").first.click()
    page.wait_for_selector("#error-modal.show", timeout=30000)
    page.wait_for_timeout(800)
    cap.shot("execute-error", [
        Mark("#error-message", 1, at="tl"),
        Mark("#retry-btn", 2, at="bl"),
        Mark("#continue-btn", 3, at="b"),
        Mark("#stop-btn", 4, at="br"),
        Mark("#global-status-icon", 5, at="tr", pad=2),
    ])
    # simulate_error succeeds on its third call
    for _ in range(3):
        if not page.locator("#error-modal.show").count():
            break
        page.locator("#retry-btn").click()
        page.wait_for_timeout(2500)
    wait_until_idle(page)


def step_warnings(cap, workdir):
    """users/deck-compatibility.md"""
    page = cap.page
    path = workdir / "legacy_screen.json"
    path.write_text(json.dumps(LEGACY_WORKFLOW), encoding="utf-8")
    cap.go("/draft")
    page.locator("button", has_text="More").click()
    page.locator(".dropdown-item", has_text="Import").first.click()
    page.wait_for_selector("#jsonModal.show")
    page.locator("#jsonModal input[type=file]").set_input_files(str(path))
    with page.expect_navigation():
        page.locator("#jsonModal button[type=submit]").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    markers = page.locator(".step-issue-marker:not(.invisible)")
    markers.nth(2).hover()
    page.locator(".tooltip.show").wait_for()
    page.wait_for_timeout(400)
    cap.shot("design-step-warnings", [
        Mark("#deck-compatibility-banner", 1, at="tl"),
        Mark(markers.nth(0), 2, at="l", pad=3, dx=-16),
        Mark(markers.nth(1), 3, at="l", pad=3, dx=-16),
        Mark(".tooltip.show", 4, at="br", pad=3),
    ], clip={"x": 200, "y": 90, "width": 1190, "height": 400}, keep_mouse=True)

    page.mouse.move(0, 0)
    page.locator("#list li a").nth(2).click()
    modal = page.locator("#editStepModal .modal-content")
    modal.wait_for()
    page.wait_for_timeout(600)
    cap.shot("design-step-warning-edit", [
        Mark(modal.locator(".alert").first, 1, at="tl"),
    ], clip=region(modal, page=page, pad=16))
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    cap.go("/executions/config")
    warning = page.locator("#run-compatibility-warning")
    cap.shot("execute-step-warnings", [Mark(warning, 1, at="tl")], clip=region(warning, page=page, pad=16))


def optimizer(cap):
    """users/execution.md; needs an optimizer package (ax-platform, baybe or nimo) installed"""
    page = cap.page
    cap.go("/library/")
    page.locator("tbody tr", has_text=WORKFLOW).locator("a, button", has_text="Open").first.click()
    page.wait_for_load_state("networkidle")
    cap.go("/executions/config")
    page.locator("#tab3-tab").click()
    page.wait_for_timeout(600)
    strategies = [v for v in page.locator("#optimizer_type option").evaluate_all(
        "options => options.map(o => o.value)") if v]
    if not strategies:
        print("  no optimizer installed, skipped execute-optimizer")
        return
    page.select_option("#optimizer_type", strategies[0])
    page.wait_for_timeout(1000)
    for name, low, high in [("amount_mg", 5, 20), ("volume_ml", 0.5, 2), ("temp_c", 20, 80)]:
        page.select_option(f"#{name}_type", "range")
        page.fill(f"#{name}_min", str(low))
        page.fill(f"#{name}_max", str(high))
    page.select_option("#purity_obj_min", "maximize")
    page.fill("#display_name_bo", "purity_optimization")
    page.fill("#tab3 #repeat", "10")
    page.mouse.click(5, 300)
    cap.shot("execute-optimizer", [
        Mark("#tab3 .card.shadow-sm:has(#existing_data)", 1, at="tl"),
        Mark("#tab3 .card.shadow-sm:has(#display_name_bo)", 2, at="tl"),
        Mark("#optimizer_type", 3, at="tl"),
        Mark("#parameters_container", 4, at="tl"),
        Mark("#purity_obj_min", 5, at="tl"),
        Mark("#tab3 button[name=bo]", 6, at="r", dx=16),
    ], clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": 730})


SCENES = ["instruments", "designer", "execution", "errors", "data", "library", "home", "step_warnings", "optimizer"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", help="an IvoryOS server already running the abstract SDL example")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="where to write the PNGs")
    parser.add_argument("--only", default="", help="comma-separated screenshot names to save")
    parser.add_argument("--cdn-mirror", type=Path, help="node_modules folder to serve CDN files from")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    only = {name.strip() for name in args.only.split(",") if name.strip()}
    workdir = Path(tempfile.mkdtemp(prefix="ivoryos-screenshots-"))
    proc = None
    try:
        if args.base_url:
            base = args.base_url.rstrip("/")
        else:
            proc, base = launch_server(workdir)
            print(f"IvoryOS started at {base} in {workdir}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE)
            if args.cdn_mirror:
                context.route(re.compile(r"^https://"), cdn_router(args.cdn_mirror))
            page = context.new_page()
            page.set_default_timeout(20000)
            page.on("pageerror", lambda e: print(f"  [page error] {e}"))
            login(page, base)
            cap = Capture(page, base, args.out, only)
            for scene in SCENES:
                print(f"{scene}:")
                func = globals()[scene]
                func(cap, workdir) if scene == "step_warnings" else func(cap)
            browser.close()
        print(f"{len(cap.taken)} screenshots written to {args.out}")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
