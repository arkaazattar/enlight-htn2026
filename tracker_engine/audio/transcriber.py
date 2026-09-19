from __future__ import annotations

import io
import os
import queue
import threading
import time
import uuid
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import sounddevice as sd
import webrtcvad
from elevenlabs.client import ElevenLabs


SAMPLE_RATE = 16_000
BLOCK_MS = 20
BLOCK_SAMPLES = SAMPLE_RATE * BLOCK_MS // 1000
BLOCK_BYTES = BLOCK_SAMPLES * 2

class AudioError(Exception):
    """Microphone could not be opened or read."""

class SpeechError(Exception):
    """VAD or ElevenLabs transcription failed."""


@dataclass(frozen=True)
class SpeechTurn:
    turn_id: str
    clip_id: str
    recorded_at: str
    text: str
    speaker_id: str | None
    start: float
    end: float
    intervals: tuple[tuple[float, float], ...] = ()
    person_id: str | None = None


# ---------------------------------------------------------------------------
# Microphone — streams raw PCM blocks
# ---------------------------------------------------------------------------

class Microphone:
    """Opens the default (or specified) system microphone and yields 20 ms PCM blocks."""

    def __init__(self, device: int | None = None) -> None:
        self._queue: queue.Queue[bytes] = queue.Queue()
        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                blocksize=BLOCK_SAMPLES, device=device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            raise AudioError(f"Could not open microphone: {exc}") from exc

    def _callback(self, indata, frames, time_info, status):
        self._queue.put(bytes(indata))

    def read(self) -> bytes:
        """Return the next 20 ms PCM block (blocks until available)."""
        return self._queue.get()

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SpeechSegmenter — WebRTC VAD → SpeechClip assembly
# ---------------------------------------------------------------------------

@dataclass
class _SpeechClip:
    pcm: bytes
    start: float
    end: float
    voiced: tuple[tuple[float, float], ...]
    clip_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class _SpeechSegmenter:
    """VAD with 300 ms pre-roll, 650 ms end-silence, 15 s cap."""

    def __init__(self) -> None:
        self._vad = webrtcvad.Vad(1)
        self._preroll: deque[tuple[bytes, float, float]] = deque(maxlen=15)
        self._blocks: list[tuple[bytes, float, float]] = []   # (pcm, start, end)
        self._voiced: list[tuple[float, float]] = []
        self._quiet = 0.0
        self._last_end: float | None = None

    def feed(self, pcm: bytes, start: float, end: float) -> _SpeechClip | None:
        """Feed one 20 ms block; returns a completed clip or None."""
        # Detect discontinuity
        if self._last_end is not None and abs(start - self._last_end) > 0.1:
            self._reset()
        self._last_end = end

        speaking = bool(self._vad.is_speech(pcm, SAMPLE_RATE))

        if not self._blocks:
            if not speaking:
                self._preroll.append((pcm, start, end))
                return None
            # Speech started — include pre-roll
            self._blocks = list(self._preroll)
            self._preroll.clear()

        self._blocks.append((pcm, start, end))
        if speaking:
            self._voiced.append((start, end))
            self._quiet = 0.0
        else:
            self._quiet += end - start

        duration = self._blocks[-1][2] - self._blocks[0][1]
        if self._quiet < 0.65 and duration < 15:
            return None

        clip = None
        if len(self._voiced) >= 8:
            clip = _SpeechClip(
                pcm=b"".join(b for b, _, _ in self._blocks),
                start=self._blocks[0][1],
                end=self._blocks[-1][2],
                voiced=tuple(self._voiced),
            )

        self._preroll.extend(self._blocks[-15:])
        self._reset(keep_preroll=False)
        return clip

    def _reset(self, keep_preroll: bool = True) -> None:
        if not keep_preroll:
            self._preroll.clear()
        self._blocks = []
        self._voiced = []
        self._quiet = 0.0


# ---------------------------------------------------------------------------
# ElevenLabs transcription
# ---------------------------------------------------------------------------

