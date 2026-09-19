"""Capture, tracking, per-turn attribution, and camera integration."""

from __future__ import annotations

import base64
import os
import queue
import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from face_app.audio import AudioBlock, AudioError, WindowsMicrophone, capture_interval
from face_app.camera import Observation, run_camera
from face_app.context import IdentityProposal
from face_app.speech import ElevenLabsTranscriber, SpeechClip, SpeechSegmenter, SpeechTurn, parse_transcript, split_turns
from face_app.storage import PersonStore
from face_app.visual import FaceEvidence, FaceTracker, FrameEvidence, VisualHistory, match_mouths
from face_app.wsl_camera import WindowsCameraSource

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAACklEQVQIHWMAAgAABAABDTukuQAAAABJRU5ErkJggg==")
A, B = "person_111111111111", "person_222222222222"


def observation(x, feature=(1., 0.), person_id=None):
    return Observation(np.array([x, 0., 100., 100.]), np.zeros((112, 112, 3), np.uint8), np.array(feature), person_id)


class FakeVad:
    def is_speech(self, pcm, _sample_rate):
        return pcm[0] == 1


class SpeechTests(unittest.TestCase):
    def test_segmentation_and_capture_gaps(self):
        segmenter = SpeechSegmenter("native", FakeVad())
        clips = []
        for index in range(80):
            talking = 5 <= index < 35
            clip = segmenter.feed(AudioBlock(bytes([talking]) + bytes(639), index * .02, (index + 1) * .02))
            if clip:
                clips.append(clip)
        self.assertEqual(len(clips), 1)
        self.assertAlmostEqual(clips[0].start, 0)
        self.assertGreaterEqual(clips[0].end, 1.48)
        segmenter = SpeechSegmenter("native", FakeVad())
        for index in range(30):
            segmenter.feed(AudioBlock(bytes([1]) + bytes(639), index * .02, (index + 1) * .02))
        segmenter.feed(AudioBlock(bytes(640), .6, .62, True))
        self.assertEqual(segmenter.blocks, [])
        self.assertEqual(segmenter.voiced, [])

    def test_turns_preserve_clip_ids_absolute_times_and_speaker_changes(self):
        clip = SpeechClip(b"", 10, 15, ((10.5, 13),), "native", "clip")
        transcript = parse_transcript({"text": "I am Jon. Hi Jon.", "words": [
            {"type": "word", "text": "I am Jon.", "start": .5, "end": 1.5, "speaker_id": "speaker_0"},
            {"type": "word", "text": "Hi Jon.", "start": 2, "end": 3, "speaker_id": "speaker_1"},
        ]})
        turns = split_turns(clip, transcript)
        self.assertEqual([turn.speaker_id for turn in turns], ["speaker_0", "speaker_1"])
        self.assertEqual([turn.clip_id for turn in turns], ["clip", "clip"])
        self.assertEqual(turns[0].start, 10.5)
        self.assertNotEqual(turns[0].turn_id, turns[1].turn_id)

    def test_overlap_missing_speakers_and_invalid_timestamps_are_rejected(self):
        clip = SpeechClip(b"", 0, 4, (), "native")
        words = [
            {"type": "word", "text": "one", "start": .5, "end": 2, "speaker_id": "a"},
            {"type": "word", "text": "two", "start": 1, "end": 3, "speaker_id": "b"},
        ]
        turns = split_turns(clip, parse_transcript({"text": "one two", "words": words}))
        self.assertTrue(all(turn.attribution == "overlapping audio speakers" for turn in turns))
        words[0]["start"] = float("nan")
        self.assertEqual(split_turns(clip, parse_transcript({"text": "one", "words": words}))[0].attribution, "invalid word timestamps")
        words = [{"type": "word", "text": "one", "start": 0, "end": 1, "speaker_id": None}]
        self.assertEqual(split_turns(clip, parse_transcript({"text": "one", "words": words}))[0].attribution, "unidentified audio speaker")

    def test_elevenlabs_uses_scribe_and_diarized_word_timestamps(self):
        transcriber = ElevenLabsTranscriber("test-key")
        clip = SpeechClip(bytes(640), 0., .02, ((0., .02),), "native")
        response = {"text": "hello", "words": [{"type": "word", "text": "hello", "start": 0, "end": .02, "speaker_id": "speaker_0"}]}
        with patch.object(transcriber.client.speech_to_text, "convert", return_value=response) as convert:
            self.assertEqual(transcriber.transcribe(clip).text, "hello")
        self.assertEqual(convert.call_args.kwargs["model_id"], "scribe_v2")
        self.assertTrue(convert.call_args.kwargs["diarize"])
        self.assertEqual(convert.call_args.kwargs["timestamps_granularity"], "word")
        self.assertEqual(convert.call_args.kwargs["file"].getvalue()[:4], b"RIFF")


