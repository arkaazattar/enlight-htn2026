# Webcam identity and speech context

A local Python app recognizes saved faces, enrolls a clearly isolated unknown
face after three seconds, and gathers speech context toward a name. Every person
keeps a stable ID even when their face image is renamed to `Name.png`.

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
about 800 ms of silence, and sends it to ElevenLabs Scribe v2 for diarized
transcription. Completed text is printed in the terminal and saved temporarily
to `data/voice_events.jsonl`. Raw audio is not saved. Batch transcription usually
appears several seconds after speech ends; network conditions affect the delay.

Add `GEMINI_API_KEY` to `.env` when it is available. The app then processes saved
and new attributed transcripts with Gemini. It can assign a name only after two
separate clips support the same identity. A correction to an existing name also
needs an explicit spoken correction. Other supported facts are kept in
`data/person_context.json` with transcript evidence. The Gemini model defaults
to `gemini-2.5-flash`; set `GEMINI_MODEL` to use another supported model.

Speech is linked to a face only when one enrolled person is visible, mouth
movement aligns with the audio, and ElevenLabs reports one speaker. Overlapping
voices, offscreen speech, multiple faces, and uncertain clips stay unassigned.
Unassigned transcripts remain available as context but cannot themselves name
a face. An unknown face must first remain clearly isolated for three seconds to
be auto-enrolled; its initial label is `Seen before: person_...`.

The window's only control is `q` or `Esc` to quit. Recognition and auto-enrollment
continue if the microphone or a provider is unavailable; the app prints a status
explaining the missing capability. Use `--camera 1` if the webcam is not device 0.
The initial cosine match threshold is `0.363`, from the
[OpenCV face recognition tutorial](https://docs.opencv.org/4.12.0/d0/dd4/tutorial_dnn_face.html).
Adjust it with `--threshold` for the actual camera and lighting.

Run automated checks with `python -m unittest discover -s tests -v`.
