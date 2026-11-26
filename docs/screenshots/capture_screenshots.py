"""Capture the annotated UI screenshots used by the user docs.

The script launches the abstract SDL example
(``community/examples/abstract_sdl_example/abstract_sdl.py``) in a fresh temporary folder,
drives the browser UI with Playwright the way a user would (build a workflow, run it, review
the data), labels the parts each page of the docs talks about, and writes the PNGs to
``docs/source/_static/screenshots/``.

Each labelled part gets a soft outline and a numbered card linked to it (a curved arrow, or a
straight line to a dot where there is little room); the rest of the page is dimmed. The card names the part, with a short hint where one helps; the numbered
list under the image in the docs page explains it in full. The labels of each image are set in
the scene functions below, next to the docs page they belong to, so when one changes, update
both.

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

# The look of the labels: a half see-through white card (55% opaque, with a light blur behind it)
# with dark text, an orange number, an orange link, and a soft orange outline round the part it
# points at. Over the dimmed page it comes out a light grey a little brighter than the page, and
# the page shows through it, so it reads as a note laid over the page rather than one more white
# panel of the UI. The blur is kept light (2px) on purpose: a heavier one smooths what is behind
# into one flat tone and the card looks solid, while 2px still softens text behind it enough not
# to compete with the card's own. Manrope comes from Google Fonts; without a connection (or with
# --cdn-mirror) the cards fall back to the system font.
CALLOUT_FONTS = "https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800&display=swap"
CALLOUT_FACES = ["700 17px Manrope", "500 14px Manrope", "800 14px Manrope"]
ACCENT = "#e3832b"
DIM = ("#0e1a24", 0.42)  # the colour and opacity laid over everything that is not labelled
CARD_MARGIN = 12  # clear space kept between a card and the edge of a cropped screenshot
SHORT_LINK = 72  # a link shorter than this (in pixels) is a straight line to a dot, not a curved arrow

CALLOUT_CSS = """
.ivy-callouts .ivy-card {
    position: absolute; display: flex; align-items: center; gap: 10px; white-space: nowrap;
    box-sizing: border-box; padding: 8px 20px 9px 8px; background: rgba(255, 255, 255, .55);
    color: #16242f;
    -webkit-backdrop-filter: blur(2px) saturate(1.2); backdrop-filter: blur(2px) saturate(1.2);
    border: 1px solid rgba(255, 255, 255, .65); border-radius: 14px;
    box-shadow: 0 12px 28px -12px rgba(8, 18, 28, .45), 0 2px 6px rgba(8, 18, 28, .14);
    -webkit-font-smoothing: antialiased;
}
.ivy-callouts .ivy-num {
    flex: none; display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; border-radius: 50%; background: @accent; color: #fff;
    font: 800 14px/1 Manrope, "Segoe UI", system-ui, sans-serif;
}
.ivy-callouts .ivy-text { display: flex; flex-direction: column; }
.ivy-callouts .ivy-title { font: 700 17px/1.25 Manrope, "Segoe UI", system-ui, sans-serif; }
.ivy-callouts .ivy-sub {
    font: 500 14.5px/1.35 Manrope, "Segoe UI", system-ui, sans-serif; color: #3e4b57;
}
.ivy-callouts .ivy-inline { border-radius: 999px; padding: 5px 18px 5px 5px; }
""".replace("@accent", ACCENT)

# Draws the labels on a layer over the page: the dimming with a hole for each labelled part, a
# soft outline round it, the cards (placed off a side of their part, then moved apart where two
# would overlap), and a curved arrow from each card to its part. Fixed positioning against the
# viewport, so screenshots are taken without scrolling after it. Returns where the cards and
# outlines ended up, as [left, top, right, bottom], so the caller can check and crop to them.
CALLOUT_JS = r"""
async ({notes, dim, accent, css, fonts, faces, shortLink}) => {
    document.querySelectorAll('.ivy-callouts').forEach(e => e.remove());
    const settle = (promise, ms) => Promise.race([promise, new Promise(done => setTimeout(done, ms))]);
    if (!document.getElementById('ivy-callout-fonts')) {
        const link = document.createElement('link');
        link.id = 'ivy-callout-fonts'; link.rel = 'stylesheet'; link.href = fonts;
        await settle(new Promise(done => { link.onload = link.onerror = done; document.head.appendChild(link); }), 4000);
    }
    await settle(Promise.all(faces.map(f => document.fonts.load(f).catch(() => null))), 4000);

    const NS = 'http://www.w3.org/2000/svg';
    const W = window.innerWidth, H = window.innerHeight, EDGE = 8, APART = 12;
    const make = (tag, attrs, parent) => {
        const el = document.createElementNS(NS, tag);
        for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
        parent.appendChild(el);
        return el;
    };
    const clamp = (v, lo, hi) => lo > hi ? (lo + hi) / 2 : Math.min(Math.max(v, lo), hi);
    const root = document.createElement('div');
    root.className = 'ivy-callouts';
    root.style.cssText = 'position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
    const style = document.createElement('style');
    style.textContent = css;
    root.appendChild(style);
    document.body.appendChild(root);
    const svg = make('svg', {width: W, height: H, style: 'position:absolute;inset:0;overflow:visible'}, root);
    const defs = make('defs', {}, svg);
    const soft = make('filter', {id: 'ivy-soft', filterUnits: 'userSpaceOnUse', x: 0, y: 0, width: W, height: H}, defs);
    make('feGaussianBlur', {stdDeviation: 3}, soft);

    const rings = notes.map(n => ({x: n.box.x - n.pad, y: n.box.y - n.pad,
        w: n.box.width + 2 * n.pad, h: n.box.height + 2 * n.pad, r: n.radius}));
    if (dim) {
        const mask = make('mask', {id: 'ivy-cut', maskUnits: 'userSpaceOnUse', x: 0, y: 0, width: W, height: H}, defs);
        make('rect', {x: 0, y: 0, width: W, height: H, fill: '#fff'}, mask);
        for (const r of rings) make('rect', {x: r.x, y: r.y, width: r.w, height: r.h, rx: r.r, fill: '#000'}, mask);
        make('rect', {x: 0, y: 0, width: W, height: H, fill: dim[0], 'fill-opacity': dim[1], mask: 'url(#ivy-cut)'}, svg);
    }
    for (const r of rings) {
        const base = {x: r.x, y: r.y, width: r.w, height: r.h, rx: r.r, fill: 'none'};
        make('rect', {...base, stroke: accent, 'stroke-width': 5, 'stroke-opacity': 0.22, filter: 'url(#ivy-soft)'}, svg);
        make('rect', {...base, stroke: accent, 'stroke-width': 1.5, 'stroke-opacity': 0.85}, svg);
    }

    // the cards: off the ``side`` of their part (and of ``outside``, a dialog to keep clear of)
    const hits = (a, b, gap) => a.l < b.r + gap && b.l < a.r + gap && a.t < b.b + gap && b.t < a.b + gap;
    const cards = [];
    notes.forEach((n, i) => {
        const card = document.createElement('div');
        card.className = 'ivy-card' + (n.sub ? '' : ' ivy-inline');
        const num = document.createElement('span'), text = document.createElement('span');
        num.className = 'ivy-num'; num.textContent = n.num;
        text.className = 'ivy-text';
        for (const [cls, words] of [['ivy-title', n.title], ['ivy-sub', n.sub]]) {
            if (!words) continue;
            const line = document.createElement('span');
            line.className = cls; line.textContent = words;
            text.appendChild(line);
        }
        card.append(num, text);
        root.appendChild(card);
        const w = card.offsetWidth, h = card.offsetHeight, r = rings[i], o = n.outside;
        let x = r.x + r.w / 2 - w / 2, y = r.y + r.h / 2 - h / 2;
        if (n.side === 'r') x = Math.max(r.x + r.w, o ? o.x + o.width : -Infinity) + n.gap;
        else if (n.side === 'l') x = Math.min(r.x, o ? o.x : Infinity) - n.gap - w;
        else if (n.side === 't') y = Math.min(r.y, o ? o.y : Infinity) - n.gap - h;
        else y = Math.max(r.y + r.h, o ? o.y + o.height : -Infinity) + n.gap;
        x = clamp(x + n.dx, EDGE, W - w - EDGE);
        y = clamp(y + n.dy, EDGE, H - h - EDGE);
        const across = n.side === 'l' || n.side === 'r';
        for (let k = 0; k < 24; k++) {
            const hit = cards.find(c => hits({l: x, t: y, r: x + w, b: y + h}, c, APART));
            if (!hit) break;
            if (across) y = clamp(y + h / 2 < (hit.t + hit.b) / 2 ? hit.t - APART - h : hit.b + APART, EDGE, H - h - EDGE);
            else x = clamp(x + w / 2 < (hit.l + hit.r) / 2 ? hit.l - APART - w : hit.r + APART, EDGE, W - w - EDGE);
        }
        card.style.left = x + 'px';
        card.style.top = y + 'px';
        cards.push({l: x, t: y, r: x + w, b: y + h});
    });

    // the arrows: from the card's side facing the part to the part's side facing the card, or
    // from the card's ``frm`` side to the part's ``to`` side, to lead an arrow round something
    const pt = p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    const unit = (a, b) => { const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1; return [dx / l, dy / l]; };
    const facing = {l: 'r', r: 'l', t: 'b', b: 't'};
    notes.forEach((n, i) => {
        const c = cards[i], r = rings[i];
        const gaps = {r: c.l - (r.x + r.w), l: r.x - c.r, b: c.t - (r.y + r.h), t: r.y - c.b};
        let to = n.to || (gaps[n.side] > 0 ? n.side : Object.keys(gaps).reduce((a, b) => gaps[a] >= gaps[b] ? a : b));
        if (!n.to && gaps[to] <= 0) return;  // the card sits on its part; the caller reports it
        const frm = n.frm || to;  // the card's side, named like ``to``: where it sits from the part
        const ccx = (c.l + c.r) / 2, ccy = (c.t + c.b) / 2;
        let p1;
        if (to === 'l' || to === 'r') {
            const e = Math.min(12, r.h / 2);
            p1 = [to === 'r' ? r.x + r.w : r.x, clamp(n.at ?? ccy, r.y + e, r.y + r.h - e)];
        } else {
            const e = Math.min(14, r.w / 2);
            p1 = [clamp(n.at ?? ccx, r.x + e, r.x + r.w - e), to === 'b' ? r.y + r.h : r.y];
        }
        // the link starts just outside the card's edge: the card is see-through, so a link
        // tucked under it would show as a pale stub inside the card
        const edge = facing[frm];
        const p0 = (edge === 'l' || edge === 'r')
            ? [edge === 'l' ? c.l - 1 : c.r + 1, clamp(p1[1], c.t + Math.min(16, (c.b - c.t) / 2), c.b - Math.min(16, (c.b - c.t) / 2))]
            : [clamp(p1[0], c.l + Math.min(24, (c.r - c.l) / 2), c.r - Math.min(24, (c.r - c.l) / 2)), edge === 't' ? c.t - 1 : c.b + 1];
        const [ux, uy] = unit(p0, p1), dist = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]);
        // a short hop has no room for a curve and an arrowhead: a straight line to a dot reads
        // better there, and ``link`` picks a style outright ('arrow', 'dot' or 'dash')
        const link = n.link || (dist < shortLink ? 'dot' : 'arrow');
        let d, tan;
        if (link === 'arrow') {
            const bow = n.bend * clamp(dist * 0.14, 6, 30);
            const ctl = [(p0[0] + p1[0]) / 2 - uy * bow, (p0[1] + p1[1]) / 2 + ux * bow];
            tan = unit(ctl, p1);
            d = `M${pt(p0)} Q${pt(ctl)} ${pt([p1[0] - tan[0] * 9, p1[1] - tan[1] * 9])}`;
        } else {
            tan = [ux, uy];
            d = `M${pt(p0)} L${pt(p1)}`;
        }
        const stroke = {d, fill: 'none', 'stroke-linecap': 'round'};
        const dash = link === 'dash' ? {'stroke-dasharray': '6 5'} : {};
        make('path', {...stroke, stroke: '#fff', 'stroke-width': 5, 'stroke-opacity': 0.5}, svg);
        make('path', {...stroke, ...dash, stroke: accent, 'stroke-width': link === 'arrow' ? 2.25 : 2}, svg);
        if (link === 'arrow') {
            const nx = -tan[1], ny = tan[0];
            const a = [p1[0] - tan[0] * 12 + nx * 6.5, p1[1] - tan[1] * 12 + ny * 6.5];
            const b = [p1[0] - tan[0] * 12 - nx * 6.5, p1[1] - tan[1] * 12 - ny * 6.5];
            make('path', {d: `M${pt(p1)} L${pt(a)} L${pt(b)} Z`, fill: accent, stroke: accent,
                'stroke-width': 1.5, 'stroke-linejoin': 'round'}, svg);
        } else {
            make('circle', {cx: p1[0], cy: p1[1], r: 4.5, fill: accent, stroke: '#fff', 'stroke-width': 2}, svg);
        }
    });
    return {cards: cards.map(c => [c.l, c.t, c.r, c.b]),
            rings: rings.map(r => [r.x, r.y, r.x + r.w, r.y + r.h])};
}
"""

# The box around an element's text alone, whatever the width of the element itself
TEXT_BOX_JS = """
el => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const {x, y, width, height} = range.getBoundingClientRect();
    return {x, y, width, height};
}
"""


class Note:
    """One labelled part of the UI: a soft outline round it and a numbered card pointing at it.

    ``target`` is a selector, a locator, a box (``{x, y, width, height}``), or a list of them
    taken together. The card says ``title`` and, where the part needs it, a short ``sub`` line;
    a simple control gets the title alone. The card sits ``gap`` pixels off the ``side`` of the
    target (``l``, ``r``, ``t`` or ``b``), centred on it, then moved by ``dx`` and ``dy``. The
    arrow meets the target facing the card, or at ``at`` (a y for a side, an x for the top or
    bottom) when given; ``bend`` (1 or -1) picks which way it bows. To lead an arrow round
    something in its way, ``to`` names the side of the target it arrives at and ``frm`` the
    side of the target the card sits on, so ``to="l", frm="b"`` runs from the top of a card
    below the target up to the target's left edge. A link shorter than ``SHORT_LINK`` is a
    straight line ending in a dot and a longer one a curved arrow; ``link`` (``"dot"``,
    ``"dash"`` or ``"arrow"``) picks one where the default looks wrong. With ``text=True`` the
    target is the element's text rather than its box, for a label that runs the full width of
    its row.
    """

    def __init__(self, target, num, title, sub=None, side="r", gap=44, dx=0, dy=0, at=None, bend=1,
                 to=None, frm=None, link=None, pad=4, radius=8, nth=0, text=False):
        self.target, self.num, self.title, self.sub = target, str(num), title, sub
        self.side, self.gap, self.dx, self.dy, self.at, self.bend = side, gap, dx, dy, at, bend
        self.to, self.frm, self.link = to, frm, link
        self.pad, self.radius, self.nth, self.text = pad, radius, nth, text


def text_box(locator):
    """The box around ``locator``'s text alone, to label words and a control beside them together."""
    return locator.evaluate(TEXT_BOX_JS)


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

    def box_of(self, target, note):
        """Where ``target`` is on the page, or None when it is not visible."""
        if isinstance(target, dict):
            return target
        loc = self.locate(target, note.nth)
        box = loc.bounding_box()
        if box is not None and note.text:
            box = loc.evaluate(TEXT_BOX_JS)
        return box

    def shot(self, name, notes=(), clip=None, height=None, keep_mouse=False, modal=None):
        """Draw ``notes``, save ``<name>.png`` (cropped to ``clip``, a target or a box), clean up.

        ``modal`` is the dialog or side panel the shot is about. The page behind it is dimmed
        already, so nothing more is dimmed, and the cards of the parts inside it are put
        outside it, so the whole dialog stays readable. The crop is widened where it would cut
        off a card, so every label explained in the docs is in the picture. The mouse is moved
        out of the way first, unless ``keep_mouse`` (to keep a tooltip open).
        """
        if self.only and name not in self.only:
            return
        page = self.page
        if height:
            page.set_viewport_size({"width": VIEWPORT["width"], "height": height})
            page.wait_for_timeout(300)
        if not keep_mouse:
            page.mouse.move(0, 0)
        dialog = self.locate(modal).bounding_box() if modal is not None else None
        specs = []
        for n in notes:
            targets = n.target if isinstance(n.target, (list, tuple)) else [n.target]
            found = [self.box_of(t, n) for t in targets]
            if None in found:
                raise RuntimeError(f"{name}: label {n.num} target is not visible: {n.target}")
            box = union(found)
            specs.append({"box": box, "num": n.num, "title": n.title, "sub": n.sub, "side": n.side,
                          "gap": n.gap, "dx": n.dx, "dy": n.dy, "at": n.at, "bend": n.bend, "to": n.to,
                          "frm": n.frm, "link": n.link, "pad": n.pad,
                          "radius": n.radius, "outside": dialog if dialog and overlap(box, dialog) else None})
        if specs:
            drawn = page.evaluate(CALLOUT_JS, {"notes": specs, "dim": None if modal is not None else DIM,
                                               "accent": ACCENT, "css": CALLOUT_CSS, "fonts": CALLOUT_FONTS,
                                               "faces": CALLOUT_FACES, "shortLink": SHORT_LINK})
            check_layout(name, notes, drawn, dialog)
            cards = drawn["cards"]
        else:
            cards = []
        if clip is not None and not isinstance(clip, dict):
            clip = self.locate(clip).bounding_box()
        if clip is not None:
            widened = include_cards(clip, cards, page.viewport_size)
            if widened is not clip:
                print(f"  {name}: crop widened to {widened['width']:.0f}x{widened['height']:.0f} "
                      f"(from {clip['width']:.0f}x{clip['height']:.0f}) to keep every label in it")
                clip = widened
        path = self.out_dir / f"{name}.png"
        page.screenshot(path=str(path), clip=clip, animations="disabled")
        page.evaluate("() => document.querySelectorAll('.ivy-callouts').forEach(e => e.remove())")
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


