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

## Setup

Use Python 3.12 or newer on a laptop or desktop with a webcam, microphone, and
graphical desktop. From the cloned project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m face_app download-models
python -m face_app camera --camera 0
```

On Windows PowerShell, create the environment with `py -3.12 -m venv .venv-win`,
activate it with `.venv-win\Scripts\Activate.ps1`, and run the three `python`
commands above. Install requirements in a fresh environment: MediaPipe uses the
desktop `opencv-contrib-python` wheel, which supplies the same `cv2` camera and
recognition APIs as the earlier `opencv-python` installation. Do not install
both OpenCV wheels into one environment.
On native Ubuntu or Debian, microphone capture also needs the system package
`libportaudio2` (`sudo apt-get install libportaudio2`). WSL uses the Windows
microphone bridge described below.

`download-models` retrieves YuNet and SFace from the
[OpenCV model zoo](https://github.com/opencv/opencv_zoo) and the
[MediaPipe Face Landmarker model](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python).
It verifies their SHA-256 hashes. Models and local data are ignored by Git.

### Windows camera and microphone from WSL

WSL often has no direct `/dev/video` or microphone device. The app can capture
both through Windows Python and process them in WSL. Install Python 3.12 on
Windows, then run from the cloned project directory in WSL:

```bash
powershell.exe -NoProfile -Command "py -3.12 -m venv .venv-win"
powershell.exe -NoProfile -Command "& ./.venv-win/Scripts/python.exe -m pip install -r requirements-bridge.txt"
chmod u+x .venv-win/Scripts/python.exe
python -m face_app camera --camera 0
```

If the Windows environment is elsewhere, pass its Linux-visible Python path
with `--windows-python`. `--mic-device N` selects a microphone index; by default,
the system input device is used. Windows privacy settings must allow desktop apps
to access the camera and microphone. The Windows helper only captures media;
API keys stay in the WSL process.
The Windows bridge only needs the two packages in `requirements-bridge.txt`;
native Windows use needs the full `requirements.txt`.

## Speech and identity

Put the existing `ELEVENLABSKEY` in the ignored `.env` file or an environment
variable. The app captures microphone speech continuously, closes a clip after
about 800 ms of silence (or 15 seconds of continuous audio), and sends it to
ElevenLabs Scribe v2 for diarized transcription. It splits the result into speaker
turns and prints each turn with the matched person or the reason it was unassigned.
Raw audio is not saved. Batch transcription usually appears several seconds after
speech ends; network conditions affect the delay.

Gemini can use `GEMINI_API_KEY` in `.env`, or Google Cloud credentials with
`GOOGLE_GENAI_USE_ENTERPRISE=true`, `GOOGLE_CLOUD_PROJECT`, and
`GOOGLE_CLOUD_LOCATION`. For the Google Cloud option, install the
[Google Cloud CLI](https://cloud.google.com/sdk/docs/install) and run
`gcloud auth application-default login` in the same Windows or WSL environment
that runs the camera. Project and location alone do not authenticate requests.
The enterprise setting takes precedence if both methods are configured.
Gemini receives new attributed speech, recent dialogue, known participant names,
prior facts, and pending name evidence in the background. A name can emerge from
natural conversation; no fixed introduction phrase is required. Naming needs
support from two separate audio clips. Multiple turns within one clip, or retried
requests, count only once. Changing an existing name also needs explicit spoken
correction evidence. Names, facts, pending candidates, and their supporting text
are kept under the stable ID in the MongoDB person document. The Gemini model defaults
to `gemini-2.5-flash`; set `GEMINI_MODEL` to use another supported model.

Two people can share the frame and take turns. Mouth landmarks are matched to
independent face tracks, and the camera evidence is preserved while transcription
runs. A turn is linked only when one stable face clearly moves its mouth with
the speech and the other visible face has reliable, inactive mouth evidence.
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
3. Provide the same person's name in two separate clips, pausing for at least a
   second between clips. Confirm the Gemini status, live label, renamed face image,
   and stored facts. Existing known names should stay linked to the same person.
4. Restart and check recognition and saved context. Test a spoken name correction
   with corroboration in a separate clip. Name conflicts must preserve both faces.

Camera recognition continues if microphone capture or a provider is unavailable.
Real camera lighting, visibility, and audio timing affect attribution; ambiguous
turns deliberately keep the temporary identity.