class BridgeTests(unittest.TestCase):
    def test_adc_time_is_mapped_to_shared_monotonic_clock(self):
        start, end, valid = capture_interval(320, SimpleNamespace(currentTime=5.05, inputBufferAdcTime=5), 100)
        self.assertAlmostEqual(start, 99.95)
        self.assertAlmostEqual(end, 99.97)
        self.assertTrue(valid)
        self.assertFalse(capture_interval(320, None, 100)[2])
        first = capture_interval(320, SimpleNamespace(currentTime=5, inputBufferAdcTime=5), 100)
        second = capture_interval(320, SimpleNamespace(currentTime=5, inputBufferAdcTime=5.02), 100)
        self.assertTrue(second[2])
        self.assertAlmostEqual(first[1], second[0])
        self.assertFalse(capture_interval(320, SimpleNamespace(currentTime=5, inputBufferAdcTime=6), 100)[2])

    def test_timestamped_windows_audio_and_camera_packets(self):
        microphone = object.__new__(WindowsMicrophone)
        parts = iter([struct.pack("!I", 640), struct.pack("!d", 10.), b"\1", bytes(640)])
        microphone._read_exact = lambda *_args: next(parts)
        block = microphone.read()
        self.assertAlmostEqual(block.start, 9.98)
        self.assertTrue(block.discontinuity)
        source = object.__new__(WindowsCameraSource)
        _, jpeg = cv2.imencode(".jpg", np.zeros((4, 4, 3), np.uint8))
        payload = jpeg.tobytes()
        parts = iter([struct.pack("!I", len(payload)), struct.pack("!d", 10), payload])
        source._read_exact = lambda _count: next(parts)
        ready, frame = source.read()
        self.assertTrue(ready)
        self.assertEqual(frame.shape, (4, 4, 3))
        self.assertEqual(source.capture_time, 10.)


class TrackingTests(unittest.TestCase):
    def test_two_unknowns_enroll_independently_and_do_not_duplicate(self):
        tracker, gallery, enrolled = FaceTracker(), {}, []
        for index in range(50):
            observations = [observation(0), observation(250, (0., 1.))]
            if index % 2:
                observations.reverse()
            tracker.update(observations, index * .1)
            for obs in observations:
                if tracker.can_enroll(obs, index * .1, gallery, .363):
                    person = A if obs.feature[0] else B
                    gallery[person] = obs.feature.copy()
                    tracker.enrolled(obs, person)
                    enrolled.append(person)
        self.assertCountEqual(enrolled, [A, B])
        self.assertEqual({obs.person_id for obs in observations}, {A, B})

    def test_known_and_unknown_crossing_pauses_enrollment(self):
        tracker, gallery = FaceTracker(), {A: np.array([1., 0.])}
        for index in range(20):
            faces = [observation(0, person_id=A), observation(250, (0., 1.))]
            tracker.update(faces, index * .1)
            for face in faces:
                self.assertFalse(tracker.can_enroll(face, index * .1, gallery, .363))
        faces = [observation(100, person_id=A), observation(120, (0., 1.))]
        tracker.update(faces, 2)
        self.assertFalse(any(face.stable for face in faces))
        for index in range(21, 53):
            faces = [observation(0, person_id=A), observation(250, (0., 1.))]
            tracker.update(faces, index * .1)
            ready = tracker.can_enroll(faces[1], index * .1, gallery, .363)
        self.assertTrue(ready)
        self.assertFalse(tracker.can_enroll(faces[0], 5.3, gallery, .363))

    def test_near_gallery_match_cannot_enroll_and_three_faces_pause(self):
        tracker = FaceTracker()
        feature = (.34, np.sqrt(1 - .34 ** 2))
        for index in range(40):
            faces = [observation(0, feature)]
            tracker.update(faces, index * .1)
            self.assertFalse(tracker.can_enroll(faces[0], index * .1, {A: np.array([1., 0.])}, .363))
        faces = [observation(0), observation(250, (0., 1.)), observation(500, (-1., 0.))]
        tracker.update(faces, 4)
        self.assertFalse(any(face.stable for face in faces))

    def test_landmark_mapping_uses_boxes_not_list_order(self):
        faces = [observation(0), observation(250, (0., 1.))]
        faces[0].track_id, faces[1].track_id = "left", "right"
        scores = match_mouths(faces, [(250, 0, 100, 100), (0, 0, 100, 100)], [.8, .1])
        self.assertEqual(scores, {"right": .8, "left": .1})
        self.assertEqual(match_mouths(faces, [(0, 0, 100, 100)] * 2, [.1, .2]), {})


