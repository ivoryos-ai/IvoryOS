# Release and tutorial videos

Maintainer notes; not part of the published docs. Agents follow
`.agents/skills/release_video/SKILL.md`, which builds on this file.

`record.py` starts a simulated dye-mixing lab (`dye_lab.py`) from the checkout, logs in and plays a
**scene script** in Chromium the way a user would: a visible cursor, captions naming each CHANGELOG
entry, title slides and a spoken narration. Everything runs on your machine; CI neither records nor
checks videos. Each recording writes, to `output/` (git-ignored, never committed):

| File | What it is |
|---|---|
| `ivoryos-<version>.mp4` | 1920x1080 video with narration, ready for YouTube |
| `ivoryos-<version>.srt` | the narration as subtitles |
| `ivoryos-<version>-cover.jpg` | the YouTube thumbnail |
| `ivoryos-<version>-youtube.txt` | title, description (with chapters and links) and tags to paste |

Setup, once:

```console
pip install -e ".[video]"
playwright install chromium
```

The voice and speech-check models download on the first recording (about 820 MB in all).

## Releasing

A release needs a video when it is a minor or major release (`1.9.0`, `2.0.0`) or its CHANGELOG
section has a `**[New]**` entry; a patch release of fixes does not.

```console
python docs/release_videos/record.py --check          # the version in ivoryos/version.py
python docs/release_videos/record.py 1.8.1 --check
```

`--check` prints the CHANGELOG section, says whether it needs a video, and exits with 1 when it does
and `scenes/v<major>_<minor>_<patch>.py` is missing. A release with nothing to show in the UI (a
`[New]` entry for docs or packaging only) gets a scene script holding only `SKIP = "<the reason>"`.

1. Write the CHANGELOG section and bump `ivoryos/version.py`.
2. Write the scene script (below) and record: `python docs/release_videos/record.py`.
3. Watch the MP4, fix the script and re-record until the screen matches the captions and the voice
   sounds right.
4. Commit the scene script with the version bump, then tag. On YouTube, upload the MP4, paste the
   title, description and tags from `-youtube.txt`, set the cover as the thumbnail and add the `.srt`
   as English subtitles. Then link the video at the end of the release's CHANGELOG summary
   ("Watch [what's new in 1.8.0](...)."), and in the README's video list in place of the last
   release's.

## Writing a scene script

Copy the latest script in `scenes/` and rewrite `play(video)`. Show the entries a user would notice,
in the order a chemist meets them: try an instrument, build a workflow, run it, read the data. Bug
fixes go on an "Also in" slide; anything that changes existing workflows gets its own upgrade slide.

A scene script defines:

| Name | |
|---|---|
| `play(video)` | the scenes, between the title slide and the closing slide `record.py` adds |
| `SUBTITLE` | the line under the title, e.g. what the demo lab is |
| `INTRO` / `OUTRO` | what the voice says on the title slide (after "Here's what's new in IvoryOS 1.8.") and the closing slide |
| `START` | the page the video opens on, e.g. `/instruments/deck.liquid_handler` |
| `COVER_POINTS` | two or three highlights for the cover, under 35 characters each |
| `cover(video)` | runs off camera after the recording and leaves the page the cover shows; by default `START` |
| `YOUTUBE_TITLE` / `DESCRIPTION` | the YouTube title (up to 100 characters) and a paragraph or two on the release |
| `setup(page, base)` | anything to prepare off camera, such as importing a workflow |

Only `play` is required. `video` is a `Video` from `record.py`:

| Call | Does |
|---|---|
| `video.page` | the Playwright page, for anything below does not cover |
| `go(path)` | open a page of the app, e.g. `"/draft"` |
| `click(target)`, `type(target, text)`, `fill(target, text)`, `drag(target, y=...)` | act with the visible cursor; `fill` sets a value at once |
| `caption(title, text, tag="New · !223", kind="new"/"fix"/"qol", where="top"/"bottom", offset=, center=, say=, hold=)` | the caption bar; text in backticks is set as code |
| `ring(*targets, hold=)`, `clear_rings()` | a pulsing ring around what the caption is about |
| `slide(title, sub=, bullets=, kicker=, say=, hold=)` | a full-screen slide, held at least until `say` is spoken |
| `say(text, hold=)` | narration over what is on screen, without a caption |
| `chapter(title)` | start a YouTube chapter once the current line ends |
| `code(source, file=, kicker=, console=, say=, hold=)` | a full-screen editor with `source` highlighted as Python, or a terminal with `console=True` |
| `focus(*lines, notes=, say=, hold=)` | highlight lines of the code slide (`6`, `"5-10"`), dim the rest; `notes={6: "a table editor"}` labels a line |
| `toolbox_form(instrument, action)`, `add_step(form)` | open a designer toolbox action, add the step |
| `dict_rows(field, {key: value})`, `config_rows([{input: value}])` | fill a dict table editor, the run config table |
| `wait(seconds)`, `wait_until_idle()` | pause; wait for a run to finish |

