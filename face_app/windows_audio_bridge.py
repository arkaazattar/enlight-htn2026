"""Stream Windows microphone PCM to the WSL parent; stdout is binary only."""

from __future__ import annotations

import argparse
import queue
import struct
import sys
import time

from .audio import BLOCK_SAMPLES, SAMPLE_RATE, capture_interval


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int)
    args = parser.parse_args()
    try:
        import sounddevice as sd
        blocks: queue.Queue[tuple[float, bytes, bool]] = queue.Queue(maxsize=100)
        dropped = False

        def callback(indata, frames, time_info, status):
            nonlocal dropped
            _, end, valid = capture_interval(frames, time_info, time.perf_counter())
            try:
                blocks.put_nowait((end, bytes(indata), bool(status) or dropped or not valid))
                dropped = False
            except queue.Full:
                dropped = True

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCK_SAMPLES, device=args.device,
            channels=1, dtype="int16", callback=callback,
        ):
            while True:
                end, pcm, discontinuity = blocks.get()
                sys.stdout.buffer.write(struct.pack("!IdB", len(pcm), end, discontinuity))
                sys.stdout.buffer.write(pcm)
                sys.stdout.buffer.flush()
    except BrokenPipeError:
        return 0
    except Exception as exc:
        message = f"Windows microphone error: {exc}".encode(errors="replace")[:4096]
        try:
            sys.stdout.buffer.write(struct.pack("!II", 0, len(message)) + message)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
