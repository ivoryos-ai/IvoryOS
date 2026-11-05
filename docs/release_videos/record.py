"""Record the "what's new" video of an IvoryOS release.

A release with something to show gets a scene script, ``scenes/v<major>_<minor>_<patch>.py``, written
from its CHANGELOG section. This script starts the dye-mixing demo lab (``dye_lab.py``) from this
checkout in a temporary folder, logs in, and plays the scene script in Chromium the way a user would,
with a visible cursor, captions and title slides, then encodes the screen recording to
``docs/release_videos/output/ivoryos-<version>.mp4`` (1920x1080), ready to upload.

Captions and slides with a ``say=`` line are narrated by a voice generated locally (``narration.py``),
and the pace follows the voice. Next to the MP4 it writes ``ivoryos-<version>.srt``, the narration as
subtitles, ``ivoryos-<version>-cover.jpg``, the YouTube cover, and ``ivoryos-<version>-youtube.txt``,
the title, description (with chapters and links) and tags to paste into YouTube; Whisper then reports
any line it hears differently from the script.

A release needs a video when it is a minor or major release (``x.y.0``) or adds a ``[New]`` entry.
A patch release of fixes and small improvements does not, and is skipped. When a release that needs
one has nothing to show (a ``[New]`` entry that is not in the UI), its scene script holds only
``SKIP = "<the reason>"``.

Usage::

    pip install -e ".[video]"
    playwright install chromium
    python docs/release_videos/record.py              # the version in ivoryos/version.py
    python docs/release_videos/record.py 1.8.0 --headed
    python docs/release_videos/record.py --check      # does it need a video, and is its scene script there?
    python docs/release_videos/record.py --tutorial getting_started   # a tutorial, tutorials/<name>.py

Options:

``--check``        print the CHANGELOG section and what it needs; exit 1 if it needs a video and has no
                   scene script. Records nothing.
``--cdn-mirror``   a ``node_modules`` folder holding the front-end libraries the UI loads from CDNs
                   (see ``docs/screenshots/capture_screenshots.py``).
``--headed``       watch the browser while it records.
``--keep``         keep the recorded frames and the server log in the temporary folder.
``--voice``        the narration's Kokoro voice, e.g. ``am_michael`` (default ``af_heart``).
``--mute``         record without narration.
``--tutorial``     record a tutorial from ``tutorials/<name>.py`` instead of a release video: a walkthrough
                   that is not tied to a release, written the same way, to
                   ``output/ivoryos-tutorial-<name>.mp4``.
"""
import argparse
import base64
import html
import importlib.util
import io
import keyword
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCENES_DIR = HERE / "scenes"
TUTORIALS_DIR = HERE / "tutorials"
OUT_DIR = HERE / "output"
sys.path.insert(0, str(REPO / "docs" / "screenshots"))

# The page is laid out at 1280x720 CSS pixels, large enough to read on a phone, and drawn at 1.5x:
# a 1920x1080 video. Chromium's screencast ignores an emulated device scale factor, so the browser
# window itself is scaled (--force-device-scale-factor) instead of Playwright's viewport.
VIEWPORT = {"width": 1280, "height": 720}
SCALE = 1.5
FPS = 30
# Pauses scale with what the viewer reads: seconds per word of a caption before the scene moves on.
READ_SECONDS_PER_WORD = 0.22
LINE_GAP = 0.35  # seconds of silence at least between two narration lines

# The demo deck, from this checkout rather than an installed ivoryos.
LAUNCHER = """
import random, sys
random.seed(7)
sys.path[:0] = [{repo!r}, {here!r}]
import dye_lab  # noqa: F401  (builds the deck: liquid_handler, plate_reader)
import ivoryos
ivoryos.run("dye_lab", port={port}, debug=False, logger="dye_lab")
"""

