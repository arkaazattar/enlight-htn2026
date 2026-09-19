# Webcam identity and speech context

A local Python app recognizes saved faces, tracks up to two people, enrolls each
stable unknown face after three seconds, and gathers speech context toward a name. Every person
keeps a stable ID even when their face image is renamed to `Name.png`.

Person records are stored in MongoDB. Set `MONGO_URI` in `.env` (also accepts
`MONGODB_URI`); `MONGODB_DATABASE` defaults to `face_app` and
`MONGODB_COLLECTION` defaults to `people`. MongoDB is required for enrollment
and loading saved people; there is no local JSON fallback.

Each document includes a stable `person_id`, nullable `name`, `image_paths`
(list of strings), and `note_paths` (list of strings), alongside saved facts and
supporting identity evidence. For example:

```json
{
  "person_id": "person_abcdef123456",
  "name": "Ada",
  "image_paths": ["faces/Ada.png"],
  "note_paths": ["notes/ada.txt"]
}
```

Images and notes remain files on disk; their paths are relative to the project's
`data/` directory, or `--data-dir` when running `python -m tracker_engine`.
New enrollments start with one image path and an empty note list. Naming renames
the first image to exactly `<name>.png`; additional images use `<name>_2.png`,
and so on. Existing note files can be attached through
`POST /people/{person_id}/notes` with `{"path": "notes/ada.txt"}`.

On startup, the tracker and API import an existing `data/people.json` into MongoDB,
preserving IDs, images, and saved context. After verification, the manifest is
archived as `people.json.migrated`. Existing database records take precedence on
retries. The migration retains the context file and leaves legacy speech logs
untouched. Keep MongoDB and the configured data directory together when moving
or backing up the app.

Run the tracker with `python -m tracker_engine --camera 0`, or the API with
`uvicorn tracker_engine.api:create_app --factory`. The API returns both path lists
and serves the first face image at `/people/{person_id}/image`.

## Setup and run

Use Python 3.12 or newer on a desktop with a webcam, microphone, and graphical
display. Run these commands from the cloned project directory. MongoDB must be
running and reachable through `MONGO_URI` before starting the tracker.
On Ubuntu or Debian, install `libportaudio2` for microphone capture with
`sudo apt-get install libportaudio2`.

