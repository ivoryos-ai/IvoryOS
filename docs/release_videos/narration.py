"""The spoken narration of a release video: a natural-sounding voice, generated locally, for the captions
and slides of a scene script.

Lines are spoken by Kokoro, an 82M-parameter text-to-speech model (Apache-2.0) that runs on the CPU,
through ``kokoro-onnx``. Its model files (about 340 MB) are downloaded once to ``~/.cache/ivoryos/kokoro``.
Each line is synthesized once and cached by its text and voice in ``output/voice/``, so re-recording a
scene only speaks the lines that changed.

After a recording, Whisper (``faster-whisper``, a speech-to-text model that also runs locally) listens to
every line and reports the ones it hears differently from the script: a word the voice garbles or a
name it says wrong. Spell such a word for the voice in ``SPEAK_AS``; captions and subtitles keep the
written form.

Try the voices on a line of your own (``--voices`` lists them, comma separated)::

    python docs/release_videos/narration.py "Dict arguments now get a table editor."
"""
import argparse
import ctypes
import difflib
import hashlib
import os
import re
import sys
import textwrap
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODEL_DIR = Path.home() / ".cache" / "ivoryos" / "kokoro"
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
SAMPLE_RATE = 24000
# af_ and am_ are American female and male voices, bf_ and bm_ British; af_heart is Kokoro's best.
VOICE = "af_heart"
SAMPLE_VOICES = ("af_heart", "af_bella", "am_michael", "bf_emma")
SPEED = 1.0
SENTENCE_PAUSE = 0.35  # seconds of silence after a full stop, so a line does not rush
WHISPER_MODEL = "small.en"  # about 480 MB, once; base.en is smaller but mishears more ("Well A2" as "L.A. 2")
# Words the voice says wrong, spelled the way it says them right.
SPEAK_AS = {"IvoryOS": "Ivory O S"}


def speak_as(text):
    """``text`` as the voice should read it: ``SPEAK_AS`` spellings, and ``1.8.1`` as "1 point 8 point 1"."""
    for word, spoken in SPEAK_AS.items():
        text = re.sub(rf"\b{re.escape(word)}\b", spoken, text, flags=re.IGNORECASE)
    return re.sub(r"\b(\d+)\.(\d+)\.(\d+)\b", r"\1 point \2 point \3", text)


def read_wav(path):
    with wave.open(str(path), "rb") as f:
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32767


def write_wav(path, audio):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def wav_seconds(path):
    with wave.open(str(path), "rb") as f:
        return f.getnframes() / f.getframerate()


def load_system_cpp_runtime():
    """Load Windows' own C++ runtime before onnxruntime looks for one.

    Python installs that bundle an older ``msvcp140.dll`` next to ``python.exe`` (Anaconda ships 14.27)
    would hand that one to onnxruntime, which needs 14.40 or newer and then crashes on import or fails
    with "DLL initialization routine failed". A DLL already loaded is the one every later import gets.
    """
    if sys.platform == "win32":
        path = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "msvcp140.dll"
        if path.exists():
            ctypes.WinDLL(str(path))


