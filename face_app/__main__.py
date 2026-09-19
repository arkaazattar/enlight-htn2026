"""Command line entry point for the local face recognition app."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import ModelError, download_models
from .storage import StoreError


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local webcam face recognition")
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download-models", help="Download and verify YuNet, SFace, and Face Landmarker")
    download.add_argument("--models-dir", type=Path, default=PROJECT_ROOT / "models")

    camera = commands.add_parser("camera", help="Open the webcam recognition window")
    camera.add_argument("--camera", type=int, default=0, help="OpenCV camera index (default: 0)")
    camera.add_argument("--threshold", type=float, default=0.363, help="Cosine match threshold")
    camera.add_argument("--models-dir", type=Path, default=PROJECT_ROOT / "models")
    camera.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    camera.add_argument("--windows-python", type=Path, help="Windows Python executable for the WSL camera bridge")
    camera.add_argument("--mic-device", type=int, help="Microphone input device index (default: system default)")

    args = parser.parse_args(argv)
    try:
        if args.command == "download-models":
            download_models(args.models_dir)
        else:
            try:
                from dotenv import load_dotenv
            except ImportError:
                print("Voice dependencies are missing. Run 'python -m pip install -r requirements.txt'.", file=sys.stderr)
                return 1
            load_dotenv(PROJECT_ROOT / ".env", override=False)
            try:
                from .camera import CameraError, run_camera
            except ModuleNotFoundError as exc:
                if exc.name in {"cv2", "numpy"}:
                    print("OpenCV is not installed. Run 'python -m pip install -r requirements.txt'.", file=sys.stderr)
                    return 1
                raise
            try:
                run_camera(args.camera, args.threshold, args.models_dir, args.data_dir, args.windows_python, args.mic_device)
            except CameraError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
    except (ModelError, StoreError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
