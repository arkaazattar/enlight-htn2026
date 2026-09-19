"""Continuous speech segmentation and ElevenLabs batch transcription."""

from __future__ import annotations

import io
import wave
from collections import deque
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Transcript:
    text: str
    speakers: tuple[str, ...]
    words: tuple[dict, ...]


def resolve_speaker(person_id: str | None, reason: str, transcript: Transcript) -> tuple[str | None, str]:
    if len(transcript.speakers) != 1 or not transcript.words or any(
        word["speaker_id"] is None for word in transcript.words
    ):
        return None, "multiple or unidentified audio speakers"
    return person_id, reason


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
        if self.last_end is not None and abs(block.start - self.last_end) > 0.1:
            self.preroll.clear()
            self.blocks = []
            self.voiced = []
            self.quiet_seconds = 0.0
        self.last_end = block.end
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