### First run

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env-template .env
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv-win
.\.venv-win\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env-template .env
```

Edit `.env` and set `MONGO_URI` to your running MongoDB instance. Set
`ELEVENLABSKEY` for transcription and `GEMINI_API_KEY` for name and fact analysis.
Then, in the same activated terminal, download the face models and start the
tracker. These commands work in both shells:

```text
python -c "from pathlib import Path; from tracker_engine.models import download_models; download_models(Path('models'))"
python -m tracker_engine --camera 0
```

The download verifies YuNet and SFace from the
[OpenCV model zoo](https://github.com/opencv/opencv_zoo) and the
[MediaPipe Face Landmarker model](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python)
with SHA-256 hashes. Models and local data are ignored by Git. The current
tracker uses local camera and microphone devices; its earlier WSL Windows bridge
commands do not apply. Run it in Windows PowerShell if your devices are
available only to Windows.

### Later runs

From the project directory, activate the existing environment and start the
tracker. Keep MongoDB running; you do not need to reinstall dependencies or
download the models again.

On macOS or Linux:

```bash
source .venv/bin/activate
python -m tracker_engine --camera 0
```

On Windows PowerShell:

```powershell
.\.venv-win\Scripts\Activate.ps1
python -m tracker_engine --camera 0
```

Use `--camera 1` for a different webcam or `--mic N` for a specific microphone.

## Speech and identity

Put the existing `ELEVENLABSKEY` in the ignored `.env` file or an environment
variable. The app captures microphone speech continuously, closes a clip after
about 800 ms of silence (or 15 seconds of continuous audio), and sends it to
ElevenLabs Scribe v2 for diarized transcription. It splits the result into speaker
turns and prints each turn with the matched person or the reason it was unassigned.
Raw audio is not saved. Batch transcription usually appears several seconds after
speech ends; network conditions affect the delay.

Set `GEMINI_API_KEY` in `.env` or the environment to enable Gemini analysis.
Gemini receives new attributed speech, recent dialogue, known participant names,
prior facts, and pending name evidence in the background. A name can emerge from
natural conversation; no fixed introduction phrase is required. Naming needs
support from two separate audio clips. Multiple turns within one clip, or retried
requests, count only once. Changing an existing name also needs explicit spoken
correction evidence. Names, facts, pending candidates, and their supporting text
are kept under the stable ID in the MongoDB person document. The Gemini model defaults
to `gemini-2.5-flash`; set `GEMINI_MODEL` to use another supported model.
An exact, standalone introduction such as "My name is Eddie" is saved as name
evidence immediately after face attribution. A second distinct clip can confirm
a change from an existing name even while Gemini is processing other speech.

Two people can share the frame and take turns. Mouth landmarks are matched to
independent face tracks, and the camera evidence is preserved while transcription
runs. A turn is linked only when one stable face clearly moves its mouth with
the speech and the other visible face has reliable, inactive mouth evidence.
The app combines jaw and lip opening and compares movement with each person's
nearby quiet samples. If neither face clearly moves, both move, or the second
face's movement is uncertain, the terminal reports that reason and leaves the
turn unassigned.
Very short turns, overlapping voices, offscreen speech, uncertain tracking, and
more than two visible people stay unassigned. Unassigned speech provides context
but cannot authorize a name or fact. Diarization labels identify voices only within
each clip; they do not identify faces across clips.

Unknown faces enroll independently after three stable seconds, including when
another person is visible. Faces must be at least 80 pixels wide and tall.
Crossings and uncertain matches pause enrollment and attribution. A temporary
label is `Seen before: person_...`; confirmed names rename the saved image to
`Name.png` and immediately update the camera label.

New transcripts are not written to a transcript log. The latest 30 dialogue turns
and up to 128 pending attributed turns remain in memory. Transient Gemini failures
retry with backoff from two seconds up to 60 seconds; authentication or configuration
failures require fixing the problem and restarting. Pending speech can be lost
when the app closes, and the terminal reports queued speech discarded on exit.
Persisted name candidates and facts survive restarts.
If `data/person_context.json` is empty, the app initializes it as a new context
and reports that no earlier evidence was present. A malformed nonempty context
is left untouched so its evidence can be recovered from a backup.

If an old `data/voice_events.jsonl` exists, the app preserves saved fact evidence
and replays eligible attributed events before removing it. Failed migration leaves
the old log intact. Previously unassigned events stay unassigned. No new speech
is appended to that legacy file.

The window's only control is `q` or `Esc` to quit. Recognition and auto-enrollment
continue if the microphone or a provider is unavailable; the app prints a status
explaining the missing capability. Use `--camera 1` if the webcam is not device 0.
The initial cosine match threshold is `0.363`, from the
[OpenCV face recognition tutorial](https://docs.opencv.org/4.12.0/d0/dd4/tutorial_dnn_face.html).
Adjust it with `--threshold` for the actual camera and lighting.

Run automated checks with `python -m unittest discover -s tests -v`.

## Manual check on Windows and WSL

1. Run the camera command with two people clearly visible. Keep faces apart and
   stable for several seconds; each unknown person should receive a temporary ID.
2. Take turns speaking for at least a second. The terminal should show each turn
   under the correct person's label. Speak simultaneously to confirm uncertain
   turns remain unassigned, with an explanation.
3. Have an unnamed person say "my name is Ben" in one clearly attributed clip.
   Confirm the Gemini status, live label, and renamed face image. A name learned
   indirectly from conversation still needs two separate clips.
4. Restart and check recognition and saved context. Test a spoken name correction
   in two separate clips. Name conflicts must preserve both faces.

Camera recognition continues if microphone capture or a provider is unavailable.
Real camera lighting, visibility, and audio timing affect attribution; ambiguous
turns deliberately keep the temporary identity.
If a transcript says `unassigned`, Gemini cannot use it to name the face. The
reason in brackets distinguishes a turn that is too short, missing synchronized
video, uncertain mouth movement, and other cases. Indirect name evidence and
corrections need two attributed clips with a pause long enough to close the first.
If startup reports a missing saved face image, restore that exact image from backup before starting;
do not substitute another person's face for the manifest entry.