Targets are CSS selectors or Playwright locators; selectors are easiest to find in the templates or in
`docs/screenshots/capture_screenshots.py`, which drives the same pages. Always wait with
`video.wait`, never `time.sleep`: the recorder only receives frames while Playwright waits on the
browser.

The pace is slow on purpose: a caption pauses about a quarter of a second per word
(`READ_SECONDS_PER_WORD`), and slides hold as long as their text takes to read. Keep URLs out of
captions and slides; they go in the description.

## Narration

A caption, slide or `video.say` with a `say=` line is spoken, and the voice sets the pace: the scene
waits for each line to end, unless a shorter `hold` lets it act while the line goes on. Write lines to
be heard: no code or symbols ("Dictionary arguments now get a table editor", not `Dict[str, float]`),
units in words ("60 microliters"), one idea per sentence. `--mute` records without a voice, `--voice`
picks another.

The voice is Kokoro (Apache-2.0, through `kokoro-onnx` on the CPU), `af_heart` by default; its
settings are in `narration.py`. The model is cached in `~/.cache/ivoryos/kokoro`, and each line is
synthesized once and cached in `output/voice/`, so a re-recording only speaks lines that changed.

After recording, Whisper (`faster-whisper`, `small.en`, also local) transcribes each line and lists
those it heard differently. Whisper mishears too ("dye" as "die"); a real slip is fixed by respelling
the word in `SPEAK_AS` in `narration.py` (`IvoryOS` is spoken as "Ivory O S") or rewording the line.
To try voices on a line:

```console
python docs/release_videos/narration.py "Dict arguments now get a table editor." --voices af_heart,am_michael
```

On Windows, Python installs that ship an old Visual C++ runtime next to `python.exe` (Anaconda does)
crash onnxruntime on import; `narration.py` loads the system's runtime first to avoid it.

## Cover, chapters and YouTube text

The cover shows the IvoryOS logo, "What's new in" and the version in large type, `COVER_POINTS`, and
a screenshot of the page `cover(video)` leaves open, in the title slides' colors (`COVER_HTML` in
`record.py`). YouTube draws the video's length over the bottom-right corner, so keep text out of it.
With `--keep`, the screenshot stays as `cover-shot.png` in the temporary folder, so `render_cover` can
be rerun on it while reworking the design.

Call `video.chapter("...")` where each part starts. YouTube only shows chapters when the first is at
0:00 (`record.py` adds "Intro"), there are at least three, and each lasts 10 seconds or more;
`record.py` drops a chapter that breaks this and says so. The links, the paragraph about IvoryOS,
the hashtags and the tags are constants in `record.py` (`LINKS`, `ABOUT`, `HASHTAGS`, `TAGS`); a
release's description also links the release notes and the getting-started tutorial
(`TUTORIAL_URL`; update it if the tutorial is re-recorded and uploaded again).

## Tutorials

Tutorials are walkthroughs not tied to a release, written like scene scripts in `tutorials/`:

```console
python docs/release_videos/record.py --tutorial getting_started
```

`getting_started.py` shows the Python a lab needs on code slides, line by line, then each page of the
app in the order of work. Besides the scene script names, a tutorial defines `TITLE`, `INTRO`,
`OUTRO_TITLE` and `OUTRO` (by default `pip install ivoryos`), and `COVER_TITLE` (a few words set large
on the cover). Keep code slides to 24 lines. Re-record a tutorial when a UI change makes it out of
date.

## The demo lab

`dye_lab.py` simulates a liquid handler (`dispense(recipe_ul: Dict[str, float])`, `mix`,
`dilute(wells: List[str])`, `move_to(xy_mm: Tuple[float, float])`) and a plate reader
(`read_absorbance(wavelengths_nm: Set[int], shake: Optional[Literal[...]])`, `color_distance`).
60 uL yellow and 40 uL blue matches the `green` target, so a screen of recipes has a clear winner.
Each method logs what it received, so a video can show the values the driver got. Add a method when
a release needs a new kind of argument, and keep it something a lab does.

## Reviewing a recording

`--keep` keeps the frames and server log in the temporary folder it prints. A contact sheet is the
quickest review:

```console
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
<ffmpeg> -i docs/release_videos/output/ivoryos-1.8.0.mp4 -vf "fps=1/3,scale=640:360,tile=2x3" sheet%02d.png
```

Check that each caption sits clear of what it describes, every ring lands on its target, the values
on screen match the captions, and the narration talks about what is on screen (the `.srt` has the
video's times).
