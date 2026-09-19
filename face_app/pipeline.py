"""Keep microphone capture and provider requests off the camera loop."""

from __future__ import annotations

import queue
import threading

from .audio import AudioError
from .speech import SpeechClip, SpeechError, SpeechSegmenter, split_turns


class VoicePipeline:
    def __init__(self, microphone, transcriber):
        self.microphone = microphone
        self.transcriber = transcriber
        self.clips: queue.Queue[SpeechClip] = queue.Queue(maxsize=4)
        self.submitted = queue.Queue(maxsize=4)
        self.completed = queue.Queue(maxsize=4)
        self.notices: queue.Queue[str] = queue.Queue(maxsize=20)
        self.stop = threading.Event()
        self.transcribing = False
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
                if block.discontinuity:
                    self._notice("Microphone timing gap; interrupted speech was discarded.")
                clip = segmenter.feed(block)
                if clip is not None:
                    try:
                        self.clips.put_nowait(clip)
                    except queue.Full:
                        self._notice("Speech queue is full; a clip was dropped.")
        except (AudioError, SpeechError) as exc:
            if not self.stop.is_set():
                self._notice(str(exc))

    def submit(self, clip: SpeechClip, evidence) -> None:
        try:
            self.submitted.put_nowait((clip, evidence))
        except queue.Full:
            self._notice("Transcription queue is full; a clip was dropped.")

    def _transcribe(self) -> None:
        while not self.stop.is_set():
            try:
                clip, evidence = self.submitted.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.transcribing = True
                self._notice("Transcribing completed speech.")
                transcript = self.transcriber.transcribe(clip)
                if transcript.text:
                    turns = evidence.attribute_turns(clip, split_turns(clip, transcript))
                    self.completed.put(turns, timeout=0.5)
            except (SpeechError, queue.Full) as exc:
                self._notice(str(exc))
            finally:
                self.transcribing = False
                clip = None  # Release PCM as soon as the provider request is finished.

    def close(self) -> int:
        pending = self.clips.qsize() + self.submitted.qsize() + self.completed.qsize() + int(self.transcribing)
        self.stop.set()
        self.microphone.close()
        self.capture_thread.join(timeout=2)
        self.transcribe_thread.join(timeout=2)
        return pending