# Installed on every page: a cursor that follows the mouse (a headless browser draws none), a ripple
# on each click, a caption bar, highlight rings and full-screen title slides. The caption and the
# cursor position are kept in sessionStorage so they carry over when a click loads a new page.
OVERLAY_JS = r"""
(() => {
    if (window.top !== window || window.ivyVideo) return;
    const CSS = `
    #ivy-cursor{position:fixed;left:-4px;top:-2px;width:26px;height:26px;z-index:2147483647;pointer-events:none;
        display:none;transition:transform .6s cubic-bezier(.3,.7,.3,1);will-change:transform}
    #ivy-cursor svg{filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))}
    .ivy-ripple{position:fixed;width:38px;height:38px;margin:-19px 0 0 -19px;border-radius:50%;pointer-events:none;
        border:3px solid #f5a524;z-index:2147483646;animation:ivy-ripple .6s ease-out forwards}
    @keyframes ivy-ripple{from{transform:scale(.3);opacity:1}to{transform:scale(1.5);opacity:0}}
    #ivy-caption{position:fixed;left:50%;bottom:24px;transform:translate(-50%,14px);opacity:0;z-index:2147483645;
        max-width:min(1000px,88vw);pointer-events:none;background:rgba(15,23,42,.93);color:#f8fafc;border-radius:14px;
        padding:13px 22px 14px;box-shadow:0 10px 30px rgba(0,0,0,.28);transition:opacity .35s ease,transform .35s ease;
        font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
    #ivy-caption.show{opacity:1;transform:translate(-50%,0)}
    #ivy-caption.top{bottom:auto;top:82px}
    #ivy-caption .ivy-tag{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
        padding:3px 9px;border-radius:999px;margin-right:10px;vertical-align:3px;background:#2a9d8f;color:#fff}
    #ivy-caption .ivy-tag.fix{background:#d4892a}
    #ivy-caption .ivy-tag.qol{background:#5b7fbf}
    #ivy-caption .ivy-title{font-size:21px;font-weight:650}
    #ivy-caption .ivy-text{font-size:15.5px;color:#cbd5e1;margin-top:5px;line-height:1.45}
    #ivy-caption code,#ivy-slide code{font-family:ui-monospace,Consolas,monospace;font-size:.92em;color:#fde68a;
        background:rgba(148,163,184,.2);padding:1px 6px;border-radius:5px}
    .ivy-ring{position:fixed;z-index:2147483644;pointer-events:none;border:3px solid #f5a524;border-radius:10px;
        box-shadow:0 0 0 4px rgba(245,165,36,.22),0 0 22px rgba(245,165,36,.4);animation:ivy-pulse 1.4s ease-in-out infinite}
    @keyframes ivy-pulse{50%{box-shadow:0 0 0 8px rgba(245,165,36,.1),0 0 30px rgba(245,165,36,.5)}}
    .ivy-sliding #ivy-cursor{opacity:0}
    .ivy-cover #ivy-cursor,.ivy-cover #ivy-caption,.ivy-cover .ivy-ring,.ivy-cover #ivy-slide{display:none!important}
    #ivy-slide{position:fixed;inset:0;z-index:2147483646;display:flex;flex-direction:column;justify-content:center;
        padding:0 9vw;background:radial-gradient(circle at 18% 12%,#1f5560,#0f172a 72%);color:#f8fafc;opacity:0;
        transition:opacity .5s ease;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
    #ivy-slide.show{opacity:1}
    #ivy-slide .ivy-kicker{font-size:17px;letter-spacing:.16em;text-transform:uppercase;color:#7dd3c8;font-weight:700}
    #ivy-slide h1{font-size:60px;font-weight:750;margin:12px 0 12px;line-height:1.05;letter-spacing:-.01em}
    #ivy-slide .ivy-sub{font-size:23px;color:#cbd5e1;max-width:960px;line-height:1.45}
    #ivy-slide ul{margin:26px 0 0;padding:0;list-style:none;font-size:20px;line-height:1.45;color:#e2e8f0;max-width:1000px}
    #ivy-slide li{padding-left:28px;position:relative;margin:9px 0}
    #ivy-slide li::before{content:"";position:absolute;left:4px;top:.55em;width:9px;height:9px;border-radius:50%;background:#2a9d8f}
    #ivy-slide .ivy-foot{position:absolute;left:9vw;right:9vw;bottom:40px;font-size:16px;color:#94a3b8;
        display:flex;align-items:center;gap:14px}
    #ivy-slide .ivy-foot img{height:34px;border-radius:6px;background:#fff;padding:2px}
    #ivy-slide.ivy-code-slide{justify-content:flex-start;padding:30px 7vw 0}
    .ivy-code-slide h1{font-size:34px;margin:6px 0 4px}
    .ivy-editor{margin-top:16px;max-width:1120px;background:#0b1220;border-radius:14px;overflow:hidden;
        box-shadow:0 18px 50px rgba(0,0,0,.45),0 0 0 1px rgba(148,163,184,.18)}
    .ivy-tabbar{display:flex;align-items:center;gap:8px;padding:10px 16px;background:#111a2e;color:#e2e8f0;
        font:14px ui-monospace,Consolas,monospace}
    .ivy-tabbar i{width:11px;height:11px;border-radius:50%;background:#ef6b5e}
    .ivy-tabbar i:nth-child(2){background:#f4bf4f}
    .ivy-tabbar i:nth-child(3){background:#61c454;margin-right:10px}
    .ivy-code{padding:12px 0 14px;color:#e2e8f0;font:15px/1.5 ui-monospace,Consolas,"Cascadia Code",monospace}
    .ivy-line{display:flex;border-left:3px solid transparent;transition:opacity .4s ease,background .4s ease}
    .ivy-line.off{opacity:.28}
    .ivy-line.on{background:rgba(42,157,143,.17);border-left-color:#2a9d8f}
    .ivy-ln{flex:none;width:46px;padding-right:16px;text-align:right;color:#475569}
    .ivy-console .ivy-ln{width:18px;padding:0}
    #ivy-slide.ivy-console-slide{justify-content:center;padding-bottom:50px}
    .ivy-console-slide .ivy-editor{max-width:1000px}
    .ivy-console-slide .ivy-code{font-size:21px;padding:18px 0 20px}
    .ivy-src{white-space:pre}
    .ivy-note{display:inline-block;margin-left:14px;padding:0 10px;border-radius:999px;background:#f5a524;color:#111827;
        font:700 13px/1.65 system-ui,"Segoe UI",sans-serif;vertical-align:1px;animation:ivy-pop .35s ease-out}
    @keyframes ivy-pop{from{opacity:0;transform:translateX(-6px)}}
    .ivy-code .k{color:#c792ea}.ivy-code .s{color:#c3e88d}.ivy-code .c{color:#64748b;font-style:italic}
    .ivy-code .n{color:#f78c6c}.ivy-code .f{color:#82aaff}.ivy-code .t{color:#ffcb6b}.ivy-code .d{color:#89ddff}
    .ivy-code .p{color:#2dd4bf;font-weight:700}.ivy-code .o{color:#94a3b8}
    `;
    const ARROW = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2 L4 19 L8.6 14.9 L11.7 21.6 ' +
        'L14.5 20.4 L11.5 13.8 L17.7 13.8 Z" fill="#111827" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    const store = {
        get(key) { try { return JSON.parse(sessionStorage.getItem(key)); } catch (e) { return null; } },
        set(key, value) { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) {} },
    };
    const escape = text => String(text).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
    // `code` in captions and slides
    const markup = text => escape(text).replace(/`([^`]+)`/g, "<code>$1</code>");
    const el = (tag, attrs = {}, html = "") => {
        const node = document.createElement(tag);
        Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
        node.innerHTML = html;
        return node;
    };
    let cursor, caption;

    function moveCursor(x, y, glide) {
        if (!cursor) return;
        cursor.style.display = "block";
        cursor.style.transition = glide ? "" : "none";
        cursor.style.transform = `translate(${x}px, ${y}px)`;
        store.set("ivy-cursor", [x, y]);
    }

    function setup() {
        if (document.getElementById("ivy-cursor")) return;
        document.documentElement.appendChild(el("style", {id: "ivy-video-style"}, CSS));
        cursor = el("div", {id: "ivy-cursor"}, ARROW);
        caption = el("div", {id: "ivy-caption"});
        document.documentElement.append(caption, cursor);
        const at = store.get("ivy-cursor");
        if (at) moveCursor(at[0], at[1], false);
        document.addEventListener("mousemove", e => moveCursor(e.clientX, e.clientY, true), true);
        document.addEventListener("mousedown", e => {
            const ring = el("div", {class: "ivy-ripple", style: `left:${e.clientX}px;top:${e.clientY}px`});
            document.documentElement.appendChild(ring);
            setTimeout(() => ring.remove(), 700);
        }, true);
        const saved = store.get("ivy-caption");
        if (saved) window.ivyVideo.caption(saved, false);
    }

    window.ivyVideo = {
        caption(c, animate = true) {
            store.set("ivy-caption", c);
            const tag = c.tag ? `<span class="ivy-tag ${escape(c.kind || "")}">${escape(c.tag)}</span>` : "";
            caption.className = c.where === "top" ? "top" : "";
            caption.style.top = c.where === "top" && c.offset != null ? `${c.offset}px` : "";
            caption.style.bottom = c.where !== "top" && c.offset != null ? `${c.offset}px` : "";
            caption.style.left = c.center != null ? `${c.center}px` : "";
            caption.innerHTML = `<div class="ivy-title">${tag}${markup(c.title)}</div>` +
                (c.text ? `<div class="ivy-text">${markup(c.text)}</div>` : "");
            if (!animate) caption.style.transition = "none";
            requestAnimationFrame(() => requestAnimationFrame(() => {
                caption.classList.add("show");
                caption.style.transition = "";
            }));
        },
        clearCaption() {
            store.set("ivy-caption", null);
            caption.classList.remove("show");
        },
        ring(boxes, pad) {
            this.clearRings();
            boxes.forEach(b => document.documentElement.appendChild(el("div", {class: "ivy-ring",
                style: `left:${b.x - pad}px;top:${b.y - pad}px;width:${b.width + 2 * pad}px;height:${b.height + 2 * pad}px`})));
        },
        clearRings() { document.querySelectorAll(".ivy-ring").forEach(e => e.remove()); },
        slide(s) {
            this.clearSlide(true);
            const bullets = (s.bullets || []).map(b => `<li>${markup(b)}</li>`).join("");
            const node = el("div", {id: "ivy-slide"},
                (s.kicker ? `<div class="ivy-kicker">${markup(s.kicker)}</div>` : "") +
                `<h1>${markup(s.title)}</h1>` +
                (s.sub ? `<div class="ivy-sub">${markup(s.sub)}</div>` : "") +
                (bullets ? `<ul>${bullets}</ul>` : "") +
                `<div class="ivy-foot">${s.logo ? `<img src="${escape(s.logo)}" alt="">` : ""}<span>${markup(s.foot || "")}</span></div>`);
            document.documentElement.appendChild(node);
            document.documentElement.classList.add("ivy-sliding");
            if (s.instant) node.classList.add("show");
            else requestAnimationFrame(() => requestAnimationFrame(() => node.classList.add("show")));
        },
        // a code editor slide; c.lines are HTML, already escaped and highlighted
        code(c) {
            this.clearSlide(true);
            const rows = c.lines.map((line, i) => `<div class="ivy-line" data-n="${i + 1}">` +
                `<span class="ivy-ln">${c.console ? "" : i + 1}</span><span class="ivy-src">${line || " "}</span></div>`).join("");
            const node = el("div", {id: "ivy-slide", class: "ivy-code-slide" + (c.console ? " ivy-console-slide" : "")},
                (c.kicker ? `<div class="ivy-kicker">${markup(c.kicker)}</div>` : "") +
                (c.title ? `<h1>${markup(c.title)}</h1>` : "") +
                `<div class="ivy-editor${c.console ? " ivy-console" : ""}"><div class="ivy-tabbar"><i></i><i></i><i></i>` +
                `${escape(c.file || "")}</div><div class="ivy-code">${rows}</div></div>`);
            document.documentElement.appendChild(node);
            document.documentElement.classList.add("ivy-sliding");
            requestAnimationFrame(() => requestAnimationFrame(() => node.classList.add("show")));
        },
        // highlight these line numbers of the code slide and dim the others; notes label a line's end
        focus(lines, notes) {
            document.querySelectorAll("#ivy-slide .ivy-note").forEach(e => e.remove());
            document.querySelectorAll("#ivy-slide .ivy-line").forEach(row => {
                const n = Number(row.dataset.n), on = lines.includes(n);
                row.classList.toggle("on", on);
                row.classList.toggle("off", lines.length > 0 && !on);
                if (notes && notes[n]) row.querySelector(".ivy-src").insertAdjacentHTML("beforeend",
                    `<span class="ivy-note">${markup(notes[n])}</span>`);
            });
        },
        clearSlide(now = false) {
            const node = document.getElementById("ivy-slide");
            if (!node) return;
            document.documentElement.classList.remove("ivy-sliding");
            if (now) return node.remove();
            node.classList.remove("show");
            setTimeout(() => node.remove(), 600);
        },
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup);
    else setup();
})();
"""