def overlap(a, b):
    """Whether boxes ``a`` and ``b`` (``{x, y, width, height}``) share any area."""
    return (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
            and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"])


def include_cards(clip, cards, viewport):
    """``clip``, grown inside the viewport where a card would be cut off or left out of it.

    Each card keeps ``CARD_MARGIN`` pixels around it. Returns ``clip`` itself when it already
    holds them all.
    """
    edges = (clip["x"], clip["y"], clip["x"] + clip["width"], clip["y"] + clip["height"])
    x0, y0, x1, y1 = edges
    for left, top, right, bottom in cards:
        x0, y0 = min(x0, max(left - CARD_MARGIN, 0)), min(y0, max(top - CARD_MARGIN, 0))
        x1 = max(x1, min(right + CARD_MARGIN, viewport["width"]))
        y1 = max(y1, min(bottom + CARD_MARGIN, viewport["height"]))
    if (x0, y0, x1, y1) == edges:
        return clip
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def check_layout(name, notes, drawn, dialog):
    """Report a card that hides a labelled part, another card, or the dialog it is about."""
    def box(edges):
        left, top, right, bottom = edges
        return {"x": left, "y": top, "width": right - left, "height": bottom - top}
    cards, rings = [box(c) for c in drawn["cards"]], [box(r) for r in drawn["rings"]]
    for i, card in enumerate(cards):
        num = notes[i].num
        for j, ring in enumerate(rings):
            if overlap(card, ring):
                print(f"  {name}: card {num} covers the part labelled {notes[j].num}")
        for j in range(i + 1, len(cards)):
            if overlap(card, cards[j]):
                print(f"  {name}: cards {num} and {notes[j].num} overlap")
        if dialog and overlap(card, dialog):
            print(f"  {name}: card {num} covers part of the dialog")


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
# The screenshots, page by page. Label numbers are explained in the docs page named on each.
# ---------------------------------------------------------------------------------------------

def instruments(cap):
    """users/instruments.md"""
    page = cap.page
    cap.go("/instruments/deck.sdl")
    card = page.locator(".draggable-method-card#equilibrate")
    cap.shot("instruments-overview", [
        Note("nav .list-group", 1, "Instruments", "Pick one to see its methods", side="b", gap=130, dx=-35,
             to="l", frm="b", bend=-1),
        Note(card, 2, "A method", "A field per argument, then run it", side="b", gap=26, dx=-90),
        Note(card.locator(".guard-shield").nth(1), 3, "Safety limit", side="b", gap=160, dx=-10, link="dash"),
        Note(card.locator(".bi-eye-slash-fill").first, 4, "Hide", side="r", gap=12, dy=-40),
        Note("[data-bs-target='#consoleOffcanvas']", 5, "Python console", side="l", gap=28),
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
        Note(analyze.locator(".input-group").first, 1, "Arguments", side="l", gap=24),
        Note(analyze.locator("button[type=submit]"), 2, "Run it", side="b", gap=18),
        Note(flash, 3, "The result", side="b", gap=16, dx=300),
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
        Note(equilibrate.locator(".guard-shield[data-param='temp']"), 1, "Limit this field", side="t", gap=16,
             dx=-90),
        Note(editor.locator(".row").first, 2, "Min, max and unit", side="l"),
        Note(editor.locator("button", has_text="Save"), 3, "Save", side="r", gap=16),
    ], clip=region(equilibrate, page=page, pad=60))
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
        Note(flash, 1, "Call refused", "With the limit it broke", side="b", gap=30, dx=-60),
        Note(equilibrate.locator(".guard-shield.is-set"), 2, "The limit, on its shield", side="t", gap=16,
             dx=-110),
    ], clip=region(flash, equilibrate, page=page, pad=60))

    # the Python console
    page.locator("[data-bs-target='#consoleOffcanvas']").click()
    page.wait_for_selector("#consoleOffcanvas.show")
    page.wait_for_timeout(500)
    page.keyboard.type("result = sdl.analyze(param_1=1, param_2=2)\nprint(f'purity: {result:.3f}')")
    page.locator("#consoleExecuteBtn").click()
    page.wait_for_function("document.getElementById('consoleOutput').textContent.includes('purity')")
    console = page.locator("#consoleOffcanvas")
    cap.shot("instruments-console", [
        Note(console.locator(".CodeMirror"), 1, "Python code", "Instruments by name: sdl, pump…", side="l"),
        Note("#consoleExecuteBtn", 2, "Execute", side="l"),
        Note("#consoleOutput", 3, "Output", side="l", dy=-120),
    ], clip=region(console, page=page, pad=24), modal=console)
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
        Note(form.locator("[name='temp']"), 1, "A value per argument", "#name makes it a run input", side="r", gap=60),
        Note(form.locator("[name='return']"), 2, "Save value as", "Names what the action returns",
             side="r", gap=60),
        Note("#list", 3, "The steps", "Of this phase, in the order they run", side="b", gap=60, dx=220),
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
        Note(".toolbox", 1, "Toolbox", "Open an action, fill it in, click Add", side="r", gap=80, dy=60),
        Note(".nav-tabs:has(.nav-link:text('Prep'))", 2, "Phases", "Only Experiment repeats", side="r", gap=24),
        Note(steps.last.locator("a"), 3, "A step", "Click to edit, drag to reorder", side="b", gap=50),
        Note([steps.last.locator("button").first, steps.last.locator("button").last], 4,
             "Switch off, duplicate, delete", side="b", gap=80, bend=-1),
        Note(["button:has-text('New')", "button:has-text('More')"], 5, "Toolbar", side="l", gap=30),
        Note(["a:has-text('Quick Save')", "a:has-text('Prepare Run')"], 6, "Save, then run",
             "Prepare Run opens Execution", side="t", gap=70, dx=30),
    ])

    page.locator("#draftHistoryButton").click()
    menu = page.locator("#draftHistoryMenu")
    menu.wait_for()
    page.wait_for_timeout(500)
    cap.shot("design-history", [
        Note(["#draftUndoButton", "#draftRedoButton"], 1, "Undo / Redo", side="t", gap=20, dx=-60, pad=2),
        Note("#draftHistoryButton", 2, "History", side="t", gap=20, dx=60, pad=2),
        Note(menu.locator("li").nth(1), 3, "Jump to a change", "The tick marks where you are", side="l"),
    ], clip=region(".draft-history-controls", menu, "button:has-text('New')", page=page, pad=60))
    page.keyboard.press("Escape")

    page.locator("#showPythonCodeSwitch").check()
    page.wait_for_function("document.getElementById('python-code').textContent.includes('def ')")
    page.wait_for_timeout(500)
    cap.shot("design-code-preview", [
        Note("#showPythonCodeSwitch", 1, "Preview code", side="l"),
        Note([".mode-toggle[data-mode='single']", ".mode-toggle[data-mode='batch']"], 2, "Single or batch",
             side="l", dy=150),
        Note(["#copy-code", "#download-code"], 3, "Copy or download", side="l"),
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
    tabs = page.locator("#myTabs .nav-link")
    cap.shot("execute-config", [
        Note([tabs.first, tabs.last], 1, "Run options", "Greyed out if it can't be used", side="r", gap=40),
        # in the gap under Add Row, its arrow kept left of the button
        Note(".card:has(#filenameSelect)", 2, "File actions", side="r", gap=40, dy=236, bend=-1),
        Note("#dataInputTable", 3, "The table", "A column per #input, a row per run", side="b", gap=40,
             dx=250, pad=2),
        Note("#display_name_config", 4, "Experiment name", side="r", gap=260, dy=20, link="dot"),
        Note("#tab2 button:has-text('Run')", 5, "Run", "Or queue it while another runs", side="r", gap=260,
             link="dot"),
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
        Note("#queueTaskName", 1, "Name the queued run", side="l"),
        Note("#confirmQueueBtn", 2, "Add to Queue", side="r"),
    ], clip=region(modal, page=page, pad=24), modal=modal)
    page.locator("#confirmQueueBtn").click()
    page.wait_for_timeout(800)

    cap.go("/executions/config")
    drag_resizer(page, 200)
    page.wait_for_function("document.getElementById('iteration-display').textContent.includes('Iteration')")
    page.wait_for_function(
        "(document.querySelector('#code-panel .executing-step') || {}).textContent?.includes('dose_solid')",
        timeout=30000)
    page.wait_for_timeout(300)
    cap.shot("execute-running", [
        # below the code, its arrow up the margin so it crosses no line of code
        Note("#code-panel .executing-step", 1, "The step running now", side="b", gap=230, dx=-271, to="l",
             frm="b", bend=-1),
        Note("#iteration-display", 2, "Where the run is", side="t", gap=24),
        Note(["#view-current-config", "#abort-pending"], 3, "Run controls", "Edit table, pause, stop, stop pending",
             side="t", gap=20),
        Note("#logging-panel", 4, "Log", "Every step and its values", side="l"),
        Note("#global-status-icon", 5, "Status", side="r", gap=30),
    ])

    page.locator("#queue-tab").click()
    page.wait_for_timeout(600)
    task = page.locator("#queue-list .list-group-item").first
    cap.shot("execute-queue", [
        Note(task.locator("div").first, 1, "A queued run", "Name, rows, who submitted it", side="b", gap=40),
        Note([task.locator("button[title='Edit']"), task.locator("button:has(.bi-trash)")], 2,
             "Edit, move, remove", side="b", gap=40),
    ], clip=region(".logging-panel h5", "#queue-list", page=page))

    page.locator("#view-current-config").click()
    table_modal = page.locator(".modal.show .modal-content").first
    table_modal.wait_for()
    page.wait_for_timeout(800)
    rows = table_modal.locator("tbody tr")
    cap.shot("execute-edit-running", [
        Note([rows.nth(0).locator("td").nth(1), rows.nth(2).locator("td").nth(1)], 1, "Row status",
             "Finished rows are locked", side="l"),
        Note(rows.nth(2), 2, "A pending row", "Change it, or × to remove it", side="r"),
        Note(table_modal.locator("button", has_text="Add entry"), 3, "Add entry", "Save applies the changes",
             side="l"),
    ], clip=region(table_modal, page=page, pad=24), modal=table_modal)
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    page.locator("#abort-current").click()
    stop = page.locator("#stopWorkflowModal .modal-content")
    stop.wait_for()
    page.wait_for_timeout(500)
    cleanup, queue = "stopCleanupCheckbox", "continueQueueCheckbox"
    cap.shot("execute-stop", [
        Note([f"#{cleanup}", text_box(page.locator(f"label[for={cleanup}]"))], 1, "Run Clean up first",
             side="l", dy=-14),
        Note([f"#{queue}", text_box(page.locator(f"label[for={queue}]"))], 2, "Let the next queued run start",
             side="l", dy=14),
    ], clip=region(stop, page=page, pad=24), modal=stop)
    page.locator("#stopWorkflowModal button", has_text="Cancel").click()
    page.wait_for_timeout(500)

    wait_until_idle(page)  # the first run
    page.wait_for_timeout(3000)
    wait_until_idle(page)  # and the queued one after it


def data(cap):
    """users/data.md"""
    page = cap.page
    cap.go("/executions/records")
    row = page.locator("tbody tr").last  # the cards go under the table, so the last row
    cap.shot("data-runs", [
        Note("#keyword", 1, "Search", side="l"),
        Note(row.locator("td").nth(0), 2, "A run", "Click to open it", side="b", gap=24),
        Note("th:has-text('Submitted By')", 3, "Submitted By", "Click a column to sort", side="t", gap=24),
        Note(row.locator("a, button", has_text="Download CSV"), 4, "Download CSV", side="b", gap=24),
    ], height=600)

    page.locator("tbody tr a", has_text="methanol_screen").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    cap.shot("data-run-overview", [
        Note("#run-submitted-by strong", 1, "Submitted by", side="r"),
        Note("#visualization", 2, "Timeline", "Click a phase to jump to it", side="t", gap=20, dx=300),
        Note("#config-results table", 3, "Config table results", "Each row's status, values and outputs",
             side="t", gap=20, dx=300),
    ])
    page.select_option("#output-select", "purity")
    page.wait_for_timeout(800)
    downloads = [page.locator("a, button", has_text=label).first
                 for label in ("Download workflow data", "Download workflow steps", "Download logs")]
    downloads[0].scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -420)")
    page.wait_for_timeout(600)
    cap.shot("data-run-steps", [
        Note("#output-select", 1, "Value to plot", side="r"),
        Note(downloads, 2, "Downloads", "Data, steps and logs", side="r"),
    ])


def library(cap):
    """users/library.md"""
    page = cap.page
    cap.go("/library/")
    row = page.locator("tbody tr").last  # the card goes under the table, so the last row
    cap.shot("library", [
        # right of the page description, its arrow over the rule above the buttons
        Note("button:has-text('Deck:')", 1, "Deck filter", side="t", gap=20, dx=407, link="dot"),
        Note("input[placeholder^='Search']", 2, "Search", side="t", gap=20),
        Note(row.locator("a, button", has_text="Open"), 3, "Open", "Loads it into the designer", side="b",
             gap=30),
    ], height=560)


def home(cap):
    """users/using-the-ui.md"""
    page = cap.page
    cap.go("/")
    cap.shot("ui-tour", [
        Note([nav(page, "Library"), nav(page, "Instruments")], 1, "Main pages", "In the usual order of work",
             side="b", gap=40, dx=40),
        Note(".navbar-nav.ms-auto .dropdown-toggle", 2, "Account menu", side="b", gap=40),
        Note("#global-status-icon", 3, "Status", side="r", gap=30),
        Note(page.locator("a, button", has_text="Open in Editor").last, 4, "Recent workflows",
             "Open one in the designer", side="b", gap=40),
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
        Note("#tab1 #repeat", 1, "Repeat for", "Times the Experiment phase runs", side="r", gap=60),
        Note("#tab1 button:has-text('Run')", 2, "Run", side="r", gap=60),
    ], clip={"x": 60, "y": 90, "width": 1320, "height": 430})
    page.locator("#tab1 button:has-text('Run')").first.click()
    page.wait_for_selector("#error-modal.show", timeout=30000)
    page.wait_for_timeout(800)
    error_modal = page.locator("#error-modal .modal-content")
    cap.shot("execute-error", [
        Note(["#retry-btn", "#stop-btn"], 1, "What next", "Rerun the step, continue, or stop", side="b", gap=40),
        Note("#global-status-icon", 2, "Status", "Click it to bring the dialog back", side="r", gap=30),
    ], modal=error_modal)
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
        Note(markers.nth(0), 1, "Will stop the run", side="l", gap=40),
        Note(markers.nth(1), 2, "Will run, but changed", side="l", gap=40),
        Note(".tooltip.show", 3, "The reason", side="r"),
    ], clip={"x": 200, "y": 90, "width": 1190, "height": 400}, keep_mouse=True)

    page.mouse.move(0, 0)
    page.locator("#list li a").nth(2).click()
    modal = page.locator("#editStepModal .modal-content")
    modal.wait_for()
    page.wait_for_timeout(600)
    cap.shot("design-step-warning-edit", [], clip=region(modal, page=page, pad=16))
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    cap.go("/executions/config")
    warning = page.locator("#run-compatibility-warning")
    cap.shot("execute-step-warnings", [], clip=region(warning, page=page, pad=16))


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
        Note("#optimizer_type", 1, "Optimizer", side="t", gap=24),
        Note("#parameters_container", 2, "Input parameters", "A range, choices, or a fixed value", side="t",
             gap=24, dx=300),
        Note("#purity_obj_min", 3, "Objective", "Maximize or minimize", side="l"),
        Note("#tab3 button[name=bo]", 4, "Run Optimization", side="r", gap=34),
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
            # Full Chromium rather than Playwright's default headless shell: the shell leaves part
            # of a card unblurred (its backdrop-filter stops at a raster tile), so the text behind
            # it shows through sharp
            browser = p.chromium.launch(headless=not args.headed, channel="chromium")
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
