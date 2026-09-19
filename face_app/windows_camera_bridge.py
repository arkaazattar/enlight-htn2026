"""Capture a Windows camera and send JPEG frames to a WSL parent over stdout.

This module runs with Windows Python. Stdout is a binary protocol, so diagnostic
messages must never be printed there.
"""

from __future__ import annotations

import argparse
import struct
import sys

import cv2


def _send_error(message: str) -> None:
    payload = message.encode("utf-8", errors="replace")[:4096]
    sys.stdout.buffer.write(struct.pack("!II", 0, len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows camera source for WSL")
    parser.add_argument("--camera", type=int, default=0)
    args = parser.parse_args()

    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        capture.release()
        _send_error(f"Windows could not open camera {args.camera}. Check its index and camera permissions.")
        return 1

    try:
        while True:
            ready, frame = capture.read()
            if not ready or frame is None:
                _send_error(f"Windows camera {args.camera} stopped returning frames.")
                return 1
            encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not encoded:
                _send_error("Windows could not encode the camera frame.")
                return 1
            payload = jpeg.tobytes()
            sys.stdout.buffer.write(struct.pack("!I", len(payload)))
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
    except BrokenPipeError:
        return 0
    except cv2.error as exc:
        try:
            _send_error(f"Windows OpenCV camera error: {exc}")
        except BrokenPipeError:
            pass
        return 1
    finally:
        capture.release()


if __name__ == "__main__":
    raise SystemExit(main())