TYPE_NAMES = {"Any", "Dict", "List", "Literal", "Optional", "Set", "Tuple", "Union",
              "bool", "bytes", "dict", "float", "int", "list", "set", "str", "tuple"}


def highlight_python(source):
    """``source`` as one HTML string per line, with the spans a code slide colors: ``k`` keyword,
    ``s`` string, ``c`` comment, ``n`` number, ``f`` name being defined, ``t`` type, ``d`` decorator."""
    lines = source.split("\n")
    out = [""] * len(lines)
    row, col = 1, 0

    def emit(text, cls=None):
        nonlocal row, col
        for i, part in enumerate(text.split("\n")):  # a docstring can span lines
            if i:
                row, col = row + 1, 0
            if part:
                out[row - 1] += f'<span class="{cls}">{html.escape(part)}</span>' if cls else html.escape(part)
                col += len(part)

    strings = {tokenize.STRING} | {getattr(tokenize, t) for t in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
                                   if hasattr(tokenize, t)}
    previous = None
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.ENDMARKER, tokenize.NEWLINE, tokenize.NL, tokenize.DEDENT):
            continue
        (start_row, start_col), text = token.start, token.string
        if start_row > row:
            row, col = start_row, 0
        emit(lines[row - 1][col:start_col])  # the spaces before it
        cls = None
        if token.type in strings:
            cls = "s"
        elif token.type == tokenize.COMMENT:
            cls = "c"
        elif token.type == tokenize.NUMBER:
            cls = "n"
        elif token.type == tokenize.NAME:
            cls = ("k" if keyword.iskeyword(text) else "f" if previous in ("def", "class")
                   else "d" if previous == "@" else "t" if text in TYPE_NAMES else None)
        elif text == "@":
            cls = "d"
        emit(text, cls)
        previous = text
    return out


