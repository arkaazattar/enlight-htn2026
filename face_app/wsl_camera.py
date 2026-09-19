"""Read camera frames from a Windows Python process while running in WSL."""

from __future__ import annotations

import os
import select
import struct
import subprocess
from pathlib import Path

import cv2
import numpy as np


MAX_FRAME_BYTES = 10 * 1024 * 1024
READ_TIMEOUT_SECONDS = 15


class BridgeError(Exception):
    """The Windows-to-WSL camera stream could not be used."""


class WindowsCameraSource:
    def __init__(self, camera_index: int, project_root: Path, windows_python: Path | None = None):
        executable = windows_python or project_root / ".venv-win" / "Scripts" / "python.exe"
        if not executable.is_file():
            raise BridgeError(
                f"Windows Python was not found at {executable}. Set up .venv-win as shown "
                "in README.md, or pass --windows-python with its Linux path."
            )
        if not os.access(executable, os.X_OK):
            raise BridgeError(f"Run 'chmod u+x {executable}' in WSL, then retry.")
        try:
            self.process = subprocess.Popen(
                [str(executable), "-u", "-m", "face_app.windows_camera_bridge", "--camera", str(camera_index)],
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError as exc:
            raise BridgeError(f"Could not start Windows camera process: {exc}") from exc

    def _read_exact(self, count: int) -> bytes:
        assert self.process.stdout is not None
        chunks: list[bytes] = []
        remaining = count
        while remaining:
            ready, _, _ = select.select([self.process.stdout], [], [], READ_TIMEOUT_SECONDS)
            if not ready:
                raise BridgeError("Timed out waiting for a frame from the Windows camera process.")
            chunk = os.read(self.process.stdout.fileno(), remaining)
            if not chunk:
                raise BridgeError(
                    "Windows camera process exited before sending a full frame. "
                    "Check Windows camera access and the .venv-win OpenCV install."
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read(self) -> tuple[bool, np.ndarray | None]:
        frame_size = struct.unpack("!I", self._read_exact(4))[0]
        if frame_size == 0:
            error_size = struct.unpack("!I", self._read_exact(4))[0]
            if error_size > 4096:
                raise BridgeError("Windows camera process sent an invalid error message.")
            raise BridgeError(self._read_exact(error_size).decode("utf-8", errors="replace"))
        if frame_size > MAX_FRAME_BYTES:
            raise BridgeError("Windows camera process sent a frame larger than 10 MB.")
        payload = self._read_exact(frame_size)
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise BridgeError("Windows camera process sent an invalid JPEG frame.")
        return True, frame

    def release(self) -> None:
        if self.process.stdout is not None:
            self.process.stdout.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
