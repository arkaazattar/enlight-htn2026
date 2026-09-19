"""Entry point: python -m tracker_engine"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from .main import run


def _load_env() -> None:
    """Load .env from project root."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main() -> None:
    _load_env()

    parser = argparse.ArgumentParser(
        prog="tracker_engine",
        description="Face + voice identity tracker.",
    )
    parser.add_argument("--camera", type=int, default=0, metavar="N",
                        help="Camera device index (default: 0)")
    parser.add_argument("--threshold", type=float, default=0.36, metavar="T",
                        help="Face recognition cosine similarity threshold (default: 0.36)")
    parser.add_argument("--mic", type=int, default=None, metavar="N",
                        help="Microphone device index (default: system default)")
    args = parser.parse_args()

    try:
        run(
            camera_index=args.camera,
            threshold=args.threshold,
            mic_device=args.mic,
        )
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