def console_html(source):
    """A terminal transcript as HTML lines: ``$ `` commands, ``#`` comments, and output."""
    out = []
    for line in source.split("\n"):
        if line.startswith("$ "):
            out.append(f'<span class="p">$</span> {html.escape(line[2:])}')
        else:
            out.append(f'<span class="{"c" if line.startswith("#") else "o"}">{html.escape(line)}</span>')
    return out


# The YouTube cover (thumbnail): the IvoryOS name and logo, the version, a few highlights and a
# screenshot of the release, in the colors of the title slides. $-placeholders are filled by render_cover.
COVER_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0}
body{width:1280px;height:720px;overflow:hidden;position:relative;color:#f8fafc;
    font-family:"Segoe UI",system-ui,-apple-system,sans-serif;background:radial-gradient(circle at 15% 10%,#24626b,#0f172a 70%)}
.shot{position:absolute;left:575px;top:120px;width:880px;border-radius:16px;overflow:hidden;
    box-shadow:0 30px 80px rgba(0,0,0,.55),0 0 0 3px rgba(125,211,200,.4);
    transform:perspective(1700px) rotateY(-15deg) rotateX(3deg);transform-origin:left center}
.shot img{display:block;width:100%}
.text{position:absolute;left:72px;top:68px;width:540px}
.brand{display:flex;align-items:center;gap:18px}
.brand img{height:76px;border-radius:16px;background:#fff;padding:4px}
.brand span{font-size:50px;font-weight:750;letter-spacing:-.01em}
.kicker{margin-top:52px;font-size:27px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#7dd3c8}
.headline{font-size:200px;font-weight:800;line-height:.92;letter-spacing:-.04em;margin-top:4px}
.headline.words{font-size:96px;line-height:1;letter-spacing:-.02em;margin-top:10px}
ul{list-style:none;padding:0;margin-top:30px;font-size:26px;line-height:1.5;color:#e2e8f0}
li{padding-left:28px;position:relative}
li::before{content:"";position:absolute;left:2px;top:.58em;width:12px;height:12px;border-radius:50%;background:#2a9d8f}
.tagline{position:absolute;left:72px;bottom:42px;font-size:21px;color:#94a3b8}
</style></head><body>
<div class="shot"><img src="$shot" alt=""></div>
<div class="text">
    <div class="brand"><img src="$logo" alt=""><span>IvoryOS</span></div>
    <div class="kicker">$kicker</div>
    <div class="headline $size">$headline</div>
    <ul>$points</ul>
</div>
<div class="tagline">Open-source orchestrator for self-driving labs</div>
</body></html>"""


def render_cover(browser, kicker, headline, points, shot, out):
    """Write the cover, 1920x1080 JPEG (YouTube takes up to 2 MB): ``kicker`` over ``headline`` (a version
    such as ``1.8.0``, set very large, or a few words), ``points`` (a few short highlights) and ``shot`` (a
    PNG screenshot)."""
    data_uri = lambda data, kind: f"data:image/{kind};base64,{base64.b64encode(data).decode()}"
    page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=SCALE)
    page.set_content(string.Template(COVER_HTML).substitute(
        shot=data_uri(shot, "png"), logo=data_uri((REPO / "ivoryos" / "static" / "ivoryos_logo.png").read_bytes(), "png"),
        kicker=html.escape(kicker), headline=html.escape(headline), size="" if len(headline) <= 6 else "words",
        points="".join(f"<li>{html.escape(p)}</li>" for p in points)))
    page.wait_for_load_state("load")
    page.screenshot(path=str(out), type="jpeg", quality=95)
    page.close()
    return out


class ScreenRecorder:
    """Records a page with Chromium's screencast: a JPEG for each frame that changed, with its time.

    The sync Playwright API delivers the frames only while it waits on the browser, so scenes wait
    with ``page.wait_for_timeout`` (``Video.wait``), never ``time.sleep``.
    """

    def __init__(self, page, frames_dir):
        self.frames_dir = frames_dir
        self.frames = []  # (timestamp, path)
        self.gaps = []  # (start, end) wall-clock spans cut from the video, e.g. synthesizing a narration line
        self.stopped_at = None
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def start(self):
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "everyNthFrame": 1,
                                               "maxWidth": int(VIEWPORT["width"] * SCALE),
                                               "maxHeight": int(VIEWPORT["height"] * SCALE)})

    def stop(self):
        self.stopped_at = time.time()
        self.cdp.send("Page.stopScreencast")

    def _frame(self, params):
        self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        path = self.frames_dir / f"{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(params["data"]))
        self.frames.append((params["metadata"]["timestamp"], path))

    def timeline(self, t):
        """Seconds into the video of the wall-clock time ``t``: from the first frame, less the gaps cut before."""
        cut = sum(min(t, end) - start for start, end in self.gaps if t > start)
        return t - self.frames[0][0] - cut

    def duration(self):
        if not self.frames:
            raise RuntimeError("no frames were recorded")
        return self.timeline(max(self.stopped_at, self.frames[-1][0] + 1 / FPS))

    def encode(self, out, audio=None):
        """An H.264 MP4 at a constant frame rate, each frame held until the next one, in the standard
        (limited range, BT.709) colors that YouTube and players expect of an HD video, with ``audio``
        (a WAV as long as the video) as its sound track."""
        import imageio_ffmpeg

        seconds = self.duration()
        times = [self.timeline(t) for t, _ in self.frames]
        command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                   "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-"]
        if audio:  # at -16 LUFS, the loudness of spoken content online; YouTube plays it as is
            command += ["-i", str(audio), "-map", "0:v", "-map", "1:a", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        command += ["-vf", "scale=in_range=full:out_range=limited:out_color_matrix=bt709,format=yuv420p",
                    "-c:v", "libx264", "-crf", "16", "-colorspace", "bt709", "-color_primaries", "bt709",
                    "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", str(out)]
        ffmpeg = subprocess.Popen(command, stdin=subprocess.PIPE)
        # for each output frame, the last screencast frame shown by then
        shown, data = -1, b""
        for i in range(int(seconds * FPS)):
            latest = shown
            while latest + 1 < len(times) and times[latest + 1] <= i / FPS:
                latest += 1
            if latest != shown:
                shown, data = latest, self.frames[latest][1].read_bytes()
            ffmpeg.stdin.write(data)
        ffmpeg.stdin.close()
        if ffmpeg.wait():
            raise RuntimeError(f"ffmpeg failed with exit code {ffmpeg.returncode}")
        return seconds


class Video:
    """What a scene script drives: the page, plus moves and captions that read well on video."""

    def __init__(self, page, base, workdir, narrator=None):
        self.page, self.base, self.workdir, self.narrator = page, base, workdir, narrator
        self.chapters = []  # (wall-clock time, title)

    def chapter(self, title):
        """Start a YouTube chapter named ``title`` once the line being spoken ends; the description lists the
        chapters with their times. YouTube shows them on the progress bar when each lasts 10 s or more."""
        self.finish_line()
        self.chapters.append((time.time(), title))

    def wait(self, seconds):
        self.page.wait_for_timeout(int(seconds * 1000))

    def _speak(self, say, show):
        """Put something up with ``show()`` as the narration line ``say`` starts, once the line before
        has ended. Returns the line's length in seconds: 0 without one, or with the narration off."""
        clip = self.narrator.prepare(say) if say and self.narrator else None
        self.finish_line()
        show()
        if clip is None:
            return 0.0
        self.narrator.start(clip)
        return clip.seconds

    def finish_line(self):
        """Wait for the narration line being spoken to end."""
        if self.narrator:
            self.wait(max(0.0, self.narrator.until + LINE_GAP - time.time()))

    def say(self, text, hold=None):
        """Speak ``text`` over what is on screen and wait for it to end, or only ``hold`` seconds.
        Returns the line's length in seconds."""
        seconds = self._speak(text, lambda: None)
        self.wait(seconds if hold is None else hold)
        return seconds

    def go(self, path, wait=0.6):
        self.page.goto(self.base + path, wait_until="networkidle")
        self.wait(wait)

    def locate(self, target):
        return (self.page.locator(target) if isinstance(target, str) else target).first

    def move(self, target, settle=0.75):
        """Glide the cursor to the middle of ``target``, scrolling it into view first."""
        loc = self.locate(target)
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.wait(settle)
        return loc

    def click(self, target, after=0.8):
        self.move(target).click()
        self.wait(after)

    def drag(self, target, x=None, y=None, steps=20):
        """Drag ``target`` by its middle to ``x``/``y`` (either left as is), slowly enough to watch."""
        box = self.move(target).bounding_box()
        x0, y0 = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        x1, y1 = x0 if x is None else x, y0 if y is None else y
        self.page.mouse.down()
        for i in range(1, steps + 1):
            self.page.mouse.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
            self.wait(0.02)
        self.page.mouse.up()
        self.wait(0.4)

    def type(self, target, text, delay=80, after=0.5):
        """Click a field, clear it and type ``text`` key by key."""
        loc = self.move(target)
        loc.click()
        loc.press("Control+A")
        loc.press("Backspace")
        loc.press_sequentially(str(text), delay=delay)
        self.wait(after)

    def fill(self, target, text):
        """Set a field at once, for values the viewer does not need to watch being typed."""
        self.locate(target).fill(str(text))

    def caption(self, title, text="", tag=None, kind="new", where="bottom", offset=None, center=None, hold=None,
                say=None):
        """Show the caption bar. ``tag`` is a short label such as ``New · !223``; ``kind`` colors it:
        ``new``, ``fix`` or ``qol``. It sits at the ``top`` or ``bottom``, ``offset`` pixels from that edge,
        centered on the page or on ``center`` (px), to keep it off what the scene shows. Text in backticks
        is set as code. ``say`` is the narration line spoken as it appears, written to be heard.

        The scene waits ``hold`` seconds: by default until the line ends and long enough to read most of
        the caption. A shorter ``hold`` lets the scene act while the line goes on."""
        caption = {"title": title, "text": text, "tag": tag, "kind": kind, "where": where, "offset": offset,
                   "center": center}
        seconds = self._speak(say, lambda: self.page.evaluate("c => ivyVideo.caption(c)", caption))
        words = len(f"{title} {text}".split())
        self.wait(0.4 + (max(1.5, words * READ_SECONDS_PER_WORD, seconds) if hold is None else hold))

    def clear_caption(self):
        """Take the caption down, once its narration line has ended."""
        self.finish_line()
        self.page.evaluate("() => ivyVideo.clearCaption()")
        self.wait(0.4)

    def ring(self, *targets, pad=6, hold=0.0):
        """Draw a pulsing ring around each target until ``clear_rings`` (or another ``ring``)."""
        boxes = [self.locate(t).bounding_box() for t in targets]
        self.page.evaluate("([boxes, pad]) => ivyVideo.ring(boxes, pad)", [boxes, pad])
        self.wait(hold)

    def clear_rings(self):
        self.page.evaluate("() => ivyVideo.clearRings()")

    def slide(self, title, sub="", bullets=(), kicker="", foot="", hold=4.0, instant=False, say=None):
        """A full-screen title slide over the page, held for ``hold`` seconds, or until its narration line
        ``say`` has ended if that is longer."""
        slide = {"title": title, "sub": sub, "bullets": list(bullets), "kicker": kicker, "foot": foot,
                 "logo": f"{self.base}/static/ivoryos_logo.png", "instant": instant}
        seconds = self._speak(say, lambda: self.page.evaluate("s => ivyVideo.slide(s)", slide))
        self.wait(max(hold, seconds + 0.8) if seconds else hold)

    def clear_slide(self):
        self.finish_line()
        self.page.evaluate("() => ivyVideo.clearSlide()")
        self.wait(0.6)

    def code(self, source, file="", kicker="", title="", console=False, say=None, hold=4.0):
        """A full-screen code editor showing ``source``: Python, or a terminal transcript with ``console``
        (``$ `` commands, ``#`` comments, output). Held for ``hold`` seconds, or until ``say`` has been
        spoken if that is longer; ``focus`` then walks through its lines, and ``clear_slide`` ends it."""
        slide = {"lines": console_html(source) if console else highlight_python(source), "file": file,
                 "kicker": kicker, "title": title, "console": console}
        seconds = self._speak(say, lambda: self.page.evaluate("c => ivyVideo.code(c)", slide))
        self.wait(max(hold, seconds + 0.6) if seconds else hold)

    def focus(self, *lines, notes=None, say=None, hold=None):
        """Highlight ``lines`` of the code slide (line numbers, or ranges such as ``"5-10"``) and dim the
        rest; with none, every line is shown plainly again. ``notes`` labels the end of a line, e.g.
        ``{6: "table editor"}``. Waits until ``say`` has been spoken, or ``hold`` seconds."""
        numbers = []
        for spec in lines:
            if isinstance(spec, str) and "-" in spec:
                first, last = map(int, spec.split("-"))
                numbers += range(first, last + 1)
            else:
                numbers.append(int(spec))
        labels = {str(n): text for n, text in (notes or {}).items()}
        seconds = self._speak(say, lambda: self.page.evaluate("([n, l]) => ivyVideo.focus(n, l)", [numbers, labels]))
        self.wait(0.5 + (max(1.5, seconds) if hold is None else hold))

    def cover_shot(self):
        """A PNG screenshot of the page for the cover, without the cursor, captions, rings or slides."""
        self.page.evaluate("() => document.documentElement.classList.add('ivy-cover')")
        self.wait(0.3)
        return self.page.screenshot(type="png")

    # the pages most scenes go through

    def toolbox_form(self, instrument, action):
        """Open ``action`` of ``instrument`` (``deck.liquid_handler``) in the designer toolbox and return its form."""
        group = self.page.locator(f"#toolbox-{instrument.replace('.', '-')}")
        if group.get_attribute("hidden") is not None:
            self.click(f".toolbox-divider[data-group='{instrument}']")
        toggle = group.locator(f".toolbox-action-toggle[data-action='{action}']")
        if toggle.get_attribute("aria-expanded") != "true":
            self.click(group.locator(f".toolbox-action:has(.toolbox-action-toggle[data-action='{action}'])"), after=0.3)
        return group.locator(f".toolbox-action:has(.toolbox-action-toggle[data-action='{action}']) form")

    def add_step(self, form):
        """Click the toolbox form's add button and wait for the step to be added."""
        with self.page.expect_response(lambda r: "/draft/instruments/" in r.url):
            self.click(form.locator("button[type=submit]"), after=0)
        self.wait(0.6)

    def dict_rows(self, field, rows, typed=True):
        """Add ``rows`` (``{key: value}``) to a dict argument's table editor; ``field`` holds the editor."""
        field = self.locate(field)
        for key, value in rows.items():
            self.click(field.locator(".structured-add-row"), after=0.4)
            row = field.locator(".structured-table tbody tr").last
            for column, text in (("key", key), ("value", value)):
                cell = row.locator(f"[data-column={column}]")
                self.type(cell, text) if typed else self.fill(cell, text)

    def config_rows(self, rows):
        """Fill the Execution page's config table: ``rows`` is a list of ``{input name: value}``."""
        page = self.page
        page.locator("#tab2 button", has_text="Clear").click()  # asks to confirm; dialogs are accepted
        self.wait(0.3)
        columns = [th.inner_text().strip().split("\n")[0].rstrip("*").strip()
                   for th in page.locator("#dataInputTable thead th").all()]
        while page.locator("#tableBody tr").count() < len(rows):
            self.click(page.locator("#tab2 button", has_text="Add Row"), after=0.3)
        for i, values in enumerate(rows):
            row = page.locator("#tableBody tr").nth(i)
            for name, value in values.items():
                cell = row.locator("td").nth(columns.index(name)).locator("input")
                self.type(cell, value, delay=60, after=0.15)

    def wait_until_idle(self, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.page.locator("#global-status-icon").inner_text().strip() == "Idle":
                return
            self.wait(0.5)
        raise RuntimeError("the run did not finish in time")


# ---------------------------------------------------------------------------------------------
# CHANGELOG
# ---------------------------------------------------------------------------------------------

def changelog_section(version):
    """``(heading, body)`` of ``version`` in CHANGELOG.md, e.g. ``("1.8.0 (November 3rd, 2026)", "...")``."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8-sig")
    match = re.search(rf"^## ({re.escape(version)}\b[^\n]*)\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return match.group(1).strip(), match.group(2).strip()


def needs_video(version, body):
    """A minor or major release, or one that adds something new."""
    patch = int(version.split(".")[2])
    return patch == 0 or "**[New]**" in body


def scene_path(version):
    return SCENES_DIR / f"v{version.replace('.', '_')}.py"


def load_scenes(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_version():
    return re.search(r'"(.+)"', (REPO / "ivoryos" / "version.py").read_text(encoding="utf-8")).group(1)


# ---------------------------------------------------------------------------------------------

def launch_server(workdir):
    from capture_screenshots import free_port, wait_for

    port = free_port()
    launcher = workdir / "launch_dye_lab.py"
    launcher.write_text(LAUNCHER.format(repo=str(REPO), here=str(HERE), port=port), encoding="utf-8")
    log = open(workdir / "server.log", "w", encoding="utf-8")
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    env.pop("IVORYOS_ACTIVE", None)
    proc = subprocess.Popen([sys.executable, str(launcher)], cwd=workdir, stdout=log, stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{port}/ivoryos"
    try:
        wait_for(base + "/")
    except RuntimeError:
        proc.kill()
        print((workdir / "server.log").read_text(encoding="utf-8"))
        raise
    return proc, base


TAGLINE = "IvoryOS - an open-source orchestrator for self-driving labs"

# What every YouTube description ends with. The videos show no links, since nobody can click them;
# the description is where they go.
ABOUT = ("IvoryOS is an open-source orchestrator for self-driving labs. It turns the Python that drives your "
         "instruments into a web app for direct control, drag-and-drop workflows, automated and optimized runs, "
         "and a record of every experiment.")
NARRATION_NOTE = "Narration: synthesized locally with the Kokoro text-to-speech model."
LINKS = [
    ("Website", "https://ivoryos.ai"),
    ("Documentation", "https://ivoryos.readthedocs.io"),
    ("Source code", "https://gitlab.com/heingroup/ivoryos"),
    ("PyPI", "https://pypi.org/project/ivoryos/"),
    ("Paper (Nature Communications)", "https://www.nature.com/articles/s41467-025-60514-w"),
    ("Community (Discord)", "https://discord.gg/3KdjhUmsYA"),
]
CHANGELOG_URL = "https://gitlab.com/heingroup/ivoryos/-/blob/main/CHANGELOG.md"
TUTORIAL_URL = "https://youtu.be/iwRtIBsNFZ4"  # "Getting started with IvoryOS", linked from release videos
HASHTAGS = "#SelfDrivingLab #LabAutomation #Python"
TAGS = ["IvoryOS", "self-driving lab", "SDL", "lab automation", "laboratory automation", "autonomous experimentation",
        "Python", "workflow orchestration", "Bayesian optimization", "chemistry automation"]


def release_video(version, heading, scenes):
    """The title slide, closing slide, cover and YouTube text of a release's "what's new" video."""
    spoken = version[:-2] if version.endswith(".0") else version  # "IvoryOS 1.8"
    date = re.search(r"\((.+)\)", heading)
    intro = {"title": f"What's new in {version}", "kicker": "IvoryOS release", "sub": getattr(scenes, "SUBTITLE", ""),
             "foot": date.group(1) if date else "",
             "say": f"Here's what's new in IvoryOS {spoken}. {getattr(scenes, 'INTRO', '')}".strip()}
    outro = {"title": f"pip install -U ivoryos=={version}", "kicker": "Upgrade", "foot": TAGLINE,
             "say": getattr(scenes, "OUTRO", "To upgrade, pip install the new version. Thanks for watching!")}
    youtube = {"title": getattr(scenes, "YOUTUBE_TITLE", f"What's new in IvoryOS {spoken}"),
               "description": getattr(scenes, "DESCRIPTION", getattr(scenes, "SUBTITLE", "")),
               "links": [(f"Release notes for {version}", CHANGELOG_URL),
                         ("New to IvoryOS? Getting started tutorial", TUTORIAL_URL)] + LINKS}
    return intro, outro, ("What's new in", version), youtube


def tutorial_video(scenes):
    """The title slide, closing slide, cover and YouTube text of a tutorial, from its ``TITLE``, ``INTRO``,
    ``OUTRO`` and ``DESCRIPTION``."""
    intro = {"title": scenes.TITLE, "kicker": "IvoryOS tutorial", "sub": getattr(scenes, "SUBTITLE", ""),
             "say": getattr(scenes, "INTRO", None)}
    outro = {"title": getattr(scenes, "OUTRO_TITLE", "pip install ivoryos"), "kicker": "Try it", "foot": TAGLINE,
             "say": getattr(scenes, "OUTRO", "Thanks for watching!")}
    youtube = {"title": getattr(scenes, "YOUTUBE_TITLE", scenes.TITLE),
               "description": getattr(scenes, "DESCRIPTION", getattr(scenes, "SUBTITLE", "")), "links": LINKS}
    return intro, outro, ("Tutorial", getattr(scenes, "COVER_TITLE", scenes.TITLE)), youtube


def youtube_chapters(chapters, seconds):
    """``chapters`` (``[(seconds, title)]``, the first at 0) as YouTube takes them: each at least 10 s long and
    at least three, or none. Returns the lines, and what was dropped and why."""
    kept, dropped = [], []
    for at, title in sorted(chapters):
        if kept and at - kept[-1][0] < 10:  # the earlier one keeps its place
            dropped.append(f"{title!r} (starts within 10 s of {kept[-1][1]!r})")
            continue
        kept.append((at, title))
    if kept and seconds - kept[-1][0] < 10:
        dropped.append(f"{kept.pop()[1]!r} (shorter than 10 s)")
    if len(kept) < 3:
        return [], dropped + ["all chapters (YouTube needs three or more)"]
    return [f"{int(at // 60)}:{int(at % 60):02d} {title}" for at, title in kept], dropped


def write_youtube_text(out, youtube, chapters, seconds):
    """Write what to paste into YouTube's upload form: title, description (with chapters and links) and tags."""
    lines, dropped = youtube_chapters(chapters, seconds)
    description = [youtube["description"].strip(), ""]
    if lines:
        description += ["Chapters", *lines, ""]
    description += [ABOUT, "", *(f"{name}: {url}" for name, url in youtube["links"]), "", NARRATION_NOTE, "", HASHTAGS]
    text = "\n".join(description)
    problems = [f"the title is {len(youtube['title'])} characters; YouTube takes 100"] * (len(youtube["title"]) > 100)
    problems += [f"the description is {len(text)} characters; YouTube takes 5000"] * (len(text) > 5000)
    out.write_text(f"=== Title ===\n{youtube['title']}\n\n=== Description ===\n{text}\n\n=== Tags ===\n"
                   f"{', '.join(TAGS)}\n", encoding="utf-8")
    for problem in problems + [f"chapter dropped: {d}" for d in dropped]:
        print(f"  [youtube] {problem}")
    return out


def record(scenes, out, intro, outro, cover, youtube, headed=False, cdn_mirror=None, keep=False, voice=None,
           mute=False):
    """Record ``scenes`` to ``out``, between an ``intro`` and an ``outro`` slide (``Video.slide`` arguments,
    ``say`` included), then make the cover (``cover`` is its ``(kicker, headline)``) and the YouTube text
    (``youtube``: its ``title``, ``description`` and ``links``)."""
    # here rather than at the top, so --check runs without the video extras installed
    from capture_screenshots import cdn_router, login
    from playwright.sync_api import sync_playwright

    narrator = None
    if not mute:
        from narration import Narrator

        narrator = Narrator(voice=voice) if voice else Narrator()

    workdir = Path(tempfile.mkdtemp(prefix="ivoryos-video-"))
    frames_dir = workdir / "frames"
    frames_dir.mkdir()
    proc, base = launch_server(workdir)
    print(f"IvoryOS started at {base} in {workdir}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed, args=[
                f"--window-size={VIEWPORT['width']},{VIEWPORT['height']}", f"--force-device-scale-factor={SCALE}"])
            context = browser.new_context(no_viewport=True)
            if cdn_mirror:
                context.route(re.compile(r"^https://"), cdn_router(cdn_mirror))
            context.add_init_script(OVERLAY_JS)
            page = context.new_page()
            page.set_default_timeout(20000)
            page.on("pageerror", lambda e: print(f"  [page error] {e}"))
            page.on("dialog", lambda d: d.accept())
            login(page, base)
            if hasattr(scenes, "setup"):
                scenes.setup(page, base)  # off camera
            video = Video(page, base, workdir, narrator)
            video.go(getattr(scenes, "START", "/"))
            video.slide(**{k: v for k, v in intro.items() if k != "say"}, hold=0, instant=True)
            if narrator and intro.get("say"):
                narrator.prepare(intro["say"])  # before the recording, so the video opens on it
            recorder = ScreenRecorder(page, frames_dir)
            recorder.start()
            if narrator:
                recorder.gaps = narrator.gaps
                narrator.recording = True
            video.wait(max(5, video.say(intro.get("say"), hold=0) + 0.8))
            video.clear_slide()
            scenes.play(video)
            video.clear_caption()
            video.slide(**outro, hold=5)
            video.finish_line()
            recorder.stop()
            page.evaluate("() => { ivyVideo.clearSlide(true); ivyVideo.clearCaption(); ivyVideo.clearRings(); }")
            if hasattr(scenes, "cover"):
                scenes.cover(video)  # off camera: the page the cover shows
            else:
                video.go(getattr(scenes, "START", "/"))
            shot = video.cover_shot()
            (workdir / "cover-shot.png").write_bytes(shot)  # kept with --keep, to rework the cover's design
            cover = render_cover(browser, *cover, getattr(scenes, "COVER_POINTS", ()), shot,
                                 out.with_name(f"{out.stem}-cover.jpg"))
            browser.close()
        narrated = narrator is not None and bool(narrator.lines)
        audio = narrator.track(recorder.timeline, recorder.duration(), workdir / "narration.wav") if narrated else None
        seconds = recorder.encode(out, audio)
        print(f"{out} ({seconds:.0f} s, {len(recorder.frames)} frames)")
        print(f"{cover} (the YouTube cover)")
        chapters = [(0.0, "Intro")] + [(max(0.0, recorder.timeline(t)), title) for t, title in video.chapters]
        print(f"{write_youtube_text(out.with_name(f'{out.stem}-youtube.txt'), youtube, chapters, seconds)} "
              f"(title, description and tags for YouTube)")
        if narrated:
            print(f"{narrator.subtitles(recorder.timeline, out.with_suffix('.srt'))} (the narration as subtitles)")
            narrator.report()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if keep:
            print(f"frames and server log kept in {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", nargs="?", default=current_version(), help="release version, e.g. 1.8.0")
    parser.add_argument("--check", action="store_true", help="only report whether the release needs a video")
    parser.add_argument("--out", type=Path, help="the MP4 to write")
    parser.add_argument("--cdn-mirror", type=Path, help="node_modules folder to serve CDN files from")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument("--keep", action="store_true", help="keep the frames and server log, to debug a scene")
    parser.add_argument("--voice", help="the narration's Kokoro voice (default af_heart, see narration.py)")
    parser.add_argument("--mute", action="store_true", help="record without narration")
    parser.add_argument("--tutorial", metavar="NAME", help="record tutorials/NAME.py instead of a release video")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")  # a Windows console cannot print every character of the CHANGELOG
    options = dict(headed=args.headed, cdn_mirror=args.cdn_mirror, keep=args.keep, voice=args.voice, mute=args.mute)

    if args.tutorial:
        path = TUTORIALS_DIR / f"{args.tutorial}.py"
        if not path.exists():
            sys.exit(f"no tutorial {path.relative_to(REPO)}; there are: "
                     + ", ".join(p.stem for p in sorted(TUTORIALS_DIR.glob("*.py"))))
        scenes = load_scenes(path)
        out = args.out or OUT_DIR / f"ivoryos-tutorial-{args.tutorial}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        record(scenes, out, *tutorial_video(scenes), **options)
        return

    version = args.version.lstrip("v")
    heading, body = changelog_section(version)
    path = scene_path(version)
    needed = needs_video(version, body)
    scenes = load_scenes(path) if path.exists() else None
    skip = getattr(scenes, "SKIP", None)  # a scene script can stand for "nothing to show", with the reason
    if args.check:
        print(f"## {heading}\n\n{body}\n")
        print(f"needs a video: {'yes' if needed else 'no (a patch release without [New] entries)'}")
        print(f"scene script: {path.relative_to(REPO)} {'(found)' if path.exists() else '(missing)'}"
              + (f", skipped: {skip}" if skip else ""))
        sys.exit(1 if needed and not path.exists() else 0)
    if not path.exists():
        if needed:
            sys.exit(f"{version} needs a release video: write {path.relative_to(REPO)} from its CHANGELOG section "
                     f"(see docs/release_videos/README.md)")
        print(f"{version} is a patch release without [New] entries: no video")
        return
    if skip:
        print(f"{version}: no video ({skip})")
        return
    out = args.out or OUT_DIR / f"ivoryos-{version}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    record(scenes, out, *release_video(version, heading, scenes), **options)


if __name__ == "__main__":
    main()