def _transcribe(api_key: str, client, clip: _SpeechClip) -> list[SpeechTurn]:
    """Call ElevenLabs and return split SpeechTurns."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(clip.pcm)
    buf.seek(0)
    buf.name = "speech.wav"

    try:
        model_id = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1_base")
        result = client.speech_to_text.convert(
            file=buf, model_id=model_id, diarize=True,
            tag_audio_events=False, timestamps_granularity="word",
        )
    except Exception as exc:
        raise SpeechError(f"ElevenLabs failed: {exc}") from exc

    # Parse words
    words = []
    for word in (getattr(result, "words", None) or []):
        kind = getattr(word, "type", None)
        if kind != "word":
            continue
        words.append({
            "text": str(getattr(word, "text", "")),
            "start": getattr(word, "start", None),
            "end": getattr(word, "end", None),
            "speaker_id": str(s) if (s := getattr(word, "speaker_id", None)) is not None else None,
        })

    if not words:
        full_text = str(getattr(result, "text", "")).strip()
        if not full_text:
            return []
        return [SpeechTurn(
            turn_id=f"{clip.clip_id}:0", clip_id=clip.clip_id,
            recorded_at=clip.recorded_at, text=full_text,
            speaker_id=None, start=clip.start, end=clip.end,
        )]

    # Group consecutive words by speaker
    groups: list[list[dict]] = []
    for word in sorted(words, key=lambda w: w["start"]):
        if (
            not groups
            or groups[-1][-1].get("speaker_id") != word.get("speaker_id")
            or word["start"] - groups[-1][-1]["end"] > 0.8
        ):
            groups.append([])
        groups[-1].append(word)

    turns = []
    for i, group in enumerate(groups):
        intervals = tuple((clip.start + w["start"], clip.start + w["end"]) for w in group)
        turns.append(SpeechTurn(
            turn_id=f"{clip.clip_id}:{i}",
            clip_id=clip.clip_id,
            recorded_at=clip.recorded_at,
            text=" ".join(w["text"].strip() for w in group).strip(),
            speaker_id=group[0].get("speaker_id"),
            start=min(s for s, _ in intervals),
            end=max(e for _, e in intervals),
            intervals=intervals,
        ))
    return turns


# ---------------------------------------------------------------------------
# SpeechPipeline — runs mic + VAD + ElevenLabs in a background thread
# ---------------------------------------------------------------------------

class SpeechPipeline:
    """Captures mic audio, segments speech, and transcribes in background.

    Completed SpeechTurns are placed on `self.turns` (a Queue).
    Notices (status strings) are placed on `self.notices` (a Queue).
    """

    def __init__(self, api_key: str, device: int | None = None) -> None:
        self._client = ElevenLabs(api_key=api_key, timeout=30)
        self._mic = Microphone(device=device)
        self._segmenter = _SpeechSegmenter()
        self.turns: queue.Queue[list[SpeechTurn]] = queue.Queue()
        self.notices: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="SpeechPipeline")
        # Monotonic capture counter for block timestamps
        self._cursor = 0.0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._mic.close()

    def _run(self) -> None:
        t0 = time.perf_counter()
        self._cursor = t0
        block_dur = BLOCK_BYTES / 2 / SAMPLE_RATE  # ≈ 0.02 s

        while not self._stop.is_set():
            try:
                pcm = self._mic.read()
            except Exception as exc:
                self.notices.put(f"Mic error: {exc}")
                break
            start = self._cursor
            end = start + block_dur
            self._cursor = end

            try:
                clip = self._segmenter.feed(pcm, start, end)
            except SpeechError as exc:
                self.notices.put(f"VAD error: {exc}")
                continue

            if clip is None:
                continue

            # Transcribe synchronously (we're in the bg thread)
            try:
                self.notices.put("Transcribing speech...")
                speech_turns = _transcribe("", self._client, clip)
                if speech_turns:
                    self.turns.put(speech_turns)
            except SpeechError as exc:
                self.notices.put(f"Transcription error: {exc}")
