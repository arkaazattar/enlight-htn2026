"""Continuous speech segmentation and ElevenLabs batch transcription."""

from __future__ import annotations

import io
import math
import uuid
import wave
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from .audio import AudioBlock, SAMPLE_RATE


class SpeechError(Exception):
    """Speech segmentation or transcription failed."""


@dataclass(frozen=True)
class SpeechClip:
    pcm: bytes
    start: float
    end: float
    voiced: tuple[tuple[float, float], ...]
    clock_source: str
    clip_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class Transcript:
    text: str
    speakers: tuple[str, ...]
    words: tuple[dict, ...]


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
    attribution: str = "pending visual attribution"


def split_turns(clip: SpeechClip, transcript: Transcript) -> tuple[SpeechTurn, ...]:
    """Keep clip-local diarization, translating word offsets to capture time."""
    def fallback(reason):
        return (SpeechTurn(
            f"{clip.clip_id}:0", clip.clip_id, clip.recorded_at, transcript.text,
            None, clip.start, clip.end, attribution=reason,
        ),)

    if not transcript.words:
        return fallback("no word timestamps")
    captured_duration = clip.end - clip.start
    audio_duration = len(clip.pcm) / (SAMPLE_RATE * 2) if clip.pcm else captured_duration
    if captured_duration <= 0 or audio_duration <= 0 or not .9 <= captured_duration / audio_duration <= 1.1:
        return fallback("audio capture timing gap")
    # Scribe may put the final word slightly past the WAV boundary. The WAV
    # sample count is authoritative for offsets; map it onto capture time.
    overflow = min(.5, max(.2, audio_duration * .05))
    words = []
    for word in transcript.words:
        start, end = word.get("start"), word.get("end")
        if (
            not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not math.isfinite(start) or not math.isfinite(end)
            or start < -.05 or end <= start or end > audio_duration + overflow
        ):
            return fallback("invalid word timestamps")
        start, end = max(0., start), min(audio_duration, end)
        if end <= start:
            return fallback("invalid word timestamps")
        words.append({**word, "start": start, "end": end})
    groups = []
    for word in sorted(words, key=lambda item: item["start"]):
        if (
            not groups or groups[-1][-1].get("speaker_id") != word.get("speaker_id")
            or word["start"] - groups[-1][-1]["end"] > .8
        ):
            groups.append([])
        groups[-1].append(word)
    turns = []
    scale = captured_duration / audio_duration
    for index, words in enumerate(groups):
        intervals = tuple((clip.start + word["start"] * scale, clip.start + word["end"] * scale) for word in words)
        turns.append(SpeechTurn(
            f"{clip.clip_id}:{index}", clip.clip_id, clip.recorded_at,
            " ".join(word["text"].strip() for word in words).strip(), words[0].get("speaker_id"),
            min(a for a, _ in intervals), max(b for _, b in intervals), intervals,
            attribution="pending visual attribution" if words[0].get("speaker_id") is not None else "unidentified audio speaker",
        ))
    for index, turn in enumerate(turns):
        if any(
            other.speaker_id != turn.speaker_id
            and any(min(b, d) - max(a, c) > .02 for a, b in turn.intervals for c, d in other.intervals)
            for other in turns
        ):
            turns[index] = replace(turn, attribution="overlapping audio speakers")
    return tuple(turns)


class SpeechSegmenter:
    """VAD with 300 ms pre-roll, 800 ms end silence, and 15 second cap."""

    def __init__(self, clock_source: str, vad=None):
        if vad is None:
            try:
                import webrtcvad
            except ImportError as exc:
                raise SpeechError("Speech segmentation is missing; install requirements.txt.") from exc
            vad = webrtcvad.Vad(2)
        self.vad = vad
        self.clock_source = clock_source
        self.preroll: deque[AudioBlock] = deque(maxlen=15)
        self.blocks: list[AudioBlock] = []
        self.voiced: list[tuple[float, float]] = []
        self.quiet_seconds = 0.0
        self.last_end: float | None = None

    def feed(self, block: AudioBlock) -> SpeechClip | None:
        if len(block.pcm) != 640:
            raise SpeechError("Microphone must deliver 20 ms of 16 kHz mono 16-bit PCM per block.")
        if block.discontinuity or (self.last_end is not None and abs(block.start - self.last_end) > 0.1):
            self.preroll.clear()
            self.blocks = []
            self.voiced = []
            self.quiet_seconds = 0.0
        self.last_end = block.end
        if block.discontinuity:
            return None
        speaking = bool(self.vad.is_speech(block.pcm, SAMPLE_RATE))
        if not self.blocks:
            if not speaking:
                self.preroll.append(block)
                return None
            self.blocks = [*self.preroll]
            self.preroll.clear()
        self.blocks.append(block)
        if speaking:
            self.voiced.append((block.start, block.end))
            self.quiet_seconds = 0.0
        else:
            self.quiet_seconds += block.end - block.start

        duration = self.blocks[-1].end - self.blocks[0].start
        if self.quiet_seconds < 0.8 and duration < 15:
            return None
        completed = None
        if len(self.voiced) >= 20:
            completed = SpeechClip(
                b"".join(item.pcm for item in self.blocks), self.blocks[0].start,
                self.blocks[-1].end, tuple(self.voiced), self.clock_source,
            )
        if duration < 15:
            self.preroll.extend(self.blocks[-15:])
        else:
            self.preroll.clear()
        self.blocks = []
        self.voiced = []
        self.quiet_seconds = 0.0
        return completed


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def parse_transcript(response) -> Transcript:
    words = []
    speakers = set()
    for word in _field(response, "words", []) or []:
        kind = _field(word, "type")
        if kind != "word":
            continue
        speaker = _field(word, "speaker_id")
        if speaker is not None:
            speakers.add(str(speaker))
        words.append({
            "text": str(_field(word, "text", "")),
            "start": _field(word, "start"),
            "end": _field(word, "end"),
            "speaker_id": str(speaker) if speaker is not None else None,
        })
    return Transcript(str(_field(response, "text", "")).strip(), tuple(sorted(speakers)), tuple(words))


class ElevenLabsTranscriber:
    def __init__(self, api_key: str):
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as exc:
            raise SpeechError("ElevenLabs SDK is missing; install requirements.txt.") from exc
        self.client = ElevenLabs(api_key=api_key, timeout=30)

    def transcribe(self, clip: SpeechClip) -> Transcript:
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(SAMPLE_RATE)
            writer.writeframes(clip.pcm)
        output.seek(0)
        output.name = "speech.wav"
        try:
            result = self.client.speech_to_text.convert(
                file=output, model_id="scribe_v2", diarize=True,
                tag_audio_events=False, timestamps_granularity="word",
            )
        except Exception as exc:
            raise SpeechError(f"ElevenLabs transcription failed: {exc}") from exc
        return parse_transcript(result)