class AttributionTests(unittest.TestCase):
    def scenario(self):
        history = VisualHistory("native")
        clip = SpeechClip(b"", 0, 3.7, ((.5, 1.5), (1.7, 2.7)), "native")
        turns = (
            SpeechTurn("one", clip.clip_id, clip.recorded_at, "My name is Jon", "speaker_0", .5, 1.5, ((.5, 1.5),)),
            SpeechTurn("two", clip.clip_id, clip.recorded_at, "Hello Jon, I am Sam", "speaker_1", 1.7, 2.7, ((1.7, 2.7),)),
        )
        for index in range(38):
            at = index / 10
            motion = .24 if index % 2 else .45
            history.add(FrameEvidence(at, (
                FaceEvidence("a", A, motion if .5 <= at <= 1.5 else .05),
                FaceEvidence("b", B, motion if 1.7 <= at <= 2.7 else .05),
            )))
        return history, clip, turns

    def test_alternating_speakers_are_attributed_even_after_history_expires(self):
        history, clip, turns = self.scenario()
        snapshot = history.snapshot(clip)
        history.add(FrameEvidence(100, ()))
        self.assertEqual(len(history.frames), 1)
        self.assertEqual([turn.person_id for turn in snapshot.attribute_turns(clip, turns)], [A, B])

    def test_offscreen_competing_mouths_tracking_gaps_and_clock_mismatch(self):
        history, clip, turns = self.scenario()
        snapshot = history.snapshot(clip)
        silent = replace(snapshot, frames=tuple(replace(frame, faces=tuple(replace(face, mouth=.05) for face in frame.faces)) for frame in snapshot.frames))
        self.assertIsNone(silent.attribute(clip, turns[0]).person_id)
        overlap = replace(snapshot, frames=tuple(replace(frame, faces=(frame.faces[0], replace(frame.faces[1], mouth=frame.faces[0].mouth))) for frame in snapshot.frames))
        self.assertIsNone(overlap.attribute(clip, turns[0]).person_id)
        gap = replace(snapshot, frames=tuple(frame for frame in snapshot.frames if not .8 <= frame.at <= 1.2))
        self.assertIsNone(gap.attribute(clip, turns[0]).person_id)
        crossing = replace(snapshot, frames=tuple(replace(frame, faces=tuple(replace(face, stable=False) for face in frame.faces)) if frame.at == 1 else frame for frame in snapshot.frames))
        self.assertIsNone(crossing.attribute(clip, turns[0]).person_id)
        self.assertIsNone(snapshot.attribute(replace(clip, clock_source="windows"), turns[0]).person_id)

    def test_unenrolled_speaker_and_missing_competing_mouth_are_unassigned(self):
        history, clip, turns = self.scenario()
        snapshot = history.snapshot(clip)
        unknown = replace(snapshot, frames=tuple(replace(frame, faces=(replace(frame.faces[0], person_id=None), frame.faces[1])) for frame in snapshot.frames))
        self.assertIsNone(unknown.attribute(clip, turns[0]).person_id)
        self.assertEqual(unknown.attribute(clip, turns[1]).person_id, B)
        missing = replace(snapshot, frames=tuple(replace(frame, faces=(frame.faces[0], replace(frame.faces[1], mouth=None))) for frame in snapshot.frames))
        self.assertIsNone(missing.attribute(clip, turns[0]).person_id)

    def test_clip_local_voice_cannot_map_to_two_faces(self):
        history, clip, turns = self.scenario()
        turns = (turns[0], replace(turns[1], speaker_id="speaker_0"))
        self.assertTrue(all(turn.person_id is None for turn in history.snapshot(clip).attribute_turns(clip, turns)))


