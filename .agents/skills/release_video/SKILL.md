---
name: release_video
description: How to write, record and review the "what's new" video of an IvoryOS release, and tutorial videos (docs/release_videos). Use before tagging a release, when bumping ivoryos/version.py, or when asked for a release, demo or tutorial video.
---

# IvoryOS Release Video

A release that is `x.y.0` or has a `**[New]**` CHANGELOG entry gets a 3-4 minute narrated video:
IvoryOS driving a simulated dye-mixing lab, with captions naming each CHANGELOG entry it shows and a
locally generated voice explaining it. The full reference (the `Video` API, narration, the cover,
the demo lab) is `docs/release_videos/README.md`; read it first. This skill is the working loop.
Videos are internal release work: keep them out of the published docs in `docs/source/`.

---

## 1. Does this release need one?

```console
python docs/release_videos/record.py --check            # version from ivoryos/version.py
```

It prints the CHANGELOG section. Exit 0 with "needs a video: no" means stop here and tell the user
it is a minor patch release. Exit 1 means write the scene script.

## 2. Plan the story from the CHANGELOG section

- Keep it to what a lab user notices: new argument types, new pages or buttons, run behavior, data.
  Bug fixes and refactors go on an "Also in <version>" slide, one short line each.
- Changes that alter existing workflows (anything under **Upgrading:**) get a "Heads-up when
  upgrading" slide. Never leave them out.
- Order the scenes the way a chemist works: Instruments page (try a method), Workflow designer
  (build), Execution (run), Data (read results). Reuse the dye lab's story: dispense a recipe, mix,
  read absorbance, score the color against `green`; 60 uL yellow + 40 uL blue is the match.
- If a feature needs an argument type or method the lab lacks, add it to
  `docs/release_videos/dye_lab.py` as something a liquid handler or plate reader would do, and log
  what it received.
- Each caption: a title saying what the viewer gets ("Dict arguments get a table editor"), one line
  with the concrete example in backticks, and `tag="New · !<MR>"` (`kind="fix"` for `[Bug]`,
  `kind="qol"` for `[QoL]`). Only claim what the screen shows.
- Say slide bullets concretely, in the demo's own terms: not "a required `#name` that no step sets",
  but "a run that leaves `#yellow_ul` out is refused instead of calling the driver with `None`".
- No URLs in captions or slides: nobody can click them. Links go in the YouTube description.
- Keep the pace slow: captions already pause for reading; give each result a `ring` of 3-5 s.
- For the cover, set `COVER_POINTS` (two or three highlights under 35 characters, in a viewer's
  words) and a `cover(video)` that leaves the page on the release's most telling screen.
- For YouTube, set `YOUTUBE_TITLE` (what the release brings, up to 100 characters) and `DESCRIPTION`
  (one or two paragraphs from the CHANGELOG section, in a lab user's words), and call
  `video.chapter("...")` at the start of each part, so the description lists chapters.
- Give every caption and slide a `say=` line, written to be heard: plain sentences, no code or
  symbols, units in words ("60 microliters"). Say what the viewer is about to see ("Type the
  wavelengths with commas"), and pass a short `hold` (2-4 s) where the scene should act while the line
  goes on. Long silent stretches of typing can take a `video.say(..., hold=0)` in the middle.

## 3. Write `docs/release_videos/scenes/v<major>_<minor>_<patch>.py`

Start from the latest scene script; it defines `SUBTITLE`, `START` and `play(video)` with one
function per page. Find selectors in the templates (`ivoryos/routes/*/templates/`) or in
`docs/screenshots/capture_screenshots.py`, which drives the same pages. Use `video.click`,
`video.type` and `video.drag` for anything the viewer should watch, `video.fill` for the rest, and
`video.wait`, never `time.sleep`.

## 4. Record and review

```console
pip install -e ".[video]"
playwright install chromium
python docs/release_videos/record.py --keep
```

Then build contact sheets and look at every one:

```console
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
<ffmpeg> -y -i docs/release_videos/output/ivoryos-<version>.mp4 -vf "fps=1/3,scale=640:360,tile=2x3" <tmp>/sheet%02d.png
```

The end of the run prints Whisper's check of the narration. For each line it heard differently, decide
whether the voice or Whisper is wrong (a British voice's "colour" is fine): respell a word the voice
gets wrong in `SPEAK_AS` in `docs/release_videos/narration.py`, or reword the line, and re-record;
cached lines are not synthesized again.

Fix and re-record until:

- no caption covers the control or value it talks about (move it with `where`, `offset`, `center`);
- each `ring` lands on its target and the values in it match the caption's text;
- nothing fails or shows an error the scene did not intend; a timeout means a selector is wrong;
- Whisper hears every line as written, or the differences are its own mishearing;
- the narration talks about what is on screen as it is spoken (check a contact sheet against
  `ivoryos-<version>.srt`, whose times are the video's);
- the cover (`ivoryos-<version>-cover.jpg`) shows the right version and screen, and no text is cut off;
- `ivoryos-<version>-youtube.txt` has the chapters you set (the run prints any it had to drop) and a
  description that matches what the video shows;
- it runs about three to four minutes, unhurried.

## 5. Hand off

Commit the scene script (and any `dye_lab.py` or `SPEAK_AS` change) with the version bump; do not
commit the MP4, SRT, cover or YouTube text. Give the user the MP4 path (1920x1080 with narration, ready
for YouTube), the cover to set as its thumbnail, the SRT to add as its subtitles, the title and
description from `-youtube.txt` to paste, and a one-paragraph list of what the video shows. When the
user shares the uploaded video's link, add it to the end of the release's CHANGELOG summary
("Watch [what's new in 1.8.0](...).") and replace the last release's video in the README's video list. Nothing in CI records or checks videos; the local MP4 is the one to upload.

## Tutorials

A tutorial (`docs/release_videos/tutorials/<name>.py`, recorded with `--tutorial <name>`) follows the
same loop without the CHANGELOG: plan it as a story a new user can follow, page by page, and show
code with `video.code` and `video.focus`, saying what each highlighted line does. Keep code slides to
24 lines or fewer so they fit.
