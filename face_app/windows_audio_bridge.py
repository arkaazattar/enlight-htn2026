"""Stream Windows microphone PCM to the WSL parent; stdout is binary only."""

from __future__ import annotations

import argparse
import queue
import struct
import sys
import time

from .audio import BLOCK_SAMPLES, SAMPLE_RATE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int)
    args = parser.parse_args()
    try:
        import sounddevice as sd
        blocks: queue.Queue[tuple[float, bytes]] = queue.Queue(maxsize=100)

        def callback(indata, _frames, _time_info, _status):
            try:
                blocks.put_nowait((time.perf_counter(), bytes(indata)))
            except queue.Full:
                pass

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCK_SAMPLES, device=args.device,
            channels=1, dtype="int16", callback=callback,
        ):
            while True:
                end, pcm = blocks.get()
                sys.stdout.buffer.write(struct.pack("!Id", len(pcm), end))
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
