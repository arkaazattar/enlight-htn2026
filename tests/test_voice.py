"""Tests for segmentation, attribution, and the temporary Gemini handoff."""

from __future__ import annotations

import base64
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from face_app.audio import AudioBlock, AudioError, WindowsMicrophone
from face_app.camera import run_camera
from face_app.context import Fact, GeminiAnalyzer, IdentityAnalysis, PersonContextStore, VoiceEvent, VoiceEventStore
from face_app.speech import ElevenLabsTranscriber, SpeechClip, SpeechSegmenter, Transcript, parse_transcript, resolve_speaker
from face_app.storage import PersonStore
from face_app.visual import AutoEnrollment, FrameEvidence, VisualHistory
from face_app.wsl_camera import WindowsCameraSource


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAACklEQVQIHWMAAgAABAABDTukuQAAAABJRU5ErkJggg==")


class FakeVad:
    def is_speech(self, pcm: bytes, sample_rate: int) -> bool:
        return pcm[0] == 1


class SpeechTests(unittest.TestCase):
    def test_continuous_blocks_close_one_speech_clip_after_silence(self):
        segmenter = SpeechSegmenter("native", FakeVad())
        clips = []
        for index in range(80):
            talking = 5 <= index < 35
            pcm = bytes([1 if talking else 0]) + bytes(639)
            block = AudioBlock(pcm, index * 0.02, (index + 1) * 0.02)
            clip = segmenter.feed(block)
            if clip:
                clips.append(clip)
        self.assertEqual(len(clips), 1)
        self.assertAlmostEqual(clips[0].start, 0)
        self.assertEqual(len(clips[0].voiced), 30)
        self.assertGreaterEqual(clips[0].end, 1.48)

    def test_diarization_controls_face_attribution(self):
        response = {"text": "Hello Jon", "words": [
            {"type": "word", "text": "Hello", "start": 0, "end": .2, "speaker_id": "speaker_0"},
            {"type": "word", "text": "Jon", "start": .3, "end": .5, "speaker_id": "speaker_1"},
        ]}
        transcript = parse_transcript(response)
        self.assertEqual(transcript.speakers, ("speaker_0", "speaker_1"))
        self.assertIsNone(resolve_speaker("person_123456789abc", "visible", transcript)[0])
        response["words"][1]["speaker_id"] = "speaker_0"
        transcript = parse_transcript(response)
        self.assertEqual(resolve_speaker("person_123456789abc", "visible", transcript)[0], "person_123456789abc")

    def test_elevenlabs_adapter_sends_wav_with_diarization(self):
        transcriber = ElevenLabsTranscriber("test-key")
        clip = SpeechClip(bytes(640), 0., .02, ((0., .02),), "native")
        response = {"text": "hello", "words": [{"type": "word", "text": "hello", "start": 0, "end": .02, "speaker_id": "speaker_0"}]}
        with patch.object(transcriber.client.speech_to_text, "convert", return_value=response) as convert:
            transcript = transcriber.transcribe(clip)
        self.assertEqual(transcript.text, "hello")
        kwargs = convert.call_args.kwargs
        self.assertEqual(kwargs["model_id"], "scribe_v2")
        self.assertTrue(kwargs["diarize"])
        self.assertEqual(kwargs["file"].getvalue()[:4], b"RIFF")


class BridgeTests(unittest.TestCase):
    def test_timestamped_windows_audio_and_camera_packets(self):
        microphone = object.__new__(WindowsMicrophone)
        audio_parts = iter([struct.pack("!I", 640), struct.pack("!d", 10.0), bytes(640)])
        microphone._read_exact = lambda _count, _timeout: next(audio_parts)
        block = microphone.read()
        self.assertAlmostEqual(block.start, 9.98)
        self.assertEqual(len(block.pcm), 640)

        source = object.__new__(WindowsCameraSource)
        ok, jpeg = cv2.imencode(".jpg", np.zeros((4, 4, 3), dtype=np.uint8))
        self.assertTrue(ok)
        payload = jpeg.tobytes()
        image_parts = iter([struct.pack("!I", len(payload)), struct.pack("!d", 10.0), payload])
        source._read_exact = lambda _count: next(image_parts)
        ready, frame = source.read()
        self.assertTrue(ready)
        self.assertEqual(frame.shape, (4, 4, 3))
        self.assertEqual(source.capture_time, 10.0)


