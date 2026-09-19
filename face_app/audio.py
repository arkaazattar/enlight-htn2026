"""Microphone capture on the current OS or through Windows from WSL."""

from __future__ import annotations

import os
import math
import platform
import queue
import select
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


SAMPLE_RATE = 16000
BLOCK_SAMPLES = 320  # 20 ms, accepted by WebRTC VAD.
MAX_AUDIO_PACKET = BLOCK_SAMPLES * 2 * 10


class AudioError(Exception):
    """A microphone or its Windows bridge cannot provide audio."""


@dataclass(frozen=True)
class AudioBlock:
    pcm: bytes
    start: float
    end: float
    discontinuity: bool = False


def capture_interval(frames: int, time_info, now: float) -> tuple[float, float, bool]:
    """Translate PortAudio's buffer ADC time into the camera's monotonic clock."""
    try:
        lag = float(time_info.currentTime) - float(time_info.inputBufferAdcTime)
        # Windows MME can dispatch a batch with one shared currentTime and ADC
        # times advancing 20 ms per block. Preserve that order, including a
        # small negative lag; clamping it would overlap consecutive buffers.
        valid = math.isfinite(lag) and -.1 <= lag <= 5
    except (AttributeError, TypeError, ValueError):
        lag, valid = 0.0, False
    start = now - lag if valid else now - frames / SAMPLE_RATE
    return start, start + frames / SAMPLE_RATE, valid


class NativeMicrophone:
    clock_source = "native"

    def __init__(self, device: int | None = None):
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise AudioError("Microphone support is missing; install requirements.txt and the PortAudio runtime.") from exc
        self.blocks: queue.Queue[AudioBlock] = queue.Queue(maxsize=250)
        self.error: str | None = None

        self.dropped = False

        def callback(indata, frames, time_info, status):
            start, end, valid = capture_interval(frames, time_info, time.perf_counter())
            block = AudioBlock(bytes(indata), start, end, bool(status) or self.dropped or not valid)
            try:
                self.blocks.put_nowait(block)
                self.dropped = False
            except queue.Full:
                self.dropped = True

        try:
            self.stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE, blocksize=BLOCK_SAMPLES, device=device,
                channels=1, dtype="int16", callback=callback,
            )
            self.stream.start()
        except Exception as exc:
            raise AudioError(f"Could not open microphone: {exc}") from exc

    def read(self, timeout: float = 0.5) -> AudioBlock | None:
        if self.error:
            error, self.error = self.error, None
            raise AudioError(error)
        try:
            return self.blocks.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


class WindowsMicrophone:
    clock_source = "windows"

    def __init__(self, project_root: Path, windows_python: Path | None, device: int | None):
        executable = windows_python or project_root / ".venv-win" / "Scripts" / "python.exe"
        if not executable.is_file():
            raise AudioError(f"Windows Python was not found at {executable}. See README.md.")
        if not os.access(executable, os.X_OK):
            raise AudioError(f"Run 'chmod u+x {executable}' in WSL, then retry.")
        args = [str(executable), "-u", "-m", "face_app.windows_audio_bridge"]
        if device is not None:
            args.extend(["--device", str(device)])
        try:
            self.process = subprocess.Popen(
                args, cwd=project_root, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            )
        except OSError as exc:
            raise AudioError(f"Could not start Windows microphone process: {exc}") from exc

    def _read_exact(self, count: int, timeout: float) -> bytes | None:
        assert self.process.stdout is not None
        chunks = []
        remaining = count
        while remaining:
            ready, _, _ = select.select([self.process.stdout], [], [], timeout)
            if not ready:
                if not chunks:
                    return None
                raise AudioError("Windows microphone stopped mid-packet.")
            chunk = os.read(self.process.stdout.fileno(), remaining)
            if not chunk:
                raise AudioError("Windows microphone process exited. Check microphone permissions and .venv-win setup.")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read(self, timeout: float = 0.5) -> AudioBlock | None:
        header = self._read_exact(4, timeout)
        if header is None:
            return None
        length = struct.unpack("!I", header)[0]
        if length == 0:
            size = struct.unpack("!I", self._read_exact(4, 2) or b"\0" * 4)[0]
            if size > 4096:
                raise AudioError("Windows microphone sent an invalid error packet.")
            raise AudioError((self._read_exact(size, 2) or b"").decode(errors="replace"))
        if length > MAX_AUDIO_PACKET or length % 2:
            raise AudioError("Windows microphone sent an invalid audio packet.")
        timestamp = self._read_exact(8, 2)
        flags = self._read_exact(1, 2)
        payload = self._read_exact(length, 2)
        if timestamp is None or payload is None or flags is None:
            raise AudioError("Windows microphone sent an incomplete audio packet.")
        end = struct.unpack("!d", timestamp)[0]
        return AudioBlock(payload, end - length / (SAMPLE_RATE * 2), end, bool(flags[0]))

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        if self.process.stdout is not None:
            self.process.stdout.close()


def open_microphone(project_root: Path, windows_python: Path | None, device: int | None):
    if "microsoft" in platform.release().lower():
        return WindowsMicrophone(project_root, windows_python, device)
    return NativeMicrophone(device)
