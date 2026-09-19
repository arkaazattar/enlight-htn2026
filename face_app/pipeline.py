"""Keep microphone capture and provider requests off the camera loop."""

from __future__ import annotations

import queue
import threading

from .audio import AudioError
from .speech import SpeechClip, SpeechError, SpeechSegmenter, Transcript


class VoicePipeline:
    def __init__(self, microphone, transcriber):
        self.microphone = microphone
        self.transcriber = transcriber
        self.clips: queue.Queue[SpeechClip] = queue.Queue(maxsize=4)
        self.submitted: queue.Queue[tuple[SpeechClip, str | None, str]] = queue.Queue(maxsize=4)
        self.completed: queue.Queue[tuple[SpeechClip, str | None, str, Transcript]] = queue.Queue(maxsize=4)
        self.notices: queue.Queue[str] = queue.Queue(maxsize=20)
        self.stop = threading.Event()
        self.capture_thread = threading.Thread(target=self._capture, daemon=True)
        self.transcribe_thread = threading.Thread(target=self._transcribe, daemon=True)
        self.capture_thread.start()
        self.transcribe_thread.start()

    def _notice(self, message: str) -> None:
        try:
            self.notices.put_nowait(message)
        except queue.Full:
            pass

    def _capture(self) -> None:
        try:
            segmenter = SpeechSegmenter(self.microphone.clock_source)
            while not self.stop.is_set():
                block = self.microphone.read()
                if block is None:
                    continue
                clip = segmenter.feed(block)
                if clip is not None:
                    try:
                        self.clips.put_nowait(clip)
                    except queue.Full:
                        self._notice("Speech queue is full; a clip was dropped.")
        except (AudioError, SpeechError) as exc:
            if not self.stop.is_set():
                self._notice(str(exc))

    def submit(self, clip: SpeechClip, person_id: str | None, reason: str) -> None:
        try:
            self.submitted.put_nowait((clip, person_id, reason))
        except queue.Full:
            self._notice("Transcription queue is full; a clip was dropped.")

    def _transcribe(self) -> None:
        while not self.stop.is_set():
            try:
                clip, person_id, reason = self.submitted.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                transcript = self.transcriber.transcribe(clip)
                if transcript.text:
                    self.completed.put((clip, person_id, reason, transcript), timeout=0.5)
            except (SpeechError, queue.Full) as exc:
                self._notice(str(exc))

    def close(self) -> None:
        self.stop.set()
        self.microphone.close()
        self.capture_thread.join(timeout=2)
        self.transcribe_thread.join(timeout=2)