class VisualTests(unittest.TestCase):
    def make_history(self, face_count=1, moving=True):
        history = VisualHistory("native")
        voiced = tuple((index / 50, (index + 1) / 50) for index in range(25, 75))
        clip = SpeechClip(b"", 0, 2.3, voiced, "native")
        for index in range(24):
            at = index / 10
            jaw = .05 if at < .5 or at > 1.5 or not moving else (.22 if index % 2 else .42)
            history.add(FrameEvidence(at, face_count, "person_123456789abc" if face_count else None, jaw))
        return history, clip

    def test_single_visible_speaking_face_is_attributed(self):
        history, clip = self.make_history()
        self.assertEqual(history.attribute(clip)[0], "person_123456789abc")
        history.frames.append(FrameEvidence(1.0, 2, None, None))
        self.assertIsNone(history.attribute(clip)[0])

    def test_offscreen_voice_and_clock_mismatch_are_unassigned(self):
        history, clip = self.make_history(moving=False)
        self.assertIsNone(history.attribute(clip)[0])
        history, clip = self.make_history()
        wrong_clock = SpeechClip(clip.pcm, clip.start, clip.end, clip.voiced, "windows")
        self.assertIsNone(history.attribute(wrong_clock)[0])

    def test_auto_enrollment_needs_stable_isolated_unknown_and_blocks_duplicates(self):
        tracker = AutoEnrollment()
        feature = np.array([1., 0.], dtype=np.float32)
        unknown = SimpleNamespace(person_id=None, face=[0, 0, 100, 100], feature=feature)
        for index in range(31):
            ready = tracker.update([unknown], index * .1, {}, .363)
        self.assertTrue(ready)
        tracker.mark_enrolled(feature)
        self.assertFalse(tracker.update([unknown], 4., {}, .363))
        tracker.update([], 4.1, {}, .363)
        tracker.update([], 5., {}, .363)
        self.assertFalse(tracker.update([unknown], 5.1, {"saved": feature}, .363))
        newcomer = SimpleNamespace(person_id=None, face=[0, 0, 100, 100], feature=np.array([0., 1.], dtype=np.float32))
        tracker = AutoEnrollment()
        tracker.mark_enrolled(feature)
        for index in range(31):
            ready = tracker.update([newcomer], 6.0 + index * .1, {"saved": feature}, .363)
        self.assertTrue(ready)


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.people = PersonStore(self.root)
        self.person = self.people.enroll(PNG)
        self.events = VoiceEventStore(self.root)
        self.context = PersonContextStore(self.root)

    def add_event(self, suffix):
        event = VoiceEvent(suffix, "2026-09-19T00:00:00+00:00", "Jon is my name", ("speaker_0",), (), self.person.id, "one visible speaking face", 1., 2.)
        self.events.append(event)
        return event

    def test_replay_facts_naming_and_explicit_correction(self):
        first, second = self.add_event("one"), self.add_event("two")
        self.assertEqual(len(VoiceEventStore(self.root).for_person(self.person.id)), 2)
        analysis = IdentityAnalysis("Jon", (first.id, second.id), False, (Fact("Likes music", (first.id,)),))
        outcome = self.context.apply(self.person.id, self.events.for_person(self.person.id), analysis, self.people)
        self.assertIn("Named", outcome)
        self.assertTrue((self.root / "faces" / "Jon.png").is_file())
        self.assertEqual(PersonContextStore(self.root).facts(self.person.id)[0].text, "Likes music")
        self.assertFalse(self.context.needs_processing(self.person.id, self.events.for_person(self.person.id)))

        third, fourth = self.add_event("three"), self.add_event("four")
        correction = IdentityAnalysis("Jonathan", (third.id, fourth.id), False, ())
        self.context.apply(self.person.id, self.events.for_person(self.person.id), correction, self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jon")
        correction = IdentityAnalysis("Jonathan", (third.id, fourth.id), True, ())
        self.context.apply(self.person.id, self.events.for_person(self.person.id), correction, self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jonathan")
        self.assertTrue((self.root / "faces" / "Jonathan.png").is_file())

    def test_one_clip_unassigned_evidence_and_conflicts_do_not_name(self):
        first = self.add_event("one")
        analysis = IdentityAnalysis("Jon", (first.id, "unassigned"), False, ())
        self.context.apply(self.person.id, [first], analysis, self.people)
        self.assertIsNone(self.people.get(self.person.id).name)
        second = self.add_event("two")
        other = self.people.enroll(PNG)
        self.people.assign_name(other.id, "Jon")
        outcome = self.context.apply(self.person.id, [first, second], IdentityAnalysis("Jon", (first.id, second.id), False, ()), self.people)
        self.assertIn("not assigned", outcome)
        self.assertIsNone(self.people.get(self.person.id).name)

    def test_gemini_adapter_validates_structured_response(self):
        first, second = self.add_event("one"), self.add_event("two")
        analyzer = GeminiAnalyzer("test-key")
        result = {"name": "Jon", "evidence_ids": [first.id, second.id], "explicit_correction": False, "facts": []}
        with patch.object(analyzer.client.models, "generate_content", return_value=SimpleNamespace(text=json.dumps(result))) as generate:
            analysis = analyzer.analyze(self.person.id, [first, second], [])
        self.assertEqual(analysis.name, "Jon")
        self.assertEqual(generate.call_args.kwargs["model"], "gemini-2.5-flash")
        self.assertEqual(generate.call_args.kwargs["config"].response_mime_type, "application/json")


class CameraFallbackTests(unittest.TestCase):
    def test_face_camera_stays_usable_when_microphone_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = SimpleNamespace(
                isOpened=lambda: True,
                read=lambda: (True, np.zeros((120, 160, 3), dtype=np.uint8)),
                release=lambda: None,
            )
            engine = SimpleNamespace(gallery={}, observe=lambda _frame, _threshold: [])
            with patch.dict(os.environ, {"ELEVENLABSKEY": "dummy"}, clear=True), \
                 patch("face_app.camera.platform.release", return_value="Linux"), \
                 patch("face_app.camera.FaceEngine", return_value=engine), \
                 patch("face_app.camera.cv2.VideoCapture", return_value=capture), \
                 patch("face_app.camera.open_microphone", side_effect=AudioError("no input")), \
                 patch("face_app.camera.cv2.imshow"), \
                 patch("face_app.camera.cv2.waitKey", return_value=ord("q")), \
                 patch("face_app.camera.cv2.destroyAllWindows"):
                run_camera(0, .363, Path(directory), Path(directory) / "data")


if __name__ == "__main__":
    unittest.main()