def model_files():
    """The Kokoro model and voices, downloaded on first use."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in MODEL_FILES:
        path = MODEL_DIR / name
        if not path.exists():
            print(f"downloading the Kokoro voice model {name} to {MODEL_DIR} (once)")
            part = path.with_name(name + ".part")
            urllib.request.urlretrieve(MODEL_URL + name, part)
            part.replace(path)
        paths.append(str(path))
    return paths


class Clip:
    """One spoken line: its written text and the cached WAV of it."""

    def __init__(self, text, path):
        self.text, self.path = text, path
        self.seconds = wav_seconds(path)


class Narrator:
    """Speaks the lines of a recording and remembers when each started, to lay them on an audio track.

    A line that is not cached yet is synthesized when the scene reaches it, which takes a second or two.
    While recording, that time is noted in ``gaps`` and cut from the video, so the line still starts
    as its caption appears.
    """

    def __init__(self, voice=VOICE, speed=SPEED, cache_dir=HERE / "output" / "voice"):
        self.voice, self.speed = voice, speed
        self.cache_dir = cache_dir / voice
        self.lines = []  # (wall-clock start, Clip), in the order spoken
        self.gaps = []  # (start, end) wall-clock spans spent synthesizing while recording
        self.recording = False
        self.until = 0.0  # wall-clock time the line being spoken ends
        self._kokoro = None

    def prepare(self, text):
        """The clip of ``text``, synthesized now unless it is cached."""
        spoken = speak_as(text)
        key = hashlib.sha1(f"{MODEL_FILES[0]}|{self.voice}|{self.speed}|{SENTENCE_PAUSE}|{spoken}".encode())
        path = self.cache_dir / f"{key.hexdigest()[:16]}.wav"
        if not path.exists():
            started = time.time()
            write_wav(path, self.synthesize(spoken))
            if self.recording:
                self.gaps.append((started, time.time()))
                self.until += time.time() - started
        return Clip(text, path)

    def synthesize(self, spoken):
        if self._kokoro is None:
            load_system_cpp_runtime()
            from kokoro_onnx import Kokoro

            self._kokoro = Kokoro(*model_files())
        audio, rate = self._kokoro.create(spoken, voice=self.voice, speed=self.speed,
                                          lang="en-gb" if self.voice.startswith("b") else "en-us",
                                          sentence_pause=SENTENCE_PAUSE)
        assert rate == SAMPLE_RATE
        return audio

    def start(self, clip):
        now = time.time()
        self.lines.append((now, clip))
        self.until = now + clip.seconds

    def track(self, timeline, seconds, out):
        """Write the narration as one WAV of ``seconds``, each line where ``timeline`` puts its start."""
        audio = np.zeros(int(seconds * SAMPLE_RATE) + 1, dtype=np.float32)
        for start, clip in self.lines:
            samples = read_wav(clip.path)
            at = max(0, int(round(timeline(start) * SAMPLE_RATE)))
            end = min(len(audio), at + len(samples))
            audio[at:end] += samples[:end - at]
        write_wav(out, audio)  # the encoder brings it to a standard loudness
        return out

    def subtitles(self, timeline, out):
        """Write the lines as SRT subtitles (closed captions for YouTube), split into cues of two short lines."""
        cues = []
        for start, clip in self.lines:
            t, parts = max(0.0, timeline(start)), cue_texts(clip.text)
            total = sum(len(p) for p in parts)
            for part in parts:
                length = clip.seconds * len(part) / total
                # one line, or two of about the same length
                cues.append((t, t + length, part if len(part) <= 42 else textwrap.fill(part, len(part) // 2 + 8)))
                t += length
        stamp = lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d},{int(s * 1000 % 1000):03d}"
        out.write_text("".join(f"{i}\n{stamp(a)} --> {stamp(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(cues, 1)),
                       encoding="utf-8")
        return out

    def check(self):
        """Transcribe each line with Whisper; return ``[(text, heard, [(said, heard)...])]`` for those heard differently.

        Returns None when faster-whisper is not installed.
        """
        load_system_cpp_runtime()
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # the model cache copies files on Windows
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return None
        model, misheard, seen = None, [], set()
        for _, clip in self.lines:
            if clip.path in seen:
                continue
            seen.add(clip.path)
            heard_path = clip.path.with_suffix(f".{WHISPER_MODEL}.txt")
            if heard_path.exists():
                heard = heard_path.read_text(encoding="utf-8")
            else:
                model = model or WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
                segments, _ = model.transcribe(str(clip.path), language="en", beam_size=5,
                                               condition_on_previous_text=False)
                heard = " ".join(s.text.strip() for s in segments)
                heard_path.write_text(heard, encoding="utf-8")
            differences = word_differences(clip.text, heard)
            if differences:
                misheard.append((clip.text, heard, differences))
        return misheard

    def report(self):
        """Print what Whisper heard differently from the script."""
        misheard = self.check()
        lines = len({clip.path for _, clip in self.lines})
        if misheard is None:
            print("narration not checked: pip install faster-whisper to have Whisper listen to it")
        elif not misheard:
            print(f"narration: Whisper heard all {lines} lines as written")
        else:
            print(f"narration: Whisper heard {len(misheard)} of {lines} lines differently. Listen to them; respell a "
                  f"word the voice gets wrong in SPEAK_AS (narration.py), or reword the line:")
            for text, heard, differences in misheard:
                print(f"  said:  {text}\n  heard: {heard}\n  " + "; ".join(f"{a!r} -> {b!r}" for a, b in differences))


def cue_texts(text, limit=84):
    """``text`` in pieces of at most ``limit`` characters, split at sentences, then clauses, then words."""
    parts = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        while len(sentence) > limit:
            cut = max(sentence.rfind(mark, 0, limit) for mark in (", ", ": ", "; "))
            if cut < limit // 3:  # no clause, or one too short to stand alone
                cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(sentence[:cut + 1].strip())
            sentence = sentence[cut + 1:].strip()
        if sentence:
            parts.append(sentence)
    return parts


def word_differences(said, heard):
    """The words of ``said`` that ``heard`` has differently, ignoring case, punctuation and spacing."""
    words = lambda s: re.findall(r"[a-z0-9]+", s.lower())
    a, b = words(said), words(heard)
    differences = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal" and "".join(a[i1:i2]) != "".join(b[j1:j2]):
            differences.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return differences


def main():
    parser = argparse.ArgumentParser(description="Speak a line in each of a few voices, to pick one.")
    parser.add_argument("text", nargs="?", default="IvoryOS 1.8 gives dictionary arguments a table editor: "
                        "one row per dye, here 60 microliters of yellow and 40 of blue.")
    parser.add_argument("--voices", default=",".join(SAMPLE_VOICES), help="comma-separated Kokoro voices")
    parser.add_argument("--out", type=Path, default=HERE / "output" / "voice-samples")
    args = parser.parse_args()
    for voice in args.voices.split(","):
        clip = Narrator(voice=voice.strip()).prepare(args.text)
        out = args.out / f"{voice.strip()}.wav"
        write_wav(out, read_wav(clip.path))
        print(f"{out} ({clip.seconds:.1f} s)")


if __name__ == "__main__":
    main()