class CameraTests(unittest.TestCase):
    def test_camera_continues_when_microphone_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = SimpleNamespace(isOpened=lambda: True, read=lambda: (True, np.zeros((120, 160, 3), np.uint8)), release=lambda: None)
            with patch.dict(os.environ, {"ELEVENLABSKEY": "dummy"}, clear=True), \
                 patch("face_app.camera.platform.release", return_value="Linux"), \
                 patch("face_app.camera.FaceEngine", return_value=SimpleNamespace(gallery={}, observe=lambda *_: [])), \
                 patch("face_app.camera.cv2.VideoCapture", return_value=capture), \
                 patch("face_app.camera.open_microphone", side_effect=AudioError("no input")), \
                 patch("face_app.camera.cv2.imshow"), patch("face_app.camera.cv2.destroyAllWindows"), \
                 patch("face_app.camera.cv2.waitKey", return_value=ord("q")):
                run_camera(0, .363, Path(directory), Path(directory) / "data")

    def test_gemini_result_renames_image_and_refreshes_camera_label(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            people = PersonStore(root)
            person = people.enroll(PNG)
            turns = tuple(SpeechTurn(str(i), f"clip{i}", "2026-01-01", "My name is Jon", "speaker_0", 0, 1, person_id=person.id) for i in range(2))
            completed = queue.Queue()
            completed.put(turns)
            pipeline = SimpleNamespace(clips=queue.Queue(), completed=completed, notices=queue.Queue(), close=lambda: 0)
            analyzer = SimpleNamespace(
                analyze=lambda req: (IdentityProposal(person.id, "Jon", tuple(t.turn_id for t in req.turns), (), ()),),
                close=lambda: None,
            )

            class ImmediateWorker:
                def __init__(self, analyzer):
                    self.analyzer, self.completed = analyzer, queue.Queue()
                def submit(self, request):
                    self.completed.put((request, self.analyzer.analyze(request)))
                def close(self):
                    pass

            capture = SimpleNamespace(isOpened=lambda: True, read=lambda: (True, np.zeros((240, 320, 3), np.uint8)), release=lambda: None)
            labels = []
            with patch.dict(os.environ, {"ELEVENLABSKEY": "dummy", "GEMINI_API_KEY": "dummy"}, clear=True), \
                 patch("face_app.camera.platform.release", return_value="Windows"), \
                 patch("face_app.camera.FaceEngine", return_value=SimpleNamespace(gallery={}, observe=lambda *_: [observation(0, person_id=person.id)])), \
                 patch("face_app.camera.cv2.VideoCapture", return_value=capture), \
                 patch("face_app.camera.open_microphone"), patch("face_app.camera.ElevenLabsTranscriber"), \
                 patch("face_app.camera.VoicePipeline", return_value=pipeline), \
                 patch("face_app.camera.require_landmarker", return_value=Path("unused")), \
                 patch("face_app.camera.MouthObserver", return_value=SimpleNamespace(score=lambda *_: {}, close=lambda: None)), \
                 patch("face_app.camera.GeminiAnalyzer", return_value=analyzer), \
                 patch("face_app.identity.AnalysisWorker", ImmediateWorker), \
                 patch("face_app.camera._draw", side_effect=lambda _f, _o, store, *_s: labels.append(store.get(person.id).label)), \
                 patch("face_app.camera.cv2.imshow"), patch("face_app.camera.cv2.destroyAllWindows"), \
                 patch("face_app.camera.cv2.waitKey", side_effect=[-1, ord("q")]):
                run_camera(0, .363, root, root)
            self.assertEqual(labels[-1], "Jon")
            self.assertTrue((root / "faces" / "Jon.png").is_file())
            self.assertFalse((root / "voice_events.jsonl").exists())
            self.assertEqual(PersonStore(root).get(person.id).name, "Jon")


if __name__ == "__main__":
    unittest.main()
