# Webcam face recognition

A local Python app that recognizes faces saved from earlier webcam sessions. People
start with temporary IDs; you can name them from the live camera view. Face images
and the identity index stay on this computer.

## Setup

Use Python 3.12 or newer on a laptop or desktop with a webcam and a graphical
desktop. From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m face_app download-models
python -m face_app camera --camera 0
```

On Windows PowerShell, create the environment with `py -3.12 -m venv .venv-win`
and activate it with `.venv-win\Scripts\Activate.ps1`; then run the three `python`
commands above.
`download-models` retrieves the YuNet and SFace ONNX files from the official
[OpenCV model zoo](https://github.com/opencv/opencv_zoo) and checks their SHA-256
hashes. You can also place those exact files in `models/` yourself if this
computer cannot download them. Use `--camera 1` if your webcam is not device 0.

### Windows camera from WSL

If this project is in WSL2 and `/dev/video0` does not exist, Linux OpenCV cannot
open the built-in Windows camera directly. The app can capture through Windows
Python and stream frames into the WSL process. Install Python 3.12 on Windows,
then run these commands **from the cloned project directory in WSL**:

```bash
powershell.exe -NoProfile -Command "py -3.12 -m venv .venv-win"
powershell.exe -NoProfile -Command "& ./.venv-win/Scripts/python.exe -m pip install -r requirements.txt"
chmod u+x .venv-win/Scripts/python.exe
python -m face_app camera --camera 0
```

The Windows environment captures frames; the WSL environment performs detection,
recognition, enrollment, and naming. The same `models/` and `data/` directories
are used in both environments. If the Windows virtual environment lives elsewhere,
pass its Linux-visible executable path with `--windows-python`.

## Camera controls

| Key | Action |
| --- | --- |
| `e` | Enroll an unknown person when they are the only face in view. |
| `n` | Name or correct the name of the one enrolled person in view. Type the name in the terminal that launched the app. |
| `q` or `Esc` | Quit and release the camera. |

The window shows `Unknown` for an unrecognized face, `Seen before: person_...`
for an enrolled person without a name, and the person's name after naming.
Enrollment saves one aligned face image to `data/faces/`. Naming changes its
filename to `Name.png` and updates `data/people.json`. Both `data/` and
`models/` are ignored by Git. Names must be unique; the app will not overwrite
another image. Keep the terminal open while using the camera so you can enter a
name when prompted.

The initial cosine matching threshold is `0.363`, from the
[OpenCV face recognition tutorial](https://docs.opencv.org/4.12.0/d0/dd4/tutorial_dnn_face.html).
If needed for your camera and lighting, pass another value between 0 and 1 with
`--threshold`, for example `--threshold 0.4`. Face matching is approximate;
review the live results before enrolling or naming someone.

Voice transcription and the planned database are not implemented yet. The
stable ID in `data/people.json` is intended to carry forward when those are
added. If the app reports a missing or damaged saved image, restore that image
from backup before starting the camera; it will not silently forget a person.

Run the local storage tests with `python -m unittest discover -s tests -v`.
